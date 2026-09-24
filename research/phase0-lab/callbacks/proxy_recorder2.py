"""Second-round proxy callbacks.

probe            : TimelineProbe -- defines its hooks on the LEAF class; stamps a server-side correlation id
                   (metadata.tl_request_id) in async_pre_call_hook; optionally blocks non-CH deployments in
                   async_pre_call_check (env BLOCK=1); optionally strips client "no-log" (env STRIP_NO_LOG=1);
                   records active router cooldowns in the post-call hooks.
inherit_only     : InheritOnly -- subclass that defines NOTHING itself (all hooks inherited from Recorder),
                   to test the proxy's leaf-class __dict__ capability detection.
"""
import os, sys, uuid

sys.path.insert(0, "/lab/callbacks")
from recorder import Recorder, _exc_chain, _safe  # noqa: E402


class PolicyBlocked(Exception):
    """Raised by our policy before any byte is sent."""


async def _cooldowns():
    from litellm.proxy.proxy_server import llm_router
    cds = await llm_router.cooldown_cache.async_get_active_cooldowns(model_ids=llm_router.get_model_ids(), parent_otel_span=None)
    return [c[0] for c in (cds or [])]


class TimelineProbe(Recorder):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        client_no_log = data.get("no-log")
        if os.environ.get("STRIP_NO_LOG") == "1":
            data.pop("no-log", None)
        md = data.setdefault("metadata", {})
        client_supplied = md.get("tl_request_id")
        md["tl_request_id"] = "tl-" + uuid.uuid4().hex[:10]  # server-side, overwrites anything the client sent
        self._rec("async_pre_call_hook", litellm_call_id=data.get("litellm_call_id"), tl_request_id=md["tl_request_id"],
                  client_supplied_tl_request_id=client_supplied, client_no_log=client_no_log,
                  model=data.get("model"))
        return data

    async def async_pre_call_check(self, deployment, parent_otel_span):
        mi = deployment.get("model_info", {})
        self._rec("async_pre_call_check", deployment_id=mi.get("id"), jurisdiction=mi.get("jurisdiction"))
        if os.environ.get("BLOCK") == "1" and mi.get("jurisdiction") != "CH":
            self._rec("POLICY_BLOCK", deployment_id=mi.get("id"))
            raise PolicyBlocked(f"blocked before send: deployment {mi.get('id')} jurisdiction={mi.get('jurisdiction')}")
        return None

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        md = data.get("metadata") or {}
        hp = getattr(response, "_hidden_params", {}) or {}
        self._rec("async_post_call_success_hook", tl_request_id=md.get("tl_request_id"), md_model_info_id=(md.get("model_info") or {}).get("id"),
                  hidden_model_id=hp.get("model_id"), resp_model=getattr(response, "model", None), cooldowns=await _cooldowns())
        return response

    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict, traceback_str=None):
        md = request_data.get("metadata") or {}
        self._rec("async_post_call_failure_hook", tl_request_id=md.get("tl_request_id"), md_model_info_id=(md.get("model_info") or {}).get("id"),
                  exc=_exc_chain(original_exception), status_code=getattr(original_exception, "status_code", None),
                  cooldowns=await _cooldowns())
        return None

    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response, request_headers=None, litellm_call_info=None):
        md = data.get("metadata") or {}
        self._rec("async_post_call_response_headers_hook", tl_request_id=md.get("tl_request_id"),
                  litellm_call_info=_safe(litellm_call_info), has_response=response is not None)
        return {"x-tl-request-id": str(md.get("tl_request_id"))}

    async def log_success_fallback_event(self, original_model_group, kwargs, original_exception):
        await super().log_success_fallback_event(original_model_group, kwargs, original_exception)
        self.events[-1]["tl_request_id"] = (kwargs.get("metadata") or {}).get("tl_request_id")

    async def log_failure_fallback_event(self, original_model_group, kwargs, original_exception):
        await super().log_failure_fallback_event(original_model_group, kwargs, original_exception)
        self._rec("log_failure_fallback_event(tl)", tl_request_id=(kwargs.get("metadata") or {}).get("tl_request_id"))


class InheritOnly(Recorder):
    pass


probe = TimelineProbe(tag="probe")
inherit_only = InheritOnly(tag="inherit_only")
