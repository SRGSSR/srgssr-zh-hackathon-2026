"""Which router/CustomLogger hooks see the paths that bypass tag filtering? (v1.92.0, SDK, mocks only)
./run.sh tags/hook_visibility.py

Hooks recorded per attempt:
  F = CustomLogger.async_filter_deployments   (router.async_callback_filter_deployments, before tag filter)
  C = CustomLogger.async_pre_call_check        (router.async_routing_strategy_pre_call_checks, right before await)
  D = CustomLogger.async_pre_call_deployment_hook (litellm.utils wrapper_async, final kwargs incl. api_base)
Enforcement in D: raise if kwargs['api_base'] not in the approved set -> check the mock counter stays 0.
"""
import asyncio, logging
import litellm
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger
from tags.mock_ext import start_mocks

logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
PORTS = {"a-ch": 9801, "b-ch": 9802, "b-us": 9803, "other-host": 9809}
M = start_mocks(PORTS)
APPROVED = {f"http://127.0.0.1:{PORTS['a-ch']}/v1", f"http://127.0.0.1:{PORTS['b-ch']}/v1"}


class Probe(CustomLogger):
    def __init__(self, enforce):
        super().__init__()
        self.enforce, self.log = enforce, []

    async def async_filter_deployments(self, model, healthy_deployments, messages, request_kwargs=None, parent_otel_span=None):
        self.log.append(("F", model, [d["model_info"]["id"] for d in healthy_deployments]))
        return healthy_deployments

    async def async_pre_call_check(self, deployment, parent_otel_span):
        self.log.append(("C", deployment["model_info"]["id"], deployment["litellm_params"].get("api_base")))

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        ab = kwargs.get("api_base")
        self.log.append(("D", (kwargs.get("model_info") or {}).get("id"), ab, (kwargs.get("metadata") or {}).get("tags")))
        if self.enforce and ab not in APPROVED:
            raise litellm.BadRequestError(message=f"policy: blocked before send api_base={ab}", model=kwargs.get("model"), llm_provider="policy")
        return None


def d(group, name, tags):
    return {"model_name": group, "litellm_params": {"model": f"openai/{name}", "api_base": f"http://127.0.0.1:{PORTS[name]}/v1",
                                                   "api_key": "sk-mock", "tags": tags}, "model_info": {"id": name}}


async def scenario(label, enforce, model, kw, modes):
    for k, m in M.items():
        m.reset(); m.mode = modes.get(k, "up")
    p = Probe(enforce)
    litellm.callbacks = [p]
    r = Router(model_list=[d("A", "a-ch", ["ch"]), d("B", "b-ch", ["ch"]), d("B", "b-us", ["us"])],
               enable_tag_filtering=True, num_retries=0, retry_after=0, allowed_fails=100, cooldown_time=0)
    try:
        resp = await r.acompletion(model=model, messages=[{"role": "user", "content": "x"}], metadata={"tags": ["ch"]}, **kw)
        out = f"OK served_by={resp._hidden_params.get('model_id')}"
    except Exception as e:
        out = f"ERR {type(e).__name__}: {str(e)[:110]}"
    print(f"\n### {label} (enforce_in_D={enforce})\n  {out}\n  counts={ {k: m.count for k, m in M.items() if m.count} }")
    for entry in p.log:
        print("   ", entry)


async def main():
    for enforce in (False, True):
        await scenario("H1 model='b-us' (deployment id)", enforce, "b-us", {}, {})
        await scenario("H2 A down, request fallbacks=[{'model':'B','api_base':other-host}]", enforce, "A",
                       {"fallbacks": [{"model": "B", "api_base": f"http://127.0.0.1:{PORTS['other-host']}/v1"}]}, {"a-ch": "down"})
        await scenario("H3 A down, request fallbacks=[{'model':'B','metadata':{'tags':['us']}}]", enforce, "A",
                       {"fallbacks": [{"model": "B", "metadata": {"tags": ["us"]}}]}, {"a-ch": "down"})


asyncio.run(main())
