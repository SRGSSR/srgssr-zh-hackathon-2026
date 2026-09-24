"""Recording CustomLogger: implements every hook that could matter for a per-attempt timeline and
records a compact, copied snapshot of the identifying fields at the moment each hook fires.

Used by exp_router.py (SDK Router) and, via proxy_recorder.py, by exp_proxy.py (proxy).
Events go to self.events (in-memory) and, if EVENTS_FILE is set, are appended as JSONL.
"""
import json, os, time, copy
from typing import Any, Optional

from litellm.integrations.custom_logger import CustomLogger

EVENTS_FILE = os.environ.get("EVENTS_FILE")


def _exc_chain(e):
    out, seen = [], set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        out.append(type(e).__module__ + "." + type(e).__name__)
        e = e.__cause__ or e.__context__
    return out


def _safe(v, depth=0):
    try:
        json.dumps(v)
        return v
    except Exception:
        if isinstance(v, dict) and depth < 3:
            return {str(k): _safe(x, depth + 1) for k, x in v.items()}
        if isinstance(v, (list, tuple)) and depth < 3:
            return [_safe(x, depth + 1) for x in v]
        return repr(v)[:200]


def snapshot_kwargs(kwargs: dict) -> dict:
    """Pull the fields that identify the deployment/attempt out of model_call_details (kwargs)."""
    if not isinstance(kwargs, dict):
        return {"kwargs_type": str(type(kwargs))}
    lp = kwargs.get("litellm_params") or {}
    md = lp.get("metadata") or kwargs.get("metadata") or {}
    slo = kwargs.get("standard_logging_object") or None
    exc = kwargs.get("exception")
    add = kwargs.get("additional_args") or {}
    snap = {
        "mcd_obj_id": id(kwargs),  # identity of model_call_details dict (same => shared logging obj)
        "litellm_call_id": kwargs.get("litellm_call_id"),
        "lp.litellm_trace_id": lp.get("litellm_trace_id"),
        "kwargs.model": kwargs.get("model"),
        "custom_llm_provider": kwargs.get("custom_llm_provider") or lp.get("custom_llm_provider"),
        "lp.api_base": lp.get("api_base"),
        "lp.model_info": copy.deepcopy(lp.get("model_info")),
        "additional_args.api_base": add.get("api_base") if isinstance(add, dict) else None,
        "md.model_group": md.get("model_group"),
        "md.deployment": md.get("deployment"),
        "md.api_base": md.get("api_base"),
        "md.model_info.id": (md.get("model_info") or {}).get("id") if isinstance(md.get("model_info"), dict) else None,
        "md.model_info.jurisdiction": (md.get("model_info") or {}).get("jurisdiction") if isinstance(md.get("model_info"), dict) else None,
        "md.attempted_retries": md.get("attempted_retries"),
        "md.max_retries": md.get("max_retries"),
        "md.previous_models_len": len(md.get("previous_models") or []),
        "md.user_api_key_team_id": md.get("user_api_key_team_id"),
        "md.tl_request_id": md.get("tl_request_id"),
        "md.user_api_key_hash_prefix": (md.get("user_api_key_hash") or "")[:8] or None,
        "has_logged": {k: v for k, v in kwargs.items() if str(k).startswith("has_logged_")},
        "log_event_type": kwargs.get("log_event_type"),
        "api_call_start_time": str(kwargs.get("api_call_start_time")) if kwargs.get("api_call_start_time") else None,
    }
    if exc is not None:
        snap["exception"] = {
            "chain": _exc_chain(exc),
            "status_code": getattr(exc, "status_code", None),
            "msg": str(exc)[:160],
        }
    if slo:
        snap["slo"] = {
            k: _safe(slo.get(k))
            for k in ["id", "trace_id", "litellm_call_id", "status", "model", "model_id", "model_group",
                      "api_base", "custom_llm_provider", "error_str", "startTime", "endTime", "response_time"]
        }
        hp = slo.get("hidden_params") or {}
        snap["slo"]["hidden_params"] = {k: _safe(hp.get(k)) for k in ["model_id", "api_base", "litellm_model_name"]}
        ei = slo.get("error_information") or {}
        snap["slo"]["error_information"] = {k: _safe(ei.get(k)) for k in ["error_code", "error_class", "llm_provider", "error_message"]}
        smd = slo.get("metadata") or {}
        snap["slo"]["metadata.user_api_key_team_id"] = smd.get("user_api_key_team_id")
    return snap


def snapshot_response(resp) -> Optional[dict]:
    if resp is None:
        return None
    hp = getattr(resp, "_hidden_params", None) or {}
    return {
        "type": type(resp).__name__,
        "resp.model": getattr(resp, "model", None),
        "resp.id": getattr(resp, "id", None),
        "hidden.model_id": hp.get("model_id"),
        "hidden.api_base": hp.get("api_base"),
        "hidden.litellm_model_name": hp.get("litellm_model_name"),
        "hidden.additional_headers.keys": sorted((hp.get("additional_headers") or {}).keys())[:12],
    }


class Recorder(CustomLogger):
    def __init__(self, tag="rec"):
        super().__init__()
        self.tag = tag
        self.events = []
        self.t0 = time.time()

    def reset(self):
        self.events = []
        self.t0 = time.time()

    def _rec(self, hook, **data):
        ev = {"t": round(time.time() - self.t0, 3), "wall": round(time.time(), 3), "tag": self.tag, "hook": hook, **data}
        self.events.append(ev)
        if EVENTS_FILE:
            with open(EVENTS_FILE, "a") as f:
                f.write(json.dumps(_safe(ev), default=str) + "\n")

    # ---------------- per-attempt logging hooks ----------------
    def log_pre_api_call(self, model, messages, kwargs):
        self._rec("log_pre_api_call", model=model, **snapshot_kwargs(kwargs))

    async def async_log_pre_api_call(self, model, messages, kwargs):
        self._rec("async_log_pre_api_call", model=model, **snapshot_kwargs(kwargs))

    def log_post_api_call(self, kwargs, response_obj, start_time, end_time):
        self._rec("log_post_api_call", **snapshot_kwargs(kwargs))

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._rec("log_success_event", resp=snapshot_response(response_obj), **snapshot_kwargs(kwargs))

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._rec("log_failure_event", **snapshot_kwargs(kwargs))

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._rec("async_log_success_event", resp=snapshot_response(response_obj), **snapshot_kwargs(kwargs))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._rec("async_log_failure_event", **snapshot_kwargs(kwargs))

    # ---------------- router hooks ----------------
    async def async_pre_routing_hook(self, model, request_kwargs, messages=None, input=None, specific_deployment=False):
        self._rec("async_pre_routing_hook", model=model)
        return None

    async def async_filter_deployments(self, model, healthy_deployments, messages, request_kwargs=None, parent_otel_span=None):
        ids = [d.get("model_info", {}).get("id") for d in healthy_deployments] if isinstance(healthy_deployments, list) else "dict"
        self._rec("async_filter_deployments", model=model, healthy_ids=ids)
        return healthy_deployments

    async def async_pre_call_check(self, deployment, parent_otel_span):
        mi = deployment.get("model_info", {})
        self._rec("async_pre_call_check", deployment_id=mi.get("id"), jurisdiction=mi.get("jurisdiction"),
                  api_base=deployment.get("litellm_params", {}).get("api_base"))
        return None

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        mi = kwargs.get("model_info") or {}
        self._rec("async_pre_call_deployment_hook", call_type=str(call_type), deployment_id=mi.get("id"),
                  litellm_call_id=kwargs.get("litellm_call_id"), api_base=kwargs.get("api_base"))
        return None

    async def async_post_call_success_deployment_hook(self, request_data, response, call_type):
        mi = request_data.get("model_info") or {}
        self._rec("async_post_call_success_deployment_hook", deployment_id=mi.get("id"), resp=snapshot_response(response))
        return None

    async def log_model_group_rate_limit_error(self, exception, original_model_group, kwargs):
        self._rec("log_model_group_rate_limit_error", original_model_group=original_model_group, exc=_exc_chain(exception))

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        md = kwargs.get("metadata") or {}
        self._rec("log_success_fallback_event", original_model_group=original_model_group,
                  fallback_model=kwargs.get("model"), md_model_group=md.get("model_group"),
                  md_model_info_id=(md.get("model_info") or {}).get("id"),
                  original_exception=_exc_chain(original_exception), fallback_depth=kwargs.get("fallback_depth"),
                  litellm_trace_id=kwargs.get("litellm_trace_id"), litellm_call_id=kwargs.get("litellm_call_id"))

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        md = kwargs.get("metadata") or {}
        self._rec("log_failure_fallback_event", original_model_group=original_model_group,
                  fallback_model=kwargs.get("model"), md_model_group=md.get("model_group"),
                  md_model_info_id=(md.get("model_info") or {}).get("id"),
                  original_exception=_exc_chain(original_exception), fallback_depth=kwargs.get("fallback_depth"),
                  litellm_trace_id=kwargs.get("litellm_trace_id"), litellm_call_id=kwargs.get("litellm_call_id"))

    # ---------------- proxy-only hooks ----------------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        self._rec("async_pre_call_hook", call_type=str(call_type), team_id=getattr(user_api_key_dict, "team_id", None),
                  litellm_call_id=data.get("litellm_call_id"), model=data.get("model"))
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        self._rec("async_post_call_success_hook", litellm_call_id=data.get("litellm_call_id"),
                  md_model_info_id=((data.get("metadata") or {}).get("model_info") or {}).get("id"),
                  resp=snapshot_response(response))
        return response

    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict, traceback_str=None):
        md = request_data.get("metadata") or {}
        self._rec("async_post_call_failure_hook", litellm_call_id=request_data.get("litellm_call_id"),
                  md_model_info_id=(md.get("model_info") or {}).get("id"), md_model_group=md.get("model_group"),
                  md_previous_models=[(pm.get("model_info") or {}).get("id") if isinstance(pm, dict) else None
                                      for pm in (md.get("previous_models") or [])],
                  exc=_exc_chain(original_exception), status_code=getattr(original_exception, "status_code", None))
        return None

    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response, request_headers=None, litellm_call_info=None):
        self._rec("async_post_call_response_headers_hook", litellm_call_info=_safe(litellm_call_info),
                  has_response=response is not None)
        return None
