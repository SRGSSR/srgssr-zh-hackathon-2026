"""Probe + (optional) CH-only enforcement callback for the LiteLLM proxy experiments.

Registered via litellm_settings.callbacks: ["probe.probe_instance"].
Writes one JSON line per hook invocation to $PROBE_OUT (default /lab/proxy/out/probe.jsonl).

PROBE_ENFORCE=1 turns on the policy:
  policy source = request_kwargs["metadata"]["user_api_key_metadata"]["allowed_jurisdictions"]
  (written by the proxy from the authenticated UserAPIKeyAuth, see litellm_pre_call_utils.py)
  - async_filter_deployments: keep only deployments whose model_info.jurisdiction is allowed;
    missing metadata -> excluded (fail closed)
  - async_pre_call_deployment_hook: last check right before the HTTP send; raises if not allowed
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from litellm.integrations.custom_logger import CustomLogger

OUT = os.environ.get("PROBE_OUT", "/lab/proxy/out/probe.jsonl")
ENFORCE = os.environ.get("PROBE_ENFORCE", "0") == "1"
ADD_HEADERS = os.environ.get("PROBE_HEADERS", "1") == "1"

META_KEYS = (
    "tags", "user_api_key_metadata", "user_api_key_team_metadata", "user_api_key_team_id",
    "user_api_key_alias", "user_api_key_auth_metadata", "model_group", "deployment", "api_base",
    "model_info", "requester_metadata", "policy_id", "allowed_jurisdictions", "user_api_key_hash",
)
TOP_KEYS = (
    "model", "fallbacks", "num_retries", "disable_fallbacks", "api_key", "api_base", "base_url",
    "mock_response", "tags", "timeout", "model_info", "allowed_model_region", "litellm_call_id",
    "context_window_fallbacks", "max_retries",
)


def _w(rec: Dict[str, Any]):
    rec["t"] = time.time()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(rec, default=lambda o: repr(o)[:200]) + "\n")


def _meta(kwargs: Optional[dict]) -> dict:
    if not isinstance(kwargs, dict):
        return {}
    md = kwargs.get("metadata") or kwargs.get("litellm_metadata") or {}
    if not isinstance(md, dict):
        return {"_raw": repr(md)[:200]}
    return {k: md.get(k) for k in META_KEYS if k in md}


def _top(kwargs: Optional[dict]) -> dict:
    if not isinstance(kwargs, dict):
        return {}
    out = {k: kwargs.get(k) for k in TOP_KEYS if k in kwargs}
    if "api_key" in out and isinstance(out["api_key"], str):
        out["api_key"] = out["api_key"][:6] + "..."  # never log full keys
    return out


def _policy(kwargs: Optional[dict]) -> Optional[List[str]]:
    """Read the policy ONLY from the server-written user_api_key_metadata slot."""
    md = (kwargs or {}).get("metadata") or (kwargs or {}).get("litellm_metadata") or {}
    ukm = md.get("user_api_key_metadata") if isinstance(md, dict) else None
    if isinstance(ukm, dict):
        return ukm.get("allowed_jurisdictions")
    return None


def _jur(deployment: dict) -> Optional[str]:
    mi = deployment.get("model_info") or {}
    return mi.get("jurisdiction")


GUARD = os.environ.get("PROBE_GUARD", "0") == "1"
MAP_FAILURE = os.environ.get("PROBE_MAP_FAILURE", "0") == "1"

# request fields that let a caller widen/steer routing or amplify sends (see exp3_overrides.py)
GUARD_FORBIDDEN_TOP = (
    "api_key", "api_base", "base_url", "api_version", "organization", "fallbacks", "context_window_fallbacks",
    "content_policy_fallbacks", "router_settings_override", "num_retries", "max_retries", "timeout",
    "stream_timeout", "request_timeout", "specific_deployment", "user_config", "model_list",
    "mock_response", "mock_testing_fallbacks", "extra_body", "fastest_response", "tags",
)


def _guard(data: dict):
    from fastapi import HTTPException

    bad = [k for k in GUARD_FORBIDDEN_TOP if k in data]
    model = data.get("model")
    try:
        from litellm.proxy.proxy_server import llm_router
        names = set(llm_router.model_names) if llm_router else set()
    except Exception:
        names = set()
    if not isinstance(model, str) or "," in model or (names and model not in names):
        bad.append(f"model={model!r} (must be exactly one configured model group name)")
    if bad:
        raise HTTPException(status_code=400, detail={"error": f"policy: request fields not allowed: {bad}"})


class Probe(CustomLogger):
    # ---------------- proxy-level ----------------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        _w({"hook": "async_pre_call_hook", "call_type": str(call_type),
            "uak": {k: getattr(user_api_key_dict, k, None) for k in
                    ("key_alias", "team_id", "team_alias", "models", "metadata", "team_metadata", "api_key", "token")},
            "top": _top(data), "meta": _meta(data), "data_keys": sorted(data.keys())})
        if GUARD and (user_api_key_dict.metadata or {}).get("allowed_jurisdictions") is not None:
            _guard(data)
        return data

    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict,
                                           traceback_str=None):
        _w({"hook": "async_post_call_failure_hook", "exc": repr(original_exception)[:300]})
        if MAP_FAILURE and "No deployments available" in str(original_exception):
            from fastapi import HTTPException
            # turn LiteLLM's retryable 429 into an explicit "no approved endpoint" signal
            return HTTPException(status_code=503, detail={"error": "no_approved_endpoint",
                                                          "policy": (user_api_key_dict.metadata or {}).get(
                                                              "policy_id")})
        return None

    # ---------------- router-level ----------------
    async def async_pre_routing_hook(self, model, request_kwargs, messages=None, input=None, specific_deployment=False):
        _w({"hook": "async_pre_routing_hook", "model": model, "specific_deployment": specific_deployment,
            "top": _top(request_kwargs), "meta": _meta(request_kwargs)})
        return None

    async def async_filter_deployments(self, model, healthy_deployments, messages, request_kwargs=None,
                                       parent_otel_span=None):
        ids = [(d.get("model_info") or {}).get("id") for d in healthy_deployments]
        pol = _policy(request_kwargs)
        kept = healthy_deployments
        if ENFORCE and pol is not None:
            kept = [d for d in healthy_deployments if _jur(d) in pol]
        _w({"hook": "async_filter_deployments", "model": model, "in_ids": ids,
            "out_ids": [(d.get("model_info") or {}).get("id") for d in kept], "policy": pol,
            "enforce": ENFORCE, "top": _top(request_kwargs), "meta": _meta(request_kwargs)})
        return kept

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        md = kwargs.get("metadata") or kwargs.get("litellm_metadata") or {}
        mi = md.get("model_info") or kwargs.get("model_info") or {}
        pol = _policy(kwargs)
        decision = "allowed"
        if ENFORCE and pol is not None and mi.get("jurisdiction") not in pol:
            decision = "blocked_before_send"
        _w({"hook": "async_pre_call_deployment_hook", "call_type": str(call_type), "deployment_id": mi.get("id"),
            "jurisdiction": mi.get("jurisdiction"), "api_base": kwargs.get("api_base"), "model": kwargs.get("model"),
            "policy": pol, "decision": decision, "litellm_call_id": kwargs.get("litellm_call_id"),
            "top": _top(kwargs), "meta": _meta(kwargs), "kw_keys": sorted(kwargs.keys())})
        if decision != "allowed":
            raise Exception(f"policy CH-only: deployment {mi.get('id')} ({mi.get('jurisdiction')}) blocked before send")
        return None

    async def async_log_pre_api_call(self, model, messages, kwargs):
        lp = kwargs.get("litellm_params") or {}
        _w({"hook": "async_log_pre_api_call", "model": model, "api_base": lp.get("api_base"),
            "model_info_id": (lp.get("model_info") or {}).get("id"), "litellm_call_id": kwargs.get("litellm_call_id")})

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        slo = kwargs.get("standard_logging_object") or {}
        _w({"hook": "async_log_success_event", "model_id": slo.get("model_id"), "api_base": slo.get("api_base"),
            "model_group": slo.get("model_group"), "response_model": getattr(response_obj, "model", None),
            "litellm_call_id": kwargs.get("litellm_call_id"),
            "model_info_id": (lp.get("model_info") or {}).get("id")})

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        slo = kwargs.get("standard_logging_object") or {}
        exc = kwargs.get("exception")
        _w({"hook": "async_log_failure_event", "model_id": slo.get("model_id"), "api_base": slo.get("api_base"),
            "model_group": slo.get("model_group"), "exception": repr(exc)[:300],
            "litellm_call_id": kwargs.get("litellm_call_id"),
            "model_info_id": (lp.get("model_info") or {}).get("id")})

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        _w({"hook": "log_success_fallback_event", "original_model_group": original_model_group,
            "exc": repr(original_exception)[:200]})

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        _w({"hook": "log_failure_fallback_event", "original_model_group": original_model_group,
            "exc": repr(original_exception)[:200]})

    # ---------------- response headers ----------------
    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response,
                                                    request_headers=None, litellm_call_info=None):
        _w({"hook": "async_post_call_response_headers_hook", "response_is_none": response is None,
            "litellm_call_info": litellm_call_info, "meta_model_info": (_meta(data).get("model_info") or {}).get("id")})
        if not ADD_HEADERS:
            return None
        mi = (litellm_call_info or {}).get("model_info") or {}
        return {
            "x-commune-policy": str((user_api_key_dict.metadata or {}).get("policy_id")),
            "x-commune-final-deployment": str(mi.get("id")),
            "x-commune-final-jurisdiction": str(mi.get("jurisdiction")),
        }


probe_instance = Probe()
