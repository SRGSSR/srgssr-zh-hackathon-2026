"""Phase 0 / tags: does LiteLLM v1.92.0 Router tag filtering hold across retries and fallbacks?

Run from lab dir:  ./run.sh tags/sdk_tag_fallbacks.py
Each scenario builds a fresh Router, resets all mocks, sends ONE request and prints mock request counts.
"""
import asyncio, json, sys, traceback
import litellm
from litellm import Router
from tags.mock_ext import start_mocks

PORTS = {"a-ch": 9201, "a-ch2": 9202, "a-us": 9203, "b-ch": 9204, "b-us": 9205, "b-untagged": 9206, "b-default-us": 9207, "evil": 9208}
M = start_mocks(PORTS)


def dep(group, name, tags=None, **extra):
    lp = {"model": f"openai/{name}-model", "api_base": f"http://127.0.0.1:{PORTS[name]}/v1", "api_key": "sk-mock"}
    if tags is not None:
        lp["tags"] = tags
    lp.update(extra)
    return {"model_name": group, "litellm_params": lp, "model_info": {"id": name}}


def counts():
    return {k: m.count for k, m in M.items() if m.count}


def reset(modes=None):
    for m in M.values():
        m.reset()
    for k, v in (modes or {}).items():
        M[k].mode = v


async def run(name, model_list, modes=None, req_kwargs=None, router_kwargs=None, model="A", n=1, sync=False):
    reset(modes)
    rk = dict(enable_tag_filtering=True, num_retries=0, retry_after=0, allowed_fails=100, cooldown_time=0)
    rk.update(router_kwargs or {})
    r = Router(model_list=model_list, **rk)
    outcomes = []
    for _ in range(n):
        kw = json.loads(json.dumps(req_kwargs or {}))  # fresh copy per request
        try:
            if sync:
                resp = r.completion(model=model, messages=[{"role": "user", "content": "hi"}], **kw)
            else:
                resp = await r.acompletion(model=model, messages=[{"role": "user", "content": "hi"}], **kw)
            outcomes.append(("OK", resp._hidden_params.get("model_id"), kw.get("metadata", {}).get("tags")))
        except Exception as e:
            outcomes.append(("ERR", type(e).__name__, str(e)[:230].replace("\n", " ")))
    print(f"\n### {name}\n  counts={counts()}")
    if n == 1:
        print(f"  outcome={outcomes[0]}")
    else:
        agg = {}
        for o in outcomes:
            key = o[0] + ":" + str(o[1])
            agg[key] = agg.get(key, 0) + 1
        print(f"  outcomes(n={n})={agg}")
        errs = [o for o in outcomes if o[0] == "ERR"]
        if errs:
            print(f"  first_error={errs[0]}")
    sys.stdout.flush()
    return r


CH = {"metadata": {"tags": ["ch"]}}
FB = {"fallbacks": [{"A": ["B"]}]}


async def main():
    print("litellm version:", litellm.version if hasattr(litellm, "version") else "?")
    try:
        from importlib.metadata import version
        print("litellm pkg version:", version("litellm"))
    except Exception as e:
        print("version err", e)

    # S1 baseline
    await run("S1 baseline: A=[a-ch(ch)] up, req tags=[ch]", [dep("A", "a-ch", ["ch"])], req_kwargs=CH)

    # S2 fallback to group with only us + untagged deployments
    ml2 = [dep("A", "a-ch", ["ch"]), dep("B", "b-us", ["us"]), dep("B", "b-untagged")]
    await run("S2 router fallback A->B, a-ch down, B=[b-us(us), b-untagged], req=[ch], num_retries=0",
              ml2, {"a-ch": "down"}, CH, FB)
    # S3 with retries
    await run("S3 same as S2 with num_retries=2", ml2, {"a-ch": "down"}, CH, {**FB, "num_retries": 2})
    # S4 fallback group has a ch deployment
    ml4 = [dep("A", "a-ch", ["ch"]), dep("B", "b-us", ["us"]), dep("B", "b-ch", ["ch"]), dep("B", "b-untagged")]
    await run("S4 router fallback A->B, B has b-ch(ch): n=10", ml4, {"a-ch": "down"}, CH, FB, n=10)
    # S5 default tag in fallback group
    ml5 = [dep("A", "a-ch", ["ch"]), dep("B", "b-default-us", ["default", "us"])]
    await run("S5 router fallback A->B, B=[b-default-us(default,us)], req=[ch]", ml5, {"a-ch": "down"}, CH, FB)
    # S6 untagged request
    ml6 = [dep("A", "a-ch", ["ch"]), dep("B", "b-us", ["us"])]
    await run("S6 untagged request, A down -> B=[b-us(us)]", ml6, {"a-ch": "down"}, {}, FB)
    # S6b untagged request, A has ch + us deployments, both up
    ml6b = [dep("A", "a-ch", ["ch"]), dep("A", "a-us", ["us"])]
    await run("S6b untagged request, A=[a-ch(ch), a-us(us)] both up, n=20", ml6b, {}, {}, {}, n=20)
    # S6c tagged request, A has ch + us deployments, both up (normal tag filtering)
    await run("S6c req=[ch], A=[a-ch(ch), a-us(us)] both up, n=20", ml6b, {}, CH, {}, n=20)

    # S7 tag pollution within retries (same group)
    ml7 = [dep("A", "a-ch", ["ch", "shared"]), dep("A", "a-us", ["us", "shared"])]
    await run("S7 POLLUTION retries: A=[a-ch(ch,shared) down, a-us(us,shared) up], req=[ch], num_retries=3",
              ml7, {"a-ch": "down"}, CH, {"num_retries": 3})
    # S7b control: no shared tag
    ml7b = [dep("A", "a-ch", ["ch"]), dep("A", "a-us", ["us"])]
    await run("S7b control: A=[a-ch(ch) down, a-us(us) up], req=[ch], num_retries=3",
              ml7b, {"a-ch": "down"}, CH, {"num_retries": 3})
    # S8 tag pollution across fallback
    ml8 = [dep("A", "a-ch", ["ch", "shared"]), dep("B", "b-us", ["us", "shared"])]
    await run("S8 POLLUTION fallback: A=[a-ch(ch,shared) down], B=[b-us(us,shared)], req=[ch]",
              ml8, {"a-ch": "down"}, CH, FB)
    # S8b control: fallback group with shared tag but primary does NOT carry it
    ml8b = [dep("A", "a-ch", ["ch"]), dep("B", "b-us", ["us", "shared"])]
    await run("S8b control: A=[a-ch(ch) down], B=[b-us(us,shared)], req=[ch]", ml8b, {"a-ch": "down"}, CH, FB)
    # S9 match_any=False
    await run("S9 like S8 but tag_filtering_match_any=False", ml8, {"a-ch": "down"}, CH, {**FB, "tag_filtering_match_any": False})
    # S9b match_any=False with a legit ch fallback deployment that lacks the 'shared' tag
    ml9b = [dep("A", "a-ch", ["ch", "shared"]), dep("B", "b-ch", ["ch"])]
    await run("S9b match_any=False: A=[a-ch(ch,shared) down], B=[b-ch(ch)], req=[ch]",
              ml9b, {"a-ch": "down"}, CH, {**FB, "tag_filtering_match_any": False})

    # S10 request-level fallbacks (string list)
    await run("S10 request-level fallbacks=['B'] (no router fallbacks), B=[b-us, b-untagged]",
              ml2, {"a-ch": "down"}, {**CH, "fallbacks": ["B"]})
    # S11 request-level fallbacks dict with metadata override
    await run("S11 request-level fallbacks=[{'model':'B','metadata':{'tags':['us']}}]",
              ml2, {"a-ch": "down"}, {**CH, "fallbacks": [{"model": "B", "metadata": {"tags": ["us"]}}]})
    # S11b request-level fallback dict with a deployment-id model (bypass)
    await run("S11b request-level fallbacks=[{'model':'b-us'}] (deployment id)",
              ml2, {"a-ch": "down"}, {**CH, "fallbacks": [{"model": "b-us"}]})
    # S11c request-level fallback dict with api_base override (SDK)
    await run("S11c request-level fallbacks=[{'model':'B','api_base':evil}]",
              [dep("A", "a-ch", ["ch"]), dep("B", "b-ch", ["ch"])], {"a-ch": "down"},
              {**CH, "fallbacks": [{"model": "B", "api_base": f"http://127.0.0.1:{PORTS['evil']}/v1"}]})

    # S12 context window fallbacks (real 400 from mock)
    await run("S12 context_window_fallbacks A->B, a-ch returns ctx error, B=[b-us, b-untagged]",
              ml2, {"a-ch": "ctx"}, CH, {"context_window_fallbacks": [{"A": ["B"]}]})
    await run("S12b context_window_fallbacks A->B, B has b-ch", ml4, {"a-ch": "ctx"}, CH,
              {"context_window_fallbacks": [{"A": ["B"]}]}, n=5)
    # S13 content policy fallbacks
    await run("S13 content_policy_fallbacks A->B, a-ch returns policy error, B=[b-us, b-untagged]",
              ml2, {"a-ch": "policy"}, CH, {"content_policy_fallbacks": [{"A": ["B"]}]})
    # S14 model = deployment id (specific deployment) bypasses tag filter
    await run("S14 model='b-us' (deployment id) with req=[ch]", ml2, {}, CH, {}, model="b-us")
    # S15 cooldown then default within same group
    ml15 = [dep("A", "a-ch", ["ch"]), dep("A", "b-default-us", ["default"])]
    await run("S15 A=[a-ch(ch) down, b-default-us(default)] req=[ch] num_retries=2 allowed_fails=0 cooldown 60",
              ml15, {"a-ch": "down"}, CH, {"num_retries": 2, "allowed_fails": 0, "cooldown_time": 60})
    # S16 sync completion path
    await run("S16 SYNC Router.completion req=[ch], A=[a-ch(ch), a-us(us)] both up, n=20", ml6b, {}, CH, {}, n=20, sync=True)
    # S17 routing strategies
    for strat in ["simple-shuffle", "latency-based-routing", "usage-based-routing", "usage-based-routing-v2", "least-busy", "cost-based-routing"]:
        await run(f"S17 routing_strategy={strat} req=[ch], A=[a-ch(ch), a-us(us)] both up, n=20", ml6b, {}, CH,
                  {"routing_strategy": strat}, n=20)
    # S18 enable_tag_filtering False (default) -> tags ignored
    await run("S18 enable_tag_filtering=False req=[ch], A=[a-ch, a-us], n=20", ml6b, {}, CH, {"enable_tag_filtering": False}, n=20)
    # S19 fallback group where every deployment is ch but in cooldown -> what error
    ml19 = [dep("A", "a-ch", ["ch"]), dep("B", "b-ch", ["ch"])]
    await run("S19 all ch down: A=[a-ch down], B=[b-ch down], req=[ch]", ml19, {"a-ch": "down", "b-ch": "down"}, CH, FB)
    # S20 negative tag
    await run("S20 req=[ch,'!ch'] A=[a-ch(ch), a-us(us)]", ml6b, {}, {"metadata": {"tags": ["ch", "!ch"]}}, {})
    await run("S20b req=['!us'] only (ban-only) A=[a-ch(ch), a-us(us)] n=10", ml6b, {}, {"metadata": {"tags": ["!us"]}}, {}, n=10)
    # S21 metadata tags None / litellm_metadata
    await run("S21 req litellm_metadata={'tags':['ch']} (SDK acompletion) A=[a-ch, a-us] n=20", ml6b, {},
              {"litellm_metadata": {"tags": ["ch"]}}, {}, n=20)
    # S22 tag_regex deployment matched by user_agent (client controlled)
    ml22 = [dep("A", "a-ch", ["ch"]), dep("A", "a-us", None, tag_regex=["^User-Agent: evil"])]
    await run("S22 req=[ch]+user_agent='evil' ; a-us has tag_regex ^User-Agent: evil ; n=20", ml22, {},
              {"metadata": {"tags": ["ch"], "user_agent": "evil/1.0"}}, {}, n=20)


asyncio.run(main())
