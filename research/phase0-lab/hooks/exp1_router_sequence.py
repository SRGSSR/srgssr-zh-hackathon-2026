"""EXP1: exact sequence of hook calls vs. sends, Router SDK, Utility-like settings.

Group A: a1 (port 9201) + a2 (9202); group B: b1 (9203). fallbacks A->B.
routing_strategy latency-based-routing, num_retries=2 (Utility uses 5), allowed_fails=1, cooldown 30.
"""
import asyncio, sys, time, traceback
import litellm
from litellm import Router
import hooklab as H

mocks = H.start_evt_mocks({"a1": 9201, "a2": 9202, "b1": 9203})
litellm.callbacks = [H.PROBE]

MODEL_LIST = [H.dep("A", "a1", 9201, "US"), H.dep("A", "a2", 9202, "CH"), H.dep("B", "b1", 9203, "CH")]


def new_router(**kw):
    args = dict(model_list=[dict(d) for d in MODEL_LIST], fallbacks=[{"A": ["B"]}], num_retries=2,
                routing_strategy="latency-based-routing", allowed_fails=1, cooldown_time=30, retry_after=0)
    args.update(kw)
    return Router(**args)


async def call(r, model="A", **kw):
    t = time.time()
    try:
        resp = await r.acompletion(model=model, messages=[{"role": "user", "content": "citizen data"}],
                                   metadata={"user_api_key_team_id": "commune-x"}, **kw)
        hp = resp._hidden_params
        return f"OK model_id={hp.get('model_id')} api_base={hp.get('api_base')} content={resp.choices[0].message.content!r} ({time.time()-t:.2f}s)"
    except Exception as e:
        return f"EXC {type(e).__module__}.{type(e).__name__}: {str(e)[:220]} ({time.time()-t:.2f}s)"


def counts():
    return {k: m.count for k, m in mocks.items()}


def reset(modes):
    for k, m in mocks.items():
        m.reset()
        m.mode = modes.get(k, "up")
    H.reset_events()
    H.POLICY.update(drop_ids=set(), veto_api_bases=set(), filter_raises=False, veto_exc="plain", precheck_veto_ids=set())


async def scenario(title, modes, model="A", router_kw=None, policy=None, n=1, **call_kw):
    reset(modes)
    if policy:
        H.POLICY.update(policy)
    r = new_router(**(router_kw or {}))
    results = [await call(r, model=model, **call_kw) for _ in range(n)]
    await asyncio.sleep(0.5)
    print(f"\n===== {title} =====")
    print("modes:", modes, "policy:", {k: v for k, v in H.POLICY.items() if v})
    H.dump()
    for i, res in enumerate(results):
        print(f"RESULT[{i}]:", res)
    print("MOCK COUNTS:", counts())
    print("COOLDOWNS:", await H.cooldowns(r))
    return r


async def main():
    which = sys.argv[1:] or ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    if "S1" in which:
        # a1 down, a2 up: first attempt may hit a1 (random), then retry -> a2.
        for i in range(3):
            await scenario(f"S1.{i} a1 down / a2 up, no policy", {"a1": "down"})
    if "S2" in which:
        await scenario("S2 all of A down -> retries in A -> fallback B, no policy", {"a1": "down", "a2": "down"})
    if "S3" in which:
        await scenario("S3 policy drops a1 (US); a1 up; 10 requests", {}, policy={"drop_ids": {"a1"}}, n=10)
    if "S4" in which:
        await scenario("S4 policy drops a1 and b1 (B = disallowed group); a2 down", {"a2": "down"},
                       policy={"drop_ids": {"a1", "b1"}})
    if "S5" in which:
        await scenario("S5 policy drops everything (a1,a2,b1): zero approved", {},
                       policy={"drop_ids": {"a1", "a2", "b1"}})
    if "S6" in which:
        await scenario("S6 filter RAISES (PolicyVeto) for every call", {}, policy={"filter_raises": True})
    if "S7" in which:
        await scenario("S7 a2 down, drop a1; B allowed -> expect a2 retries then b1", {"a2": "down"},
                       policy={"drop_ids": {"a1"}})


asyncio.run(main())
