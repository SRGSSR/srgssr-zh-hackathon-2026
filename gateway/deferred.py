"""Deferred chat completions: the gateway, not every application, keeps a request that cannot
be served within the commune's rule right now, and completes it once an approved endpoint is back.

Loaded like any LiteLLM callback (litellm_settings.callbacks: ["deferred.deferred_plugin"]).
On import it adds these routes to the proxy's FastAPI app and starts a background worker:

    POST /v1/deferred/chat/completions   body = a chat completion request -> 202 {"id", "status": "queued"}
    GET  /v1/deferred/jobs?id=...        one job (status, result, timeline summary)
    GET  /v1/deferred/jobs?status=a,b    the caller's jobs
    GET  /v1/deferred/events?id=...      the job's timeline (routing decisions, sends, outcomes)
    POST /v1/deferred/retry  {"id"}      try a waiting job now
    POST /v1/deferred/cancel {"id"}      cancel it (its request body is deleted)

Paths are fixed strings (ids go in the query or body) because LiteLLM's allowed_routes matches
exact paths. Every route uses LiteLLM's normal key authentication; a job is visible only to the
key that submitted it.

The worker calls the router directly with the routing policy captured from the key at submit
time, so every attempt still passes through gateway/policy.py (filter before each attempt,
last check before each send). The proxy-level request check (layer 1) runs at submit.

LiteLLM has no official API for adding endpoints; this relies on the proxy exposing its FastAPI
app (tested on litellm-database v1.98.0). See docs/findings.md, open questions.
"""

import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth

import store
from policy import PolicyViolation, check_request, pick_policy, policy_hook

RETRY_BASE_SECONDS = float(os.environ.get("DEFERRED_RETRY_BASE_SECONDS", "2"))
RETRY_MAX_SECONDS = float(os.environ.get("DEFERRED_RETRY_MAX_SECONDS", "20"))
MAX_AGE_SECONDS = float(os.environ.get("DEFERRED_MAX_AGE_SECONDS", str(24 * 3600)))
POLL_SECONDS = 1.0

# A deferred request is a plain chat completion; anything that could steer routing is refused.
ALLOWED_BODY_KEYS = {
    "model", "messages", "temperature", "top_p", "max_tokens", "max_completion_tokens", "stop", "seed",
    "presence_penalty", "frequency_penalty", "response_format", "n", "user", "metadata",
}
MAX_CLIENT_METADATA_BYTES = 2048

WAIT_REASON = (
    "No approved endpoint is available right now. The request stays in the gateway's local store, "
    "inside the authorized environment, and is not sent anywhere else. It is retried automatically."
)

router = APIRouter()
_inflight: set = set()
_worker_task: Optional[asyncio.Task] = None


# ------------------------------------------------------------------------------ helpers
def _owner(auth: UserAPIKeyAuth) -> str:
    return hashlib.sha256(str(auth.api_key or auth.token or "").encode()).hexdigest()[:32]


def _event(job_id: str, **event) -> None:
    policy_hook._emit({"job_id": job_id, **event})  # stdout + gateway store


def _backoff(runs: int) -> float:
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** max(0, runs - 1)))


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, PolicyViolation) or "blocked before send" in str(exc):
        return False  # the rule itself refused the send: waiting will not change that
    return getattr(exc, "status_code", None) not in (400, 404, 422)


def _public(job: dict) -> dict:
    result = json.loads(job["result_json"]) if job.get("result_json") else None
    return {
        "id": job["id"],
        "object": "deferred.chat.completion",
        "status": job["status"],
        "status_reason": job.get("status_reason"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "runs": job["runs"],
        "next_retry_at": job.get("next_retry_at"),
        "inflight": job["id"] in _inflight,
        "request_retained": job.get("request_json") is not None,
        "served_by": job.get("served_by"),
        "result": result,
        "metadata": json.loads(job.get("client_metadata_json") or "{}"),
        "error": (job.get("error") or "")[:500] or None,
    }


def _own_job(job_id: str, auth: UserAPIKeyAuth) -> dict:
    job = store.get_job(job_id or "")
    if not job or job["owner"] != _owner(auth):
        raise HTTPException(status_code=404, detail="deferred job not found")
    return job


# ------------------------------------------------------------------------------- routes
@router.post("/v1/deferred/chat/completions", status_code=202)
async def submit(request: Request, auth: UserAPIKeyAuth = Depends(user_api_key_auth)):
    _ensure_worker()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    policy = pick_policy(auth.metadata or {}, auth.team_metadata or {})
    problems = [f"body parameter '{k}' is not supported for deferred requests" for k in sorted(set(body) - ALLOWED_BODY_KEYS)]
    problems += check_request(policy, body, dict(request.headers), auth.models)
    if not body.get("model") or not isinstance(body.get("messages"), list) or not body["messages"]:
        problems.append("'model' and a non-empty 'messages' list are required")
    client_md = body.get("metadata") or {}
    if len(json.dumps(client_md)) > MAX_CLIENT_METADATA_BYTES:
        problems.append("metadata is too large")
    if problems:
        policy_hook._emit({"type": "request_rejected", "key_alias": auth.key_alias, "reasons": problems, "deferred": True})
        raise HTTPException(status_code=400, detail={"error": "rejected by routing policy", "reasons": problems})

    job_id = "def-" + uuid.uuid4().hex[:12]
    request_body = {k: v for k, v in body.items() if k != "metadata"}
    auth_snapshot = {
        "metadata": auth.metadata or {},
        "team_metadata": auth.team_metadata or {},
        "key_alias": auth.key_alias,
        "team_id": auth.team_id,
    }
    store.create_job(job_id, _owner(auth), auth.key_alias, auth.team_id, auth_snapshot, request_body, client_md)
    _event(job_id, type="job_created", model_group=body["model"])
    if policy:
        _event(job_id, type="request_accepted", key_alias=auth.key_alias, policy_id=policy.get("id"),
               rule=policy.get("description"), model_group=body["model"])
    return _public(store.get_job(job_id))


@router.get("/v1/deferred/jobs")
async def jobs(id: Optional[str] = None, status: Optional[str] = None, limit: int = 20,
               auth: UserAPIKeyAuth = Depends(user_api_key_auth)):
    if id:
        return _public(_own_job(id, auth))
    statuses = [s for s in (status or "").split(",") if s]
    return {"object": "list", "data": [_public(j) for j in store.list_jobs(_owner(auth), statuses, min(limit, 200))]}


@router.get("/v1/deferred/events")
async def events(id: str, auth: UserAPIKeyAuth = Depends(user_api_key_auth)):
    _own_job(id, auth)
    return {"object": "list", "data": store.events(id)}


@router.post("/v1/deferred/retry")
async def retry(request: Request, auth: UserAPIKeyAuth = Depends(user_api_key_auth)):
    _ensure_worker()
    job = _own_job((await request.json()).get("id"), auth)
    if store.transition(job["id"], ("waiting",), next_retry_at=None):
        _event(job["id"], type="retry_requested")
    return _public(store.get_job(job["id"]))


@router.post("/v1/deferred/cancel")
async def cancel(request: Request, auth: UserAPIKeyAuth = Depends(user_api_key_auth)):
    job = _own_job((await request.json()).get("id"), auth)
    if store.transition(job["id"], ("queued", "waiting", "running"), status="cancelled", status_reason="Cancelled by the caller."):
        _event(job["id"], type="job_cancelled")
    return _public(store.get_job(job["id"]))


# ------------------------------------------------------------------------------- worker
async def _run(job_id: str) -> None:
    job = store.get_job(job_id)
    if not job or job["status"] not in ("queued", "waiting"):
        return
    runs = job["runs"] + 1
    resumed = job["status"] == "waiting"
    if not store.transition(job_id, ("queued", "waiting"), status="running", runs=runs, status_reason=None):
        return
    _event(job_id, type="job_resumed" if resumed else "job_started", run=runs)

    from litellm.proxy.proxy_server import llm_router

    auth = json.loads(job["auth_json"])
    request_body = json.loads(job["request_json"])
    # Server-side metadata only: the same fields the proxy attaches to a normal request.
    md = {
        "user_api_key_metadata": auth.get("metadata") or {},
        "user_api_key_team_metadata": auth.get("team_metadata") or {},
        "user_api_key_alias": auth.get("key_alias"),
        "user_api_key_team_id": auth.get("team_id"),
        "deferred_job_id": job_id,
    }
    try:
        response = await llm_router.acompletion(**request_body, metadata=md)
    except Exception as exc:
        policy_hook.report_final_failure(md, exc)
        if _retryable(exc):
            wait = _backoff(runs)
            if store.transition(job_id, ("running",), status="waiting", next_retry_at=time.time() + wait,
                                status_reason=WAIT_REASON, error=str(exc)[:1000]):
                _event(job_id, type="job_waiting", run=runs, retry_in_s=wait, gateway_error=str(exc)[:300])
        else:
            if store.transition(job_id, ("running",), status="failed", status_reason="The request cannot be served.",
                                error=str(exc)[:1000]):
                _event(job_id, type="job_failed", error=str(exc)[:300])
        return

    served_by = (getattr(response, "_hidden_params", None) or {}).get("model_id")
    result = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    if store.transition(job_id, ("running",), status="done", status_reason=None, error=None,
                        result_json=json.dumps(result, default=str), served_by=served_by):
        _event(job_id, type="job_done", deployment_id=served_by)


async def _guarded(job_id: str) -> None:
    try:
        await _run(job_id)
    except Exception as e:  # never lose a job: park it and retry later
        store.transition(job_id, ("running",), status="waiting", next_retry_at=time.time() + RETRY_MAX_SECONDS,
                         status_reason="Unexpected gateway error, retrying.", error=repr(e)[:1000])
        print(f"DEFERRED_WORKER_ERROR {job_id} {e!r}", flush=True)
    finally:
        _inflight.discard(job_id)


async def _loop() -> None:
    # Jobs that were running when the gateway stopped are resumed, never lost.
    for job_id in store.interrupted_jobs():
        if store.transition(job_id, ("running",), status="waiting", next_retry_at=None, status_reason="Gateway restarted."):
            _event(job_id, type="job_resumed_after_restart")
    while True:
        try:
            now = time.time()
            for job_id in store.expirable_jobs(now - MAX_AGE_SECONDS):
                if store.transition(job_id, ("queued", "waiting"), status="expired", status_reason="Expired before an approved endpoint was available."):
                    _event(job_id, type="job_expired")
            for job_id in store.due_jobs(now):
                if job_id not in _inflight:
                    _inflight.add(job_id)
                    asyncio.get_running_loop().create_task(_guarded(job_id))
        except Exception as e:
            print(f"DEFERRED_LOOP_ERROR {e!r}", flush=True)
        await asyncio.sleep(POLL_SECONDS)


def _ensure_worker() -> None:
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    try:
        _worker_task = asyncio.get_running_loop().create_task(_loop())
    except RuntimeError:
        pass  # no running loop yet; the first request starts it


# ------------------------------------------------------------------ registration
class DeferredPlugin(CustomLogger):
    """No-op logger: exists so LiteLLM imports this module from litellm_settings.callbacks."""


def _register() -> None:
    from litellm.proxy.proxy_server import app

    if not any(getattr(r, "path", None) == "/v1/deferred/chat/completions" for r in app.routes):
        app.include_router(router)
    _ensure_worker()  # the callback is imported inside the proxy's startup, so a loop is running


deferred_plugin = DeferredPlugin()
_register()
