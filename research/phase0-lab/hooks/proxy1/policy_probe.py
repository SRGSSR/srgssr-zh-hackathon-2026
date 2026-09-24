"""Proxy-side instrumented policy callback (loaded via litellm_settings.callbacks).

Policy: if the *key* or *team* metadata (server-side, from auth) says routing_policy == "CH-only",
async_filter_deployments keeps only deployments whose model_info.jurisdiction == "CH".
MODE env var (read per call from /lab/hooks/proxy1/mode.txt) toggles extra behaviours for experiments:
  "plain"         -> filter only (no deployment-hook enforcement)
  "defense"       -> also enforce in async_pre_call_deployment_hook (api_base allowlist, id registry)
Every hook invocation is appended as a JSON line to events.jsonl (absolute timestamps).
"""
import json, os, time
from typing import Any, Dict, List, Optional

from litellm.integrations.custom_logger import CustomLogger

HERE = os.path.dirname(os.path.abspath(__file__))
EVF = os.path.join(HERE, "events.jsonl")
MODEF = os.path.join(HERE, "mode.txt")

# Approved registry, built from the *static* config at deploy time (not from router state).
APPROVED = {  # model_info.id -> expected api_base
    "a2": "http://127.0.0.1:9202/v1",
    "b1": "http://127.0.0.1:9203/v1",
}


def _mode():
    try:
        return open(MODEF).read().strip()
    except Exception:
        return "plain"


def ev(name, **d):
    with open(EVF, "a") as f:
        f.write(json.dumps({"t": time.time(), "ev": name, **d}, default=str) + "\n")


def _md(kwargs: Optional[dict]) -> dict:
    if not kwargs:
        return {}
    out = {}
    for k in ("litellm_metadata", "metadata"):
        v = kwargs.get(k)
        if isinstance(v, dict):
            out.update(v)
    return out


def policy_of(md: dict) -> Optional[str]:
    for src in ("user_api_key_metadata", "user_api_key_team_metadata"):
        v = md.get(src) or {}
        if isinstance(v, dict) and v.get("routing_policy"):
            return v["routing_policy"]
    auth = md.get("user_api_key_auth")
    if auth is not None:
        for attr in ("metadata", "team_metadata"):
            v = getattr(auth, attr, None) or {}
            if isinstance(v, dict) and v.get("routing_policy"):
                return v["routing_policy"]
    return None


def summ(md: dict) -> dict:
    return {k: md.get(k) for k in ("user_api_key_alias", "user_api_key_team_id", "user_api_key_metadata",
                                    "user_api_key_team_metadata", "model_group", "tags") if k in md} | \
           {"has_user_api_key_auth": "user_api_key_auth" in md, "n_keys": len(md)}


class PolicyProbe(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        md = _md(data)
        ev("async_pre_call_hook(proxy)", call_type=call_type, model=data.get("model"),
           key_alias=user_api_key_dict.key_alias, team_id=user_api_key_dict.team_id,
           key_md=user_api_key_dict.metadata, team_md=user_api_key_dict.team_metadata,
           body_fallbacks=data.get("fallbacks"), body_keys=sorted(k for k in data.keys() if k not in ("messages", "proxy_server_request", "secret_fields")),
           md=summ(md))
        return None

    async def async_pre_routing_hook(self, model, request_kwargs, messages=None, input=None, specific_deployment=False):
        ev("async_pre_routing_hook", model=model)
        return None

    async def async_filter_deployments(self, model, healthy_deployments, messages, request_kwargs=None, parent_otel_span=None):
        md = _md(request_kwargs)
        pol = policy_of(md)
        ids = [(d.get("model_info") or {}).get("id") for d in healthy_deployments]
        out = healthy_deployments
        if pol == "CH-only":
            out = [d for d in healthy_deployments if (d.get("model_info") or {}).get("jurisdiction") == "CH"]
            if _mode() in ("strict", "defense"):
                # registry-based: id must be in the static approved registry AND api_base must match it,
                # and the deployment must not be a router-created clientside-credential clone
                out = [d for d in out
                       if (d.get("model_info") or {}).get("id") in APPROVED
                       and APPROVED[(d.get("model_info") or {}).get("id")] == (d.get("litellm_params") or {}).get("api_base")
                       and not (d.get("model_info") or {}).get("original_model_id")]
        ev("async_filter_deployments", model=model, policy=pol, in_ids=ids,
           out_ids=[(d.get("model_info") or {}).get("id") for d in out],
           in_api_bases=[(d.get("litellm_params") or {}).get("api_base") for d in healthy_deployments], md=summ(md))
        return out

    async def async_pre_call_check(self, deployment, parent_otel_span=None):
        ev("async_pre_call_check", id=(deployment.get("model_info") or {}).get("id"))

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        md = _md(kwargs)
        pol = policy_of(md)
        mi = kwargs.get("model_info") or md.get("model_info") or {}
        api_base = kwargs.get("api_base")
        ev("async_pre_call_deployment_hook", call_type=str(call_type), policy=pol, model=kwargs.get("model"),
           api_base=api_base, model_info_id=mi.get("id"), original_model_id=mi.get("original_model_id"),
           jurisdiction=mi.get("jurisdiction"), md=summ(md), health=bool(md.get("tags") and "litellm-internal-health-check" in (md.get("tags") or [])))
        if _mode() in ("defense",) and pol == "CH-only":
            mid = mi.get("id")
            if mid not in APPROVED or APPROVED[mid] != api_base or mi.get("original_model_id"):
                ev("  deployment_hook.VETO", model_info_id=mid, api_base=api_base)
                raise Exception(f"CH-only policy: send to {api_base} (deployment {mid}) blocked before send")
        return None

    def log_pre_api_call(self, model, messages, kwargs):
        lp = kwargs.get("litellm_params") or {}
        ev("log_pre_api_call(sync)", model=model, api_base=str((kwargs.get("additional_args") or {}).get("api_base")),
           model_info_id=(lp.get("model_info") or {}).get("id"))

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        ev("async_log_success_event", model_info_id=(lp.get("model_info") or {}).get("id"), api_base=lp.get("api_base"))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        lp = kwargs.get("litellm_params") or {}
        exc = kwargs.get("exception")
        ev("async_log_failure_event", model_info_id=(lp.get("model_info") or {}).get("id"), exc=type(exc).__name__,
           status=getattr(exc, "status_code", None))

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        ev("log_success_fallback_event", original_model_group=original_model_group, now=kwargs.get("model"))

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        ev("log_failure_fallback_event", original_model_group=original_model_group, now=kwargs.get("model"))


proxy_handler_instance = PolicyProbe()
