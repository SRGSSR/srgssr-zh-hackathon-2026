"""Probe CustomLogger: records, per attempt, exactly which fields a callback can read to identify the
deployment (id, api_base, provider, model_info incl. custom keys). Written as JSON lines to $PROBE_OUT.
Used by /lab/utility/exp_utility_proxy.py. Never raises (like custom_lago_callback)."""
import json, os, time
from litellm.integrations.custom_logger import CustomLogger

OUT = os.environ.get("PROBE_OUT", "/tmp/probe.jsonl")


def _lp(kwargs):
    return kwargs.get("litellm_params") or {}


def _summ(kwargs):
    lp = _lp(kwargs)
    mi = lp.get("model_info") or {}
    slo = kwargs.get("standard_logging_object") or {}
    meta = lp.get("metadata") or {}
    return {
        "kwargs.model": kwargs.get("model"),
        "kwargs.custom_llm_provider": kwargs.get("custom_llm_provider") or lp.get("custom_llm_provider"),
        "litellm_params.api_base": lp.get("api_base"),
        "litellm_params.model_info": {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None), list, dict)) else v) for k, v in dict(mi).items()},
        "metadata.model_group": meta.get("model_group"),
        "metadata.deployment": meta.get("deployment"),
        "metadata.user_api_key_team_id": meta.get("user_api_key_team_id"),
        "metadata.tags": meta.get("tags"),
        "slo.model_id": slo.get("model_id"),
        "slo.api_base": slo.get("api_base"),
        "slo.model_group": slo.get("model_group"),
        "slo.model": slo.get("model"),
        "slo.custom_llm_provider": slo.get("custom_llm_provider"),
        "slo.status": slo.get("status"),
        "slo.error_str": (slo.get("error_str") or "")[:120] or None,
        "slo.response_cost": slo.get("response_cost"),
        "slo.hidden_params.api_base": (slo.get("hidden_params") or {}).get("api_base"),
        "slo.hidden_params.model_id": (slo.get("hidden_params") or {}).get("model_id"),
    }


def _w(rec):
    try:
        rec["t"] = time.time()
        with open(OUT, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:  # never break the request
        print("probe write error", e)


class Probe(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        _w({"hook": "log_pre_api_call", "model_arg": model, **_summ(kwargs)})

    async def async_log_pre_api_call(self, model, messages, kwargs):
        _w({"hook": "async_log_pre_api_call", "model_arg": model, **_summ(kwargs)})

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        hp = getattr(response_obj, "_hidden_params", {}) or {}
        _w({"hook": "async_log_success_event", "response.model": getattr(response_obj, "model", None),
            "response._hidden_params.model_id": hp.get("model_id"),
            "response._hidden_params.api_base": hp.get("api_base"), **_summ(kwargs)})

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        exc = kwargs.get("exception")
        _w({"hook": "async_log_failure_event", "exception": type(exc).__name__ if exc else None, **_summ(kwargs)})

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        _w({"hook": "log_success_fallback_event", "original_model_group": original_model_group,
            "original_exception": type(original_exception).__name__, "kwargs.model": kwargs.get("model")})

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        _w({"hook": "log_failure_fallback_event", "original_model_group": original_model_group,
            "original_exception": type(original_exception).__name__, "kwargs.model": kwargs.get("model")})


probe = Probe()
