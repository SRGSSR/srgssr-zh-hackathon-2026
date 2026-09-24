"""SDK Router round 2.
    ./run.sh callbacks/exp_router2.py            # all
g2_single_cooldown_allowed_fails0 : single approved deployment + allowed_fails=0 -> is it cooled down by one 503?
                                    next request: silent skip? which callbacks? mock count?
k_previous_models_cross_request   : Router.previous_models is a per-ROUTER list -> does request B's metadata carry
                                    request A's failed-attempt breadcrumbs?
"""
import asyncio, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
MSG = [{"role": "user", "content": "hi"}]


def dep(name, did, port, weight=None):
    lp = {"model": "openai/x", "api_base": f"http://127.0.0.1:{port}/v1", "api_key": "k"}
    if weight:
        lp["weight"] = weight
    return {"model_name": name, "litellm_params": lp, "model_info": {"id": did, "jurisdiction": "CH"}}


async def run(name):
    import litellm
    from litellm import Router
    from mock_openai import start_mocks
    sys.path.insert(0, HERE)
    from recorder import Recorder
    rec = Recorder(); litellm.callbacks = [rec]
    mocks = start_mocks({"ch-1": 9101, "ch-2": 9102})
    out = {"scenario": name}
    if name == "g2_single_cooldown_allowed_fails0":
        mocks["ch-1"].mode = "down"
        r = Router(model_list=[dep("single", "ch-1", 9101)], allowed_fails=0, cooldown_time=3, num_retries=0)
        for i, mode in enumerate(["down", "up", "up"]):
            mocks["ch-1"].mode = mode
            if i == 2:
                await asyncio.sleep(3.2)
            rec._rec(f"---- request {i+1} (mock={mode}) ----")
            before = mocks["ch-1"].count
            try:
                resp = await r.acompletion(model="single", messages=MSG)
                res = f"OK {resp._hidden_params.get('model_id')}"
            except Exception as e:
                res = f"{type(e).__name__}: {str(e)[:140]}"
            await asyncio.sleep(0.3)
            cds = await r.cooldown_cache.async_get_active_cooldowns(model_ids=r.get_model_ids(), parent_otel_span=None)
            line = f"request {i+1}: {res} | mock ch-1 received {mocks['ch-1'].count - before} | cooldowns={[c[0] for c in cds or []]}"
            print(line); out[f"req{i+1}"] = line
    elif name == "k_previous_models_cross_request":
        mocks["ch-1"].mode = "down"
        r = Router(model_list=[dep("g", "ch-1", 9101, weight=1000), dep("g", "ch-2", 9102, weight=1)], num_retries=1)
        for who in ["commune-A", "commune-B"]:
            rec._rec(f"---- request from {who} ----")
            try:
                await r.acompletion(model="g", messages=MSG, metadata={"commune": who})
            except Exception as e:
                pass
        # inspect previous_models as seen in B's retry attempt
        for e in rec.events:
            pass
        md_seen = []
        # the Recorder snapshot does not keep previous_models content; read it from the router directly
        pm = [{"commune": (p.get("metadata") or {}).get("commune"), "litellm_call_id": p.get("litellm_call_id"),
               "exception_type": p.get("exception_type")} for p in r.previous_models]
        print("router.previous_models after A and B:", json.dumps(pm, indent=1))
        out["previous_models"] = pm
    print("hook sequence:")
    for e in rec.events:
        lpmi = e.get("lp.model_info") if isinstance(e.get("lp.model_info"), dict) else {}
        did = e.get("deployment_id") or lpmi.get("id")
        exc = (e.get("exception") or {}).get("chain", [None])[:1] if e.get("exception") else None
        print(f"   {e['hook']:<40} dep={did!s:<6} exc={exc} healthy={e.get('healthy_ids')} prev_models_len={e.get('md.previous_models_len')}")
    out["events"] = rec.events
    json.dump(out, open(os.path.join(OUT, f"router2_{name}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        asyncio.run(run(sys.argv[1]))
    else:
        for s in ["g2_single_cooldown_allowed_fails0", "k_previous_models_cross_request"]:
            print(f"\n===== {s} =====", flush=True)
            subprocess.run([sys.executable, os.path.abspath(__file__), s])
