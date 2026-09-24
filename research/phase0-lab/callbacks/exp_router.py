"""SDK Router experiment: which CustomLogger hooks fire per attempt, with which deployment identity.

Run all scenarios (each in a fresh subprocess so global litellm callbacks / cooldowns never leak):
    ./run.sh callbacks/exp_router.py
Run one:
    ./run.sh callbacks/exp_router.py <scenario>
Output: human-readable sequence per scenario + JSON dump in callbacks/out/router_<scenario>.json
"""
import asyncio, json, os, socket, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SCENARIOS = ["a_success", "b_503_then_other_default", "b2_503_then_other_allowed_fails0", "c_group_fails_fallback_ok",
             "d_all_fail", "e_timeout_after_send", "e2_conn_refused", "e3_connect_timeout", "f_cooldown_skip_and_return",
             "g_single_deployment_503_cooldown", "h_block_in_pre_call_check", "i_block_in_filter_deployments",
             "j_utility_settings_503"]

MSG = [{"role": "user", "content": "citizen data: AHV 756.1234.5678.97"}]


def dep(name, did, port, jurisdiction="CH", provider="mock", weight=None, extra_lp=None, api_base=None):
    lp = {"model": "openai/x", "api_base": api_base or f"http://127.0.0.1:{port}/v1", "api_key": "k"}
    if weight is not None:
        lp["weight"] = weight
    lp.update(extra_lp or {})
    return {"model_name": name, "litellm_params": lp,
            "model_info": {"id": did, "jurisdiction": jurisdiction, "provider": provider, "country": jurisdiction}}


def start_blackhole(port):
    """TCP listener whose accept queue is pre-filled and never accepted -> new SYNs are dropped -> ConnectTimeout."""
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(0)
    fillers = []
    for _ in range(3):
        c = socket.socket(); c.setblocking(False)
        try:
            c.connect(("127.0.0.1", port))
        except BlockingIOError:
            pass
        fillers.append(c)
    time.sleep(0.3)
    return s, fillers


def summarize(events):
    lines = []
    for e in events:
        h = e["hook"]
        lpmi = e.get("lp.model_info") if isinstance(e.get("lp.model_info"), dict) else {}
        did = e.get("deployment_id") or e.get("md.model_info.id") or lpmi.get("id")
        exc = (e.get("exception") or {}).get("chain", [None])[0] if e.get("exception") else None
        slo = e.get("slo") or {}
        resp = e.get("resp") or {}
        extra = ""
        if h == "async_filter_deployments":
            extra = f"healthy={e.get('healthy_ids')}"
        if h in ("log_success_fallback_event", "log_failure_fallback_event"):
            extra = f"orig_group={e.get('original_model_group')} fb_model={e.get('fallback_model')} md.model_info.id={e.get('md_model_info_id')} depth={e.get('fallback_depth')}"
        lines.append(f"  t={e['t']:>7} {h:<42} dep={did!s:<6} call_id={str(e.get('litellm_call_id'))[:8]} "
                     f"trace={str(e.get('lp.litellm_trace_id'))[:8]} mcd={str(e.get('mcd_obj_id'))[-5:]} "
                     f"exc={exc} slo.status={slo.get('status')} slo.model_id={slo.get('model_id')} "
                     f"resp.model={resp.get('resp.model')} {extra}")
    return "\n".join(lines)


async def run_one(name):
    import litellm
    from litellm import Router
    from mock_openai import start_mocks
    sys.path.insert(0, HERE)
    from recorder import Recorder

    rec = Recorder()
    litellm.callbacks = [rec]
    mocks = start_mocks({"ch-1": 9101, "ch-2": 9102, "fb-1": 9103, "us-1": 9104})
    result = {"scenario": name}
    router_kwargs = {}
    req_kwargs = {}
    model = "apertus"
    model_list = [dep("apertus", "ch-1", 9101, weight=1000), dep("apertus", "ch-2", 9102, weight=1),
                  dep("fbgrp", "fb-1", 9103, jurisdiction="CH")]
    notes = []
    extra_requests = 0

    if name == "a_success":
        pass
    elif name == "b_503_then_other_default":
        mocks["ch-1"].mode = "down"
    elif name == "b2_503_then_other_allowed_fails0":
        mocks["ch-1"].mode = "down"
        router_kwargs["allowed_fails"] = 0
    elif name == "c_group_fails_fallback_ok":
        mocks["ch-1"].mode = "down"; mocks["ch-2"].mode = "down"
        router_kwargs["fallbacks"] = [{"apertus": ["fbgrp"]}]
        router_kwargs["num_retries"] = 1
    elif name == "d_all_fail":
        for m in ("ch-1", "ch-2", "fb-1"):
            mocks[m].mode = "down"
        router_kwargs["fallbacks"] = [{"apertus": ["fbgrp"]}]
        router_kwargs["num_retries"] = 1
    elif name == "e_timeout_after_send":
        mocks["ch-1"].mode = "timeout"
        model_list = [dep("slow", "ch-1", 9101)]
        model = "slow"
        router_kwargs.update(timeout=1.5, num_retries=1)
    elif name == "e2_conn_refused":
        model_list = [dep("refused", "dead-1", 9199)]  # nothing listens on 9199
        model = "refused"
        router_kwargs.update(timeout=1.5, num_retries=1)
    elif name == "e3_connect_timeout":
        bh = start_blackhole(9198)
        model_list = [dep("blackhole", "bh-1", 9198)]
        model = "blackhole"
        router_kwargs.update(timeout=1.5, num_retries=0)
    elif name == "f_cooldown_skip_and_return":
        mocks["ch-1"].mode = "down"
        router_kwargs.update(allowed_fails=0, cooldown_time=3, num_retries=1)
        extra_requests = 1
    elif name == "g_single_deployment_503_cooldown":
        mocks["ch-1"].mode = "down"
        model_list = [dep("single", "ch-1", 9101)]
        model = "single"
        router_kwargs.update(num_retries=0)
    elif name == "h_block_in_pre_call_check":
        # fallback from CH group (down) into a US group; block non-CH in async_pre_call_check (last hook before send)
        mocks["ch-1"].mode = "down"; mocks["ch-2"].mode = "down"
        model_list = [dep("apertus", "ch-1", 9101), dep("apertus", "ch-2", 9102), dep("usgrp", "us-1", 9104, jurisdiction="US")]
        router_kwargs.update(fallbacks=[{"apertus": ["usgrp"]}], num_retries=1)

        class Blocked(Exception):
            pass

        orig = rec.async_pre_call_check

        async def blocking_check(deployment, parent_otel_span):
            await orig(deployment, parent_otel_span)
            if deployment.get("model_info", {}).get("jurisdiction") != "CH":
                rec._rec("POLICY_BLOCK", deployment_id=deployment["model_info"]["id"])
                raise Blocked(f"blocked before send: {deployment['model_info']['id']}")
        rec.async_pre_call_check = blocking_check
    elif name == "i_block_in_filter_deployments":
        mocks["ch-1"].mode = "down"; mocks["ch-2"].mode = "down"
        model_list = [dep("apertus", "ch-1", 9101), dep("apertus", "ch-2", 9102), dep("usgrp", "us-1", 9104, jurisdiction="US")]
        router_kwargs.update(fallbacks=[{"apertus": ["usgrp"]}], num_retries=1)
        orig = rec.async_filter_deployments

        async def filtering(model, healthy_deployments, messages, request_kwargs=None, parent_otel_span=None):
            await orig(model, healthy_deployments, messages, request_kwargs, parent_otel_span)
            keep = [d for d in healthy_deployments if d.get("model_info", {}).get("jurisdiction") == "CH"]
            dropped = [d["model_info"]["id"] for d in healthy_deployments if d not in keep]
            if dropped:
                rec._rec("POLICY_FILTER", dropped=dropped)
            return keep
        rec.async_filter_deployments = filtering
    elif name == "j_utility_settings_503":
        # what the Utility effectively runs: litellm_settings num_retries=5, allowed_fails=1, cooldown_time=30
        litellm.num_retries = 5
        litellm.allowed_fails = 1
        setattr(litellm, "cooldown_time", 30)
        mocks["ch-1"].mode = "down"
        router_kwargs.update(routing_strategy="latency-based-routing")

    router = Router(model_list=model_list, **router_kwargs)
    result["router_effective"] = {"num_retries": router.num_retries, "retry_after": router.retry_after,
                                  "allowed_fails": router.allowed_fails, "cooldown_time": router.cooldown_time,
                                  "timeout": router.timeout, "routing_strategy": router.routing_strategy,
                                  "disable_cooldowns": router.disable_cooldowns,
                                  "default_litellm_params.max_retries": router.default_litellm_params.get("max_retries")}
    t0 = time.time()
    resp_info, err = None, None
    try:
        resp = await router.acompletion(model=model, messages=MSG, **req_kwargs)
        resp_info = {"content": resp.choices[0].message.content, "model": resp.model,
                     "hidden.model_id": resp._hidden_params.get("model_id"),
                     "hidden.api_base": resp._hidden_params.get("api_base"),
                     "additional_headers": {k: v for k, v in (resp._hidden_params.get("additional_headers") or {}).items()
                                            if "litellm" in k or "attempted" in k}}
    except Exception as e:
        err = {"type": type(e).__name__, "status_code": getattr(e, "status_code", None), "msg": str(e)[:300],
               "num_retries": getattr(e, "num_retries", None), "max_retries": getattr(e, "max_retries", None)}
    result["elapsed_s"] = round(time.time() - t0, 2)
    await asyncio.sleep(0.5)  # let create_task() success logging run
    cds = await router.cooldown_cache.async_get_active_cooldowns(model_ids=router.get_model_ids(), parent_otel_span=None)
    result["cooldowns_after_req1"] = [c[0] for c in (cds or [])]

    if name == "f_cooldown_skip_and_return":
        # request 2 while ch-1 is cooling down; ch-1 now healthy again but should be skipped silently
        mocks["ch-1"].mode = "up"
        rec._rec("---- request 2 (ch-1 cooling down, mock is up again) ----")
        for i in range(3):
            r2 = await router.acompletion(model=model, messages=MSG)
        result["req2_counts"] = {k: m.count for k, m in mocks.items()}
        await asyncio.sleep(3.5)
        rec._rec("---- request 3 (after cooldown_time=3s) ----")
        r3 = await router.acompletion(model=model, messages=MSG)
        result["req3_model_id"] = r3._hidden_params.get("model_id")
        await asyncio.sleep(0.3)

    result["response"] = resp_info
    result["error"] = err
    result["mock_counts"] = {k: m.count for k, m in mocks.items()}
    result["events"] = rec.events
    hooks = [e["hook"] for e in rec.events]
    print(f"\n===== {name} =====  elapsed={result['elapsed_s']}s")
    print("router_effective:", result["router_effective"])
    print("mock_counts:", result["mock_counts"], " cooldowns_after_req1:", result["cooldowns_after_req1"])
    print("response:", resp_info)
    print("error:", err)
    print("hook sequence:")
    print(summarize(rec.events))
    with open(os.path.join(OUT, f"router_{name}.json"), "w") as f:
        json.dump(result, f, indent=1, default=str)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1:
        asyncio.run(run_one(sys.argv[1]))
    else:
        for s in SCENARIOS:
            subprocess.run([sys.executable, os.path.abspath(__file__), s], check=False)
