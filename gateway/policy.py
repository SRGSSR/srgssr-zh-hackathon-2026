"""Commune routing policy for the LiteLLM proxy (v1.92.0).

The policy is bound to the commune's API key (see custom_auth.py) and is read ONLY from
the server-side key metadata that the proxy attaches to every request
(metadata["user_api_key_metadata"]["routing_policy"]). Nothing the client sends can change it.

Three layers, all in this one CustomLogger (registered via litellm_settings.callbacks):

1. async_pre_call_hook (proxy, once per request)
   Rejects requests that try to steer routing: client-side fallbacks, api_base/base_url/api_key,
   tags (any location), litellm_metadata, mock_* params, deployment ids as model, unknown
   metadata keys, x-litellm-tags header. Phase 0 showed several of these bypass tag routing,
   and client "fallbacks" with an api_base can send data (and the upstream key) to any host.

2. async_filter_deployments (router, before EVERY attempt: first try, retries, fallbacks)
   Keeps only deployments whose model_info carries complete metadata (fail closed) and whose
   jurisdiction is allowed. Among those it returns the single highest-priority one that has
   not already failed within this request, so the order is deterministic
   (LiteLLM 1.92.0 has no deployment "order"). Returning [] makes the router raise
   "No deployments available", which the app treats as "wait and retry later".

3. async_pre_call_deployment_hook (right before each send)
   Last check on the concrete request: the deployment must still pass the policy and the
   api_base about to be used must equal the api_base configured for that deployment id.
   Anything else raises before a single byte leaves the gateway.

Every decision and every attempt outcome is emitted as an event to the citizen app
(EVENT_SINK_URL) and to stdout, which builds the per-job timeline.
"""

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from litellm.integrations.custom_logger import CustomLogger

REQUIRED_METADATA = ("provider", "country", "jurisdiction")

# Request body keys that can influence routing or credentials. Rejected outright.
FORBIDDEN_BODY_KEYS = {
    "fallbacks",
    "context_window_fallbacks",
    "content_policy_fallbacks",
    "api_base",
    "base_url",
    "api_key",
    "api_version",
    "custom_llm_provider",
    "user_config",
    "litellm_metadata",
    "tags",
    "model_list",
    "router_settings",
    "deployment_id",
    "specific_deployment",
    "mock_response",
    "mock_testing_fallbacks",
    "mock_testing_context_fallbacks",
    "mock_testing_content_policy_fallbacks",
    "extra_headers",
    "extra_body",
}
# The proxy adds its own keys into body["metadata"] before our hook runs, so client metadata
# cannot be allow-listed here. Instead, block the keys that steer routing or impersonate
# server-side fields (the proxy overwrites user_api_key_* itself).
FORBIDDEN_METADATA_KEYS = {
    "tags",
    "model_info",
    "deployment",
    "api_base",
    "fallbacks",
    "model_group",
    "routing_policy",
    "_policy_tried",
    "disable_fallbacks",
}
FORBIDDEN_HEADERS = {"x-litellm-tags"}

EVENT_SINK_URL = os.environ.get("EVENT_SINK_URL", "")
EVENT_SINK_TOKEN = os.environ.get("EVENT_SINK_TOKEN", "")


class PolicyViolation(Exception):
    """Raised when a send would violate the commune's routing policy."""


def _now() -> float:
    return time.time()


def _router():
    try:
        from litellm.proxy.proxy_server import llm_router

        return llm_router
    except Exception:
        return None


def _norm_base(url: Optional[str]) -> str:
    if not url:
        return ""
    p = urlsplit(str(url))
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}".lower()


def _md(kwargs: Optional[dict]) -> dict:
    if not kwargs:
        return {}
    md = kwargs.get("metadata")
    if not md:
        md = (kwargs.get("litellm_params") or {}).get("metadata")
    return md or {}


def _policy_from_md(md: dict) -> Optional[dict]:
    key_md = md.get("user_api_key_metadata") or {}
    policy = key_md.get("routing_policy")
    if not isinstance(policy, dict) or not policy.get("allowed_jurisdictions"):
        return None
    return policy


def _job_id(md: dict) -> Optional[str]:
    return md.get("job_id") or (md.get("requester_metadata") or {}).get("job_id")


def _mi(deployment: dict) -> dict:
    return deployment.get("model_info") or {}


def evaluate(deployment: dict, policy: dict) -> Dict[str, Any]:
    """Pure policy decision for one deployment. Fail closed on missing metadata."""
    mi = _mi(deployment)
    info = {
        "deployment_id": mi.get("id"),
        "provider": mi.get("provider"),
        "country": mi.get("country"),
        "jurisdiction": mi.get("jurisdiction"),
        "endpoint_kind": mi.get("endpoint_kind"),
        "priority": mi.get("priority", 100),
    }
    missing = [f for f in REQUIRED_METADATA if not mi.get(f)]
    if missing:
        return {**info, "allowed": False, "reason": f"missing metadata: {', '.join(missing)} (fail closed)"}
    allowed = policy.get("allowed_jurisdictions") or []
    if mi["jurisdiction"] not in allowed:
        return {**info, "allowed": False, "reason": f"jurisdiction {mi['jurisdiction']} not in {allowed}"}
    return {**info, "allowed": True, "reason": f"jurisdiction {mi['jurisdiction']} allowed"}


class CommunePolicy(CustomLogger):
    def __init__(self):
        super().__init__()
        self._client: Optional[httpx.AsyncClient] = None

    # ---------------------------------------------------------------- events
    def _emit(self, event: dict) -> None:
        event.setdefault("ts", _now())
        print("POLICY_EVENT " + json.dumps(event, default=str), flush=True)
        if not EVENT_SINK_URL:
            return
        try:
            asyncio.get_running_loop().create_task(self._post(event))
        except RuntimeError:
            pass

    async def _post(self, event: dict) -> None:
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=3)
            await self._client.post(EVENT_SINK_URL, json=event, headers={"x-internal-token": EVENT_SINK_TOKEN})
        except Exception as e:  # the timeline must never break the request path
            print(f"POLICY_EVENT_SINK_ERROR {type(e).__name__}: {e}", flush=True)

    # ------------------------------------------------- layer 1: request shape
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        key_md = getattr(user_api_key_dict, "metadata", None) or {}
        policy = key_md.get("routing_policy")
        psr = data.get("proxy_server_request") or {}
        body = psr.get("body") or {}
        headers = {k.lower(): v for k, v in (psr.get("headers") or {}).items()}
        client_md = body.get("metadata") or {}
        job_id = client_md.get("job_id") if isinstance(client_md, dict) else None

        problems: List[str] = []
        if not isinstance(policy, dict) or not policy.get("allowed_jurisdictions"):
            problems.append("no routing policy bound to this API key")
        problems += [f"body parameter '{k}' is not allowed" for k in sorted(FORBIDDEN_BODY_KEYS & set(body))]
        if isinstance(client_md, dict):
            problems += [f"metadata key '{k}' is not allowed" for k in sorted(FORBIDDEN_METADATA_KEYS & set(client_md))]
        elif client_md:
            problems.append("metadata must be an object")
        problems += [f"header '{h}' is not allowed" for h in sorted(FORBIDDEN_HEADERS & set(headers))]
        allowed_models = list(getattr(user_api_key_dict, "models", None) or [])
        if allowed_models and body.get("model") not in allowed_models:
            problems.append(f"model '{body.get('model')}' is not allowed for this key (allowed: {allowed_models})")

        if problems:
            self._emit(
                {
                    "type": "request_rejected",
                    "job_id": job_id,
                    "key_alias": getattr(user_api_key_dict, "key_alias", None),
                    "reasons": problems,
                }
            )
            raise HTTPException(status_code=400, detail={"error": "rejected by routing policy", "reasons": problems})

        self._emit(
            {
                "type": "request_accepted",
                "job_id": job_id,
                "key_alias": getattr(user_api_key_dict, "key_alias", None),
                "policy_id": policy.get("id"),
                "rule": policy.get("description"),
                "model_group": body.get("model"),
            }
        )
        return data

    # ------------------------------- layer 2: before every attempt (router)
    async def async_filter_deployments(
        self,
        model: str,
        healthy_deployments: List[dict],
        messages=None,
        request_kwargs: Optional[dict] = None,
        parent_otel_span=None,
    ) -> List[dict]:
        md = _md(request_kwargs)
        policy = _policy_from_md(md)
        job_id = _job_id(md)

        # Deployment tried by the previous attempt of this request (the router writes it into the
        # shared request metadata). If we are here again, that attempt failed.
        tried: List[str] = md.setdefault("_policy_tried", [])
        last = (md.get("model_info") or {}).get("id")
        if last and last not in tried:
            tried.append(last)

        router = _router()
        group = router.get_model_list(model_name=model) if router else None
        group = group or healthy_deployments
        healthy_ids = {_mi(d).get("id") for d in healthy_deployments}

        evaluated, candidates = [], []
        for d in group:
            if policy is None:
                e = {"deployment_id": _mi(d).get("id"), "provider": _mi(d).get("provider"), "jurisdiction": _mi(d).get("jurisdiction"),
                     "endpoint_kind": _mi(d).get("endpoint_kind"), "allowed": False, "reason": "no routing policy on key (fail closed)"}
            else:
                e = evaluate(d, policy)
            if e["allowed"] and e["deployment_id"] in tried:
                e = {**e, "allowed": False, "reason": "already failed in this request"}
            elif e["allowed"] and e["deployment_id"] not in healthy_ids:
                e = {**e, "allowed": False, "reason": "skipped by router (cooldown)"}
            evaluated.append(e)
            if e["allowed"]:
                candidates.append((e.get("priority", 100), e["deployment_id"], d))

        candidates.sort(key=lambda c: (c[0], str(c[1])))
        chosen = candidates[0][2] if candidates else None
        chosen_id = _mi(chosen).get("id") if chosen else None
        for e in evaluated:
            if e["deployment_id"] == chosen_id:
                e["decision"] = "selected"
            elif e["allowed"]:
                e["decision"] = "standby"
            else:
                e["decision"] = "blocked_before_send"
        self._emit(
            {
                "type": "routing_decision",
                "job_id": job_id,
                "model_group": model,
                "attempt": len(tried) + 1,
                "selected": chosen_id,
                "evaluated": evaluated,
            }
        )
        return [chosen] if chosen else []

    # --------------------------- layer 3: last check right before the send
    async def async_pre_call_deployment_hook(self, kwargs: Dict[str, Any], call_type) -> Optional[dict]:
        md = _md(kwargs)
        policy = _policy_from_md(md)
        mi = kwargs.get("model_info") or (kwargs.get("litellm_params") or {}).get("model_info") or {}
        dep_id = mi.get("id")
        api_base = kwargs.get("api_base") or (kwargs.get("litellm_params") or {}).get("api_base")
        router = _router()
        configured = router.get_deployment(model_id=dep_id) if (router and dep_id) else None
        configured_dict = configured.model_dump() if hasattr(configured, "model_dump") else (configured or {})
        configured_base = (configured_dict.get("litellm_params") or {}).get("api_base")

        reason = None
        if policy is None:
            reason = "no routing policy on key (fail closed)"
        elif not configured_dict:
            reason = f"deployment '{dep_id}' is not in the gateway config"
        else:
            verdict = evaluate(configured_dict, policy)
            if not verdict["allowed"]:
                reason = verdict["reason"]
            elif _norm_base(api_base) != _norm_base(configured_base):
                reason = f"api_base '{api_base}' differs from the configured one for '{dep_id}'"

        event = {
            "type": "dispatch" if reason is None else "send_vetoed",
            "job_id": _job_id(md),
            "call_id": kwargs.get("litellm_call_id"),
            "deployment_id": dep_id,
            "provider": mi.get("provider"),
            "country": mi.get("country"),
            "jurisdiction": mi.get("jurisdiction"),
            "endpoint_kind": mi.get("endpoint_kind"),
            "api_base": api_base,
            "attempt": len(md.get("_policy_tried") or []) + 1,
        }
        if reason:
            event["reason"] = reason
            self._emit(event)
            raise PolicyViolation(f"blocked before send: {reason}")
        self._emit(event)
        return None

    # --------------------------------------------------------- outcomes
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        mi = lp.get("model_info") or {}
        self._emit(
            {
                "type": "attempt_result",
                "outcome": "success",
                "job_id": _job_id(_md(kwargs)),
                "call_id": kwargs.get("litellm_call_id"),
                "deployment_id": mi.get("id"),
                "model_returned": getattr(response_obj, "model", None),
                "latency_s": (end_time - start_time).total_seconds() if start_time and end_time else None,
            }
        )

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        mi = lp.get("model_info") or {}
        exc = kwargs.get("exception")
        name = type(exc).__name__ if exc else "UnknownError"
        status = getattr(exc, "status_code", None)
        if isinstance(exc, PolicyViolation) or "blocked before send" in str(exc):
            outcome, meaning = "blocked", "blocked by policy before send, nothing was sent"
        elif name == "Timeout" or status == 408:
            outcome, meaning = "timeout", "data sent, no response in time: the provider may have received the data"
        elif name == "APIConnectionError":
            outcome, meaning = "connection_failed", "connection failed: the provider most likely did not receive the data"
        elif not mi.get("id"):
            outcome, meaning = "no_deployment", "no approved deployment available"
        else:
            outcome, meaning = "error", "provider received the request and answered with an error"
        self._emit(
            {
                "type": "attempt_result",
                "outcome": outcome,
                "meaning": meaning,
                "job_id": _job_id(_md(kwargs)),
                "call_id": kwargs.get("litellm_call_id"),
                "deployment_id": mi.get("id"),
                "error_type": name,
                "status_code": status,
                "error": str(exc)[:300] if exc else None,
            }
        )


policy_hook = CommunePolicy()
