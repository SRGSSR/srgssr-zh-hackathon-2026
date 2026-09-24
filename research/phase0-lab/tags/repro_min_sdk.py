"""Minimal SDK repros (LiteLLM v1.92.0) for tag-routing gaps. Mocks only.  ./run.sh tags/repro_min_sdk.py

R1 tag pollution: Router._update_kwargs_with_deployment merges the tried deployment's tags into the SHARED
   request metadata dict, so the next retry/fallback is filtered with widened tags (match_any=True default).
R2 sync Router.completion never applies tag filtering.
R3 routing_strategy='usage-based-routing' (v1) async path delegates to sync get_available_deployment -> no tag filtering.
R4 docs: model_info.enable_tag_filtering (per group) is not honored in v1.92.0.
R5 cooldown happens BEFORE tag filtering: once the only matching deployment is cooled down, the tag filter
   raises 'Not allowed to access model due to tags configuration' (misleading) instead of a no-deployments error.
R6 untagged request: first attempt pollutes tags, fallback is then filtered by the primary deployment's tags.
"""
import asyncio, logging
import litellm
from litellm import Router
from tags.mock_ext import start_mocks

logging.getLogger("LiteLLM Router").setLevel(logging.CRITICAL)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
PORTS = {"ch": 9601, "us": 9602}
M = start_mocks(PORTS)
MSG = [{"role": "user", "content": "citizen data"}]


def d(group, name, tags=None, model_info=None):
    lp = {"model": f"openai/{name}", "api_base": f"http://127.0.0.1:{PORTS[name]}/v1", "api_key": "sk-mock"}
    if tags is not None:
        lp["tags"] = tags
    return {"model_name": group, "litellm_params": lp, "model_info": {"id": name, **(model_info or {})}}


def reset(**modes):
    for k, m in M.items():
        m.reset()
        m.mode = modes.get(k, "up")


def show(label, extra=""):
    print(f"{label}: counts={{'ch': {M['ch'].count}, 'us': {M['us'].count}}} {extra}", flush=True)


async def main():
    base = dict(enable_tag_filtering=True, retry_after=0, allowed_fails=100, cooldown_time=0)

    # R1a pollution across router fallback
    reset(ch="down")
    r = Router(model_list=[d("A", "ch", ["ch", "shared"]), d("B", "us", ["us", "shared"])], fallbacks=[{"A": ["B"]}], num_retries=0, **base)
    md = {"tags": ["ch"]}
    resp = await r.acompletion(model="A", messages=MSG, metadata=md)
    show("R1a fallback A(ch,shared; down)->B(us,shared), req tags=[ch]", f"served_by={resp._hidden_params.get('model_id')} request_tags_after={md['tags']}")
    # R1b pollution inside retries of one group
    reset(ch="down")
    r = Router(model_list=[d("A", "ch", ["ch", "shared"]), d("A", "us", ["us", "shared"])], num_retries=3, **base)
    md = {"tags": ["ch"]}
    resp = await r.acompletion(model="A", messages=MSG, metadata=md)
    show("R1b retries in A=[ch(ch,shared; down), us(us,shared)], req tags=[ch]", f"served_by={resp._hidden_params.get('model_id')} request_tags_after={md['tags']}")

    # R2 sync completion ignores tags
    reset()
    r = Router(model_list=[d("A", "ch", ["ch"]), d("A", "us", ["us"])], num_retries=0, **base)
    for _ in range(20):
        r.completion(model="A", messages=MSG, metadata={"tags": ["ch"]})
    show("R2 SYNC Router.completion x20, req tags=[ch]")
    reset()
    for _ in range(20):
        await r.acompletion(model="A", messages=MSG, metadata={"tags": ["ch"]})
    show("R2 control ASYNC Router.acompletion x20, req tags=[ch]")

    # R3 usage-based-routing v1
    reset()
    r = Router(model_list=[d("A", "ch", ["ch"]), d("A", "us", ["us"])], num_retries=0, routing_strategy="usage-based-routing", **base)
    for _ in range(20):
        await r.acompletion(model="A", messages=MSG, metadata={"tags": ["ch"]})
    show("R3 routing_strategy=usage-based-routing, acompletion x20, req tags=[ch]")

    # R4 per-group model_info.enable_tag_filtering (documented upstream) not honored at v1.92.0
    reset()
    r = Router(model_list=[d("A", "ch", ["ch"], {"enable_tag_filtering": True}), d("A", "us", ["us"], {"enable_tag_filtering": True})],
               num_retries=0, enable_tag_filtering=False, retry_after=0)
    for _ in range(20):
        await r.acompletion(model="A", messages=MSG, metadata={"tags": ["ch"]})
    show("R4 router enable_tag_filtering=False + model_info.enable_tag_filtering=True, x20, req tags=[ch]")

    # R5 cooldown before tag filter
    reset(ch="down")
    r = Router(model_list=[d("A", "ch", ["ch"]), d("A", "us", ["us"])], num_retries=0, enable_tag_filtering=True,
               retry_after=0, allowed_fails=0, cooldown_time=60)
    for i in range(2):
        try:
            await r.acompletion(model="A", messages=MSG, metadata={"tags": ["ch"]})
        except Exception as e:
            print(f"  R5 request {i+1}: {type(e).__name__}: {str(e)[:160]}")
    show("R5 A=[ch(down), us], allowed_fails=0 cooldown 60s, 2 requests tagged [ch]")

    # R6 untagged request + fallback
    reset(ch="down")
    r = Router(model_list=[d("A", "ch", ["ch"]), d("B", "us", ["us"])], fallbacks=[{"A": ["B"]}], num_retries=0, **base)
    md = {}
    try:
        await r.acompletion(model="A", messages=MSG, metadata=md)
    except Exception as e:
        i = str(e).find("Error doing the fallback")
        print(f"  R6 error: {type(e).__name__}: ...{str(e)[i:i+140]}")
    show("R6 UNTAGGED request, A=[ch(ch) down] -> B=[us(us)]", f"request_tags_after={md.get('tags')}")


asyncio.run(main())
