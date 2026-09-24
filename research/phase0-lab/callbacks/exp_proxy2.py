"""Proxy experiment round 2 (Utility image, no DB, master key).

    ./run.sh callbacks/exp_proxy2.py [P3 P4 P5 P6]
P3: Utility-effective settings (litellm_settings num_retries=5, allowed_fails=1, cooldown_time=30; latency-based-routing)
    -> does a 429 cool a deployment down, and for how long (5s default vs the configured 30s)?
P4: lab settings (allowed_fails=0, cooldown 3s) + BLOCK=1 + global_disable_no_log_param
    -> blocked-before-send in async_pre_call_check on a cross-jurisdiction fallback; per-attempt cooldown dedup;
       server-side correlation id; client "no-log" neutralised by global_disable_no_log_param
P5: only a callback whose hooks are all INHERITED (InheritOnly) -> does the proxy still call async_pre_call_hook?
P6: STRIP_NO_LOG=1 (pop "no-log" in async_pre_call_hook, no global flag) -> does that restore logging callbacks?
"""
import json, os, subprocess, sys, time
import httpx, yaml

HERE = "/lab/callbacks"
OUT = f"{HERE}/out"
sys.path.insert(0, HERE)
from mock_status import start_status_mocks  # noqa: E402

MASTER = "sk-lab-master"
MSG = [{"role": "user", "content": "citizen data: AHV 756.1234.5678.97"}]


def dep(name, did, port, jurisdiction="CH", weight=None):
    lp = {"model": "openai/x", "api_base": f"http://127.0.0.1:{port}/v1", "api_key": "k"}
    if weight is not None:
        lp["weight"] = weight
    return {"model_name": name, "litellm_params": lp,
            "model_info": {"id": did, "jurisdiction": jurisdiction, "provider": "mock", "country": jurisdiction}}


ML = [dep("apertus", "ch-1", 9101, weight=1000), dep("apertus", "ch-2", 9102, weight=1),
      dep("usgrp", "us-1", 9104, jurisdiction="US"), dep("rl", "rl-1", 9106), dep("rl", "rl-2", 9107)]

CONFIGS = {
    "P3": ({"model_list": ML,
            "router_settings": {"routing_strategy": "latency-based-routing"},
            "litellm_settings": {"num_retries": 5, "allowed_fails": 1, "cooldown_time": 30, "drop_params": True,
                                 "callbacks": ["proxy_recorder2.probe"]},
            "general_settings": {"master_key": MASTER}}, {}),
    "P4": ({"model_list": ML,
            "router_settings": {"routing_strategy": "simple-shuffle", "num_retries": 1, "allowed_fails": 0, "cooldown_time": 3,
                                "timeout": 2, "fallbacks": [{"apertus": ["usgrp"]}]},
            "litellm_settings": {"callbacks": ["proxy_recorder2.probe"], "drop_params": True, "global_disable_no_log_param": True},
            "general_settings": {"master_key": MASTER}}, {"BLOCK": "1"}),
    "P5": ({"model_list": ML,
            "router_settings": {"routing_strategy": "simple-shuffle", "num_retries": 0},
            "litellm_settings": {"callbacks": ["proxy_recorder2.inherit_only"], "drop_params": True},
            "general_settings": {"master_key": MASTER}}, {}),
    "P7": ({"model_list": ML + [dep("single", "s-1", 9101)],
            "router_settings": {"routing_strategy": "simple-shuffle", "num_retries": 0, "allowed_fails": 0, "cooldown_time": 3},
            "litellm_settings": {"callbacks": ["proxy_recorder2.probe"], "drop_params": True},
            "general_settings": {"master_key": MASTER}}, {}),
    "P6": ({"model_list": ML,
            "router_settings": {"routing_strategy": "simple-shuffle", "num_retries": 0},
            "litellm_settings": {"callbacks": ["proxy_recorder2.probe"], "drop_params": True},
            "general_settings": {"master_key": MASTER}}, {"STRIP_NO_LOG": "1"}),
}


def start_proxy(name):
    cfg, env_extra = CONFIGS[name]
    cfg_path = f"{HERE}/config2_{name}.yaml"
    yaml.safe_dump(cfg, open(cfg_path, "w"), sort_keys=False)
    ev = f"{OUT}/proxy2_{name}_events.jsonl"
    if os.path.exists(ev):
        os.remove(ev)
    env = dict(os.environ, EVENTS_FILE=ev, LITELLM_LOG="ERROR", **env_extra)
    p = subprocess.Popen(["litellm", "--config", cfg_path, "--port", "4000"], env=env,
                         stdout=open(f"{OUT}/proxy2_{name}.log", "w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            if httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=1).status_code == 200:
                return p, ev
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("proxy did not start")


def marker(ev, text):
    with open(ev, "a") as f:
        f.write(json.dumps({"hook": "MARKER", "text": text, "wall": time.time()}) + "\n")


def events_after(ev, name):
    out, on = [], False
    for line in open(ev):
        e = json.loads(line)
        if e["hook"] == "MARKER":
            on = e["text"] == name
            continue
        if on:
            out.append(e)
    return out


def call(model="apertus", extra_body=None, headers=None):
    body = {"model": model, "messages": MSG, **(extra_body or {})}
    r = httpx.post("http://127.0.0.1:4000/v1/chat/completions", json=body,
                   headers={"Authorization": f"Bearer {MASTER}", **(headers or {})}, timeout=90)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
    return {"status": r.status_code, "hdr": {k: v for k, v in r.headers.items() if k.startswith("x-litellm-model") or k.startswith("x-litellm-attempted") or k == "x-tl-request-id" or k == "x-litellm-call-id"},
            "content": (j.get("choices") or [{}])[0].get("message", {}).get("content") if "choices" in j else None,
            "error": (j.get("error") or {}).get("message", "")[:300] if isinstance(j.get("error"), dict) else None}


def show(name, res, evs, mocks):
    print(f"\n===== {name} =====")
    print("result:", json.dumps(res))
    print("mock_counts:", {k: m.count for k, m in mocks.items()})
    for e in evs:
        lpmi = e.get("lp.model_info") if isinstance(e.get("lp.model_info"), dict) else {}
        did = e.get("deployment_id") or e.get("md.model_info.id") or lpmi.get("id") or e.get("md_model_info_id")
        exc = (e.get("exception") or {}).get("chain", [None])[:1] if e.get("exception") else (e.get("exc") or [None])[:1]
        extra = {k: e.get(k) for k in ("healthy_ids", "cooldowns", "tl_request_id", "md.tl_request_id", "client_no_log",
                                       "client_supplied_tl_request_id", "litellm_call_info", "original_model_group",
                                       "fallback_model", "status_code") if e.get(k) is not None}
        print(f"   [{e.get('tag')}] {e['hook']:<40} dep={did!s:<6} exc={exc} slo.status={(e.get('slo') or {}).get('status')} {extra}")


def scen(ev, mocks, name, setup, req=None, wait=1.0):
    for m in mocks.values():
        m.reset()
    setup(mocks)
    marker(ev, name)
    res = call(**(req or {}))
    time.sleep(wait)
    evs = events_after(ev, name)
    show(name, res, evs, mocks)
    return res, evs


def main():
    os.makedirs(OUT, exist_ok=True)
    mocks = start_status_mocks({"ch-1": 9101, "ch-2": 9102, "us-1": 9104, "rl-1": 9106, "rl-2": 9107})
    results = {}
    for name in (sys.argv[1:] or ["P3", "P4", "P5", "P6"]):
        p, ev = start_proxy(name)
        R = results.setdefault(name, {})
        try:
            if name == "P3":
                # find a request that lands on rl-1 while rl-1 returns 429 (latency-based routing may pick rl-2 first)
                t_cool = None
                for i in range(12):
                    for m in mocks.values():
                        m.reset()
                    mocks["rl-1"].mode = 429
                    marker(ev, f"P3_hit_{i}")
                    res = call(model="rl")
                    time.sleep(0.4)
                    evs = events_after(ev, f"P3_hit_{i}")
                    if mocks["rl-1"].count > 0:
                        t_cool = mocks["rl-1"].requests[-1]["t"]
                        show(f"P3_429_on_rl-1 (try {i})", res, evs, mocks)
                        break
                R["t_cool"] = t_cool
                mocks["rl-1"].mode = "up"
                # poll: when does rl-1 re-appear in the healthy list seen by async_filter_deployments?
                back_after = None
                for j in range(40):
                    marker(ev, f"P3_poll_{j}")
                    call(model="rl")
                    time.sleep(0.25)
                    evs = events_after(ev, f"P3_poll_{j}")
                    healthy = [e.get("healthy_ids") for e in evs if e["hook"] == "async_filter_deployments"]
                    cds = [e.get("cooldowns") for e in evs if e.get("cooldowns") is not None]
                    dt = round(time.time() - t_cool, 2) if t_cool else None
                    print(f"   poll t+{dt}s healthy_seen_by_filter={healthy} cooldowns={cds}")
                    if healthy and "rl-1" in (healthy[0] or []):
                        back_after = dt
                        break
                    time.sleep(0.75)
                R["rl-1_back_in_healthy_after_s"] = back_after
                print(f"P3 RESULT: rl-1 back in healthy list after ~{back_after}s (litellm_settings.cooldown_time=30)")
                # 503 on the only... all deployments of a 2-deployment group: does v2 logic cool down on 503?
                R["503_both"] = scen(ev, mocks, "P3_503_both_rl",
                                     lambda m: (setattr(m["rl-1"], "mode", 503), setattr(m["rl-2"], "mode", 503)),
                                     {"model": "rl"}, wait=1.0)[0]
            elif name == "P4":
                R["block"] = scen(ev, mocks, "P4_ch_down_fallback_to_US_blocked",
                                  lambda m: (setattr(m["ch-1"], "mode", 503), setattr(m["ch-2"], "mode", 503)), wait=2.5)[0]
                time.sleep(3.5)
                R["timeout_ch"] = scen(ev, mocks, "P4_ch1_timeout_then_ch2",
                                       lambda m: setattr(m["ch-1"], "mode", "timeout"), wait=1.0)[0]
                time.sleep(3.5)
                R["no_log"] = scen(ev, mocks, "P4_client_no_log_with_global_disable", lambda m: None,
                                   {"extra_body": {"no-log": True, "metadata": {"tl_request_id": "client-forged"}}}, wait=1.0)[0]
            elif name == "P5":
                R["inherit"] = scen(ev, mocks, "P5_inherit_only_success", lambda m: None, wait=1.0)[0]
            elif name == "P7":
                R["r1"] = scen(ev, mocks, "P7_single_503_cooldown", lambda m: setattr(m["ch-1"], "mode", 503),
                               {"model": "single"}, wait=0.8)[0]
                R["r2"] = scen(ev, mocks, "P7_single_in_cooldown_no_deployments", lambda m: None, {"model": "single"}, wait=0.8)[0]
                time.sleep(3.2)
                R["r3"] = scen(ev, mocks, "P7_single_after_cooldown", lambda m: None, {"model": "single"}, wait=0.8)[0]
            elif name == "P6":
                R["strip"] = scen(ev, mocks, "P6_client_no_log_stripped_in_pre_call_hook", lambda m: None,
                                  {"extra_body": {"no-log": True}}, wait=1.0)[0]
        finally:
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
        time.sleep(1)
    json.dump(results, open(f"{OUT}/proxy2_results.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
