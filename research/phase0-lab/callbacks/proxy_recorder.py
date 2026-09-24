"""Callback module loaded by the LiteLLM proxy (litellm_settings.callbacks: ["proxy_recorder.proxy_handler_instance"]).
Writes every hook invocation as JSONL to $EVENTS_FILE (see recorder.py)."""
import sys, json, os

sys.path.insert(0, "/lab/callbacks")
from recorder import Recorder, _safe  # noqa: E402


class ProxyRecorder(Recorder):
    _dumped = False

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if not ProxyRecorder._dumped:
            ProxyRecorder._dumped = True
            import litellm
            from litellm.proxy.proxy_server import llm_router
            r = llm_router
            self._rec("EFFECTIVE_SETTINGS", router={
                "num_retries": r.num_retries, "retry_after": r.retry_after, "allowed_fails": r.allowed_fails,
                "cooldown_time": r.cooldown_time, "timeout": r.timeout, "routing_strategy": r.routing_strategy,
                "disable_cooldowns": r.disable_cooldowns, "allowed_fails_policy": str(r.allowed_fails_policy),
                "fallbacks": r.fallbacks, "default_max_retries": r.default_litellm_params.get("max_retries")},
                litellm_module={"num_retries": litellm.num_retries, "allowed_fails": litellm.allowed_fails,
                                "cooldown_time(attr set by litellm_settings)": getattr(litellm, "cooldown_time", "<unset>"),
                                "request_timeout": litellm.request_timeout},
                model_info_in_router={d["model_info"]["id"]: {k: v for k, v in d["model_info"].items() if k in ("jurisdiction", "provider", "country")}
                                      for d in r.model_list})
        md = data.get("metadata") or {}
        self._rec("async_pre_call_hook", call_type=str(call_type), team_id=getattr(user_api_key_dict, "team_id", None),
                  litellm_call_id=data.get("litellm_call_id"), model=data.get("model"),
                  body_keys=sorted(k for k in data.keys() if k not in ("messages", "proxy_server_request", "secret_fields")),
                  no_log=data.get("no-log"), md_keys=sorted(md.keys())[:40],
                  litellm_trace_id=data.get("litellm_trace_id"), logging_obj_id=id(data.get("litellm_logging_obj")))
        return data


proxy_handler_instance = ProxyRecorder(tag="proxy")
