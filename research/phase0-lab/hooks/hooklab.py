"""Instrumentation for Phase-0 hook research (LiteLLM v1.92.0).

- EVENTS: global ordered list of (t, event, details) shared by hooks and mocks
- start_evt_mocks(): same OpenAI mock as ../mock_openai.py, plus an event appended
  to EVENTS every time a mock *receives* a chat/embeddings/responses request (= "SEND").
- Probe(CustomLogger): implements every candidate hook, records the call, and can
  apply a policy (drop deployment ids / veto api_bases) controlled by globals.
"""
import asyncio
import threading
import time
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

import litellm
from litellm.integrations.custom_logger import CustomLogger

import mock_openai

EVENTS: List[tuple] = []
_T0 = time.time()


def ev(name: str, **details):
    EVENTS.append((round(time.time() - _T0, 3), name, details))


def reset_events():
    EVENTS.clear()


def dump(title: str = ""):
    if title:
        print(f"----- {title} -----")
    for t, name, d in EVENTS:
        print(f"{t:8.3f} {name:34s} {d}")


# ---------------------------------------------------------------- mocks
def _add_routes(m):
    app = m.app

    @app.post("/v1/embeddings")
    async def emb(req: Request):
        body = await req.json()
        m.count += 1
        m.requests.append({"body": body, "headers": dict(req.headers), "t": time.time()})
        if m.mode == "down":
            return JSONResponse({"error": {"message": "down"}}, status_code=503)
        return {"object": "list", "model": body.get("model"),
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1}}

    @app.post("/v1/responses")
    async def resp(req: Request):
        body = await req.json()
        m.count += 1
        m.requests.append({"body": body, "headers": dict(req.headers), "t": time.time()})
        if m.mode == "down":
            return JSONResponse({"error": {"message": "down"}}, status_code=503)
        return {"id": f"resp_{m.name}_{m.count}", "object": "response", "created_at": int(time.time()),
                "status": "completed", "model": body.get("model"),
                "output": [{"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
                            "content": [{"type": "output_text", "text": f"hello from {m.name}", "annotations": []}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}

    @app.middleware("http")
    async def record(request: Request, call_next):
        if request.method == "POST":
            ev("SEND->" + m.name, path=request.url.path, mode=m.mode,
               auth=(request.headers.get("authorization") or "")[:24])
        return await call_next(request)


def start_evt_mocks(spec: Dict[str, int]):
    mocks = {}
    for name, port in spec.items():
        m = mock_openai.Mock(name, port)
        _add_routes(m)
        server = uvicorn.Server(uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        mocks[name] = m
    time.sleep(1.5)
    return mocks


# ---------------------------------------------------------------- policy knobs
POLICY = {
    "drop_ids": set(),        # async_filter_deployments removes these model_info.id
    "veto_api_bases": set(),  # async_pre_call_deployment_hook raises if api_base in set
    "filter_raises": False,   # async_filter_deployments raises instead of filtering
    "veto_exc": "plain",      # exception class for deployment-hook veto: plain|badrequest|ratelimit
    "precheck_veto_ids": set(),  # async_pre_call_check raises for these ids
}


def _meta(kwargs: Optional[dict]) -> dict:
    if not kwargs:
        return {}
    return kwargs.get("metadata") or kwargs.get("litellm_metadata") or {}


def _summ_meta(md: dict) -> dict:
    keys = sorted(k for k in md.keys())
    out = {"keys_n": len(keys)}
    for k in ("user_api_key_alias", "user_api_key_team_id", "user_api_key_metadata",
              "user_api_key_team_metadata", "model_group", "tags", "deployment"):
        if k in md:
            out[k] = md[k]
    if "user_api_key_auth" in md:
        out["has_user_api_key_auth"] = True
    mi = md.get("model_info")
    if isinstance(mi, dict):
        out["model_info.id"] = mi.get("id")
    return out


class PolicyVeto(Exception):
    pass


class Probe(CustomLogger):
    # -- router-level
    async def async_pre_routing_hook(self, model, request_kwargs, messages=None, input=None, specific_deployment=False):
        ev("async_pre_routing_hook", model=model)
        return None

    async def async_filter_deployments(self, model, healthy_deployments, messages, request_kwargs=None, parent_otel_span=None):
        ids = [d.get("model_info", {}).get("id") for d in healthy_deployments]
        ev("async_filter_deployments", model=model, in_ids=ids,
           has_request_kwargs=request_kwargs is not None,
           meta=_summ_meta(_meta(request_kwargs)),
           mi_sample={k: v for k, v in (healthy_deployments[0].get("model_info") or {}).items() if k in ("id", "jurisdiction", "country", "provider")} if healthy_deployments else None)
        if POLICY["filter_raises"]:
            raise PolicyVeto(f"filter veto for {model}")
        out = [d for d in healthy_deployments if d.get("model_info", {}).get("id") not in POLICY["drop_ids"]]
        if len(out) != len(healthy_deployments):
            ev("  filter.dropped", ids=[i for i in ids if i in POLICY["drop_ids"]])
        return out

    async def async_pre_call_check(self, deployment, parent_otel_span=None):
        did = deployment.get("model_info", {}).get("id")
        ev("async_pre_call_check", id=did)
        if did in POLICY["precheck_veto_ids"]:
            raise PolicyVeto(f"pre_call_check veto {did}")
        return None

    def pre_call_check(self, deployment):
        ev("pre_call_check(sync)", id=deployment.get("model_info", {}).get("id"))
        return None

    # -- litellm.<fn> @client wrapper level (every attempt)
    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        api_base = kwargs.get("api_base")
        md = _meta(kwargs)
        ev("async_pre_call_deployment_hook", call_type=str(call_type), model=kwargs.get("model"), api_base=api_base,
           kw_model_info_id=(kwargs.get("model_info") or {}).get("id"), meta=_summ_meta(md))
        if api_base in POLICY["veto_api_bases"]:
            exc = POLICY["veto_exc"]
            if exc == "badrequest":
                raise litellm.BadRequestError(message=f"policy veto {api_base}", model=kwargs.get("model"), llm_provider="openai")
            if exc == "ratelimit":
                raise litellm.RateLimitError(message=f"policy veto {api_base}", model=kwargs.get("model"), llm_provider="openai")
            raise PolicyVeto(f"deployment hook veto {api_base}")
        return None

    async def async_pre_request_hook(self, model, messages, kwargs):
        ev("async_pre_request_hook", model=model)
        return None

    async def async_log_pre_api_call(self, model, messages, kwargs):
        ev("async_log_pre_api_call", model=model)

    def log_pre_api_call(self, model, messages, kwargs):
        lp = kwargs.get("litellm_params") or {}
        ev("log_pre_api_call(sync)", model=model, api_base=(kwargs.get("additional_args") or {}).get("api_base"),
           model_info_id=(lp.get("model_info") or {}).get("id"))

    # -- proxy-level
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        md = _meta(data)
        ev("async_pre_call_hook(proxy)", call_type=call_type, model=data.get("model"),
           key_alias=getattr(user_api_key_dict, "key_alias", None), team_id=getattr(user_api_key_dict, "team_id", None),
           key_metadata=getattr(user_api_key_dict, "metadata", None), team_metadata=getattr(user_api_key_dict, "team_metadata", None),
           body_fallbacks=data.get("fallbacks"), meta=_summ_meta(md))
        return None

    # -- outcomes
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        ev("async_log_success_event", model_info_id=(lp.get("model_info") or {}).get("id"),
           api_base=lp.get("api_base"))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        exc = kwargs.get("exception")
        ev("async_log_failure_event", model_info_id=(lp.get("model_info") or {}).get("id"),
           exc=type(exc).__name__, status=getattr(exc, "status_code", None))

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        ev("log_success_fallback_event", original_model_group=original_model_group, now_model=kwargs.get("model"))

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        ev("log_failure_fallback_event", original_model_group=original_model_group, now_model=kwargs.get("model"))


PROBE = Probe()


def dep(model_name, mid, port, jurisdiction="CH", **extra_lp):
    lp = {"model": "openai/x-" + mid, "api_base": f"http://127.0.0.1:{port}/v1", "api_key": f"sk-admin-{mid}"}
    lp.update(extra_lp)
    mi = {"id": mid}
    if jurisdiction is not None:
        mi["jurisdiction"] = jurisdiction
    return {"model_name": model_name, "litellm_params": lp, "model_info": mi}


async def cooldowns(router):
    from litellm.router_utils.cooldown_handlers import _async_get_cooldown_deployments
    return await _async_get_cooldown_deployments(litellm_router_instance=router, parent_otel_span=None)
