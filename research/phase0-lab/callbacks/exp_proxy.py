"""Proxy experiment: per-attempt callback behaviour of the real LiteLLM v1.92.0 proxy (Utility image, no DB, master key).

    ./run.sh callbacks/exp_proxy.py            # config P1 (lab) + P2 (Utility-effective settings)
Mocks run in threads of THIS process; proxy is a subprocess; the callback (proxy_recorder.py) appends JSONL
to callbacks/out/proxy_<cfg>_events.jsonl; we slice it per scenario by a marker event.
"""
import json, os, subprocess, sys, time
import httpx, yaml

HERE = "/lab/callbacks"
OUT = f"{HERE}/out"
sys.path.insert(0, "/lab"); sys.path.insert(0, HERE)
from mock_openai import start_mocks  # noqa: E402

MASTER = "sk-lab-master"
MSG = [{"role": "user", "content": "citizen data: AHV 756.1234.5678.97"}]


def dep(name, did, port, jurisdiction="CH", weight=None):
    lp = {"model": "openai/x", "api_base": f"http://127.0.0.1:{port}/v1", "api_key": "k"}
    if weight is not None:
        lp["weight"] = weight
    return {"model_name": name, "litellm_params": lp,
            "model_info": {"id": did, "jurisdiction": jurisdiction, "provider": "mock", "country": jurisdiction}}


MODEL_LIST = [dep("apertus", "ch-1", 9101, weight=1000), dep("apertus", "ch-2", 9102, weight=1),
              dep("fbgrp", "fb-1", 9103), dep("slow", "slow-1", 9105)]

CONFIGS = {
    "P1": {
        "model_list": MODEL_LIST,
        "router_settings": {"routing_strategy": "simple-shuffle", "num_retries": 2, "allowed_fails": 0,
                            "cooldown_time": 4, "timeout": 2, "fallbacks": [{"apertus": ["fbgrp"]}]},
        "litellm_settings": {"callbacks": ["proxy_recorder.proxy_handler_instance"], "drop_params": True},
        "general_settings": {"master_key": MASTER},
    },
    # what the Utility configmap renders (values.yaml litellm_settings + router_settings.routing_strategy)
    "P2": {
        "model_list": MODEL_LIST,
        "router_settings": {"routing_strategy": "latency-based-routing", "fallbacks": [{"apertus": ["fbgrp"]}]},
        "litellm_settings": {"num_retries": 5, "allowed_fails": 1, "cooldown_time": 30, "drop_params": True,
                             "callbacks": ["proxy_recorder.proxy_handler_instance"]},
        "general_settings": {"master_key": MASTER},
    },
}


def start_proxy(cfg_name):
    cfg_path = f"{HERE}/config_{cfg_name}.yaml"
    with open(cfg_path, "w") as f:
        yaml.safe_dump(CONFIGS[cfg_name], f, sort_keys=False)
    ev = f"{OUT}/proxy_{cfg_name}_events.jsonl"
    if os.path.exists(ev):
        os.remove(ev)
    env = dict(os.environ, EVENTS_FILE=ev, LITELLM_LOG="ERROR")
    log = open(f"{OUT}/proxy_{cfg_name}.log", "w")
    p = subprocess.Popen(["litellm", "--config", cfg_path, "--port", "4000"], env=env, stdout=log, stderr=subprocess.STDOUT)
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
        f.write(json.dumps({"t": time.time(), "hook": "MARKER", "text": text}) + "\n")


def read_events(ev, after_marker):
    out, on = [], False
    for line in open(ev):
        e = json.loads(line)
        if e["hook"] == "MARKER":
            on = e["text"] == after_marker
            continue
        if on:
            out.append(e)
    return out


def call(model="apertus", extra_body=None, headers=None, timeout=60):
    body = {"model": model, "messages": MSG}
    body.update(extra_body or {})
    h = {"Authorization": f"Bearer {MASTER}"}
    h.update(headers or {})
    t0 = time.time()
    r = httpx.post("http://127.0.0.1:4000/v1/chat/completions", json=body, headers=h, timeout=timeout)
    hdrs = {k: v for k, v in r.headers.items() if k.startswith("x-litellm")}
    try:
        j = r.json()
    except Exception:
        j = r.text
    return {"status": r.status_code, "elapsed": round(time.time() - t0, 2), "x-litellm headers": hdrs,
            "body_model": j.get("model") if isinstance(j, dict) else None,
            "content": (j.get("choices") or [{}])[0].get("message", {}).get("content") if isinstance(j, dict) and "choices" in j else None,
            "error": (j.get("error") if isinstance(j, dict) else j)}


def line(e):
    h = e["hook"]
    lpmi = e.get("lp.model_info") if isinstance(e.get("lp.model_info"), dict) else {}
    did = e.get("deployment_id") or e.get("md.model_info.id") or lpmi.get("id") or e.get("md_model_info_id")
    exc = (e.get("exception") or {}).get("chain", [None]) if e.get("exception") else e.get("exc")
    slo = e.get("slo") or {}
    s = (f"   {h:<40} dep={did!s:<7} call_id={str(e.get('litellm_call_id'))[:8]} trace={str(e.get('lp.litellm_trace_id'))[:8]} "
         f"mcd={str(e.get('mcd_obj_id'))[-5:]} has_logged={list((e.get('has_logged') or {}).keys())} "
         f"exc={(exc or [None])[:1] if isinstance(exc, list) else exc} slo.status={slo.get('status')} slo.model_id={slo.get('model_id')} "
         f"att_retries={e.get('md.attempted_retries')}")
    if h == "async_filter_deployments":
        s += f" healthy={e.get('healthy_ids')}"
    if h in ("log_success_fallback_event", "log_failure_fallback_event"):
        s += f" orig={e.get('original_model_group')} fb={e.get('fallback_model')}"
    if h == "async_post_call_failure_hook":
        s += f" md_prev_models={e.get('md_previous_models')} status={e.get('status_code')}"
    if h == "async_post_call_response_headers_hook":
        s += f" call_info={e.get('litellm_call_info')}"
    if h == "async_pre_call_hook":
        s += f" no_log={e.get('no_log')} trace={e.get('litellm_trace_id')} logging_obj={str(e.get('logging_obj_id'))[-5:]}"
    return s


def scenario(ev, mocks, name, setup, req, results, sleep_after=0.8):
    for m in mocks.values():
        m.reset()
    setup(mocks)
    marker(ev, name)
    res = call(**req)
    time.sleep(sleep_after)  # let async logging tasks flush
    evs = read_events(ev, name)
    res["mock_counts"] = {k: m.count for k, m in mocks.items()}
    results[name] = {"result": res, "events": evs}
    print(f"\n===== {name} =====")
    print("result:", json.dumps(res)[:900])
    for e in evs:
        print(line(e))


def main():
    os.makedirs(OUT, exist_ok=True)
    mocks = start_mocks({"ch-1": 9101, "ch-2": 9102, "fb-1": 9103, "slow-1": 9105})
    which = sys.argv[1:] or ["P1", "P2"]
    for cfg in which:
        p, ev = start_proxy(cfg)
        results = {}
        try:
            # warm-up call to dump effective settings (not part of any scenario)
            marker(ev, "warmup"); call()
            time.sleep(0.5)
            for e in read_events(ev, "warmup"):
                if e["hook"] == "EFFECTIVE_SETTINGS":
                    print(f"\n##### {cfg} EFFECTIVE_SETTINGS:", json.dumps(e, default=str))
                    results["EFFECTIVE_SETTINGS"] = e
            cd = CONFIGS[cfg]["router_settings"].get("cooldown_time", 5) + 1
            if cfg == "P1":
                scenario(ev, mocks, "a_success", lambda m: None, {}, results)
                scenario(ev, mocks, "b_ch1_503_then_ch2", lambda m: setattr(m["ch-1"], "mode", "down"), {}, results)
                time.sleep(cd)
                scenario(ev, mocks, "c_group_down_fallback_ok",
                         lambda m: (setattr(m["ch-1"], "mode", "down"), setattr(m["ch-2"], "mode", "down")), {}, results)
                time.sleep(cd)
                scenario(ev, mocks, "d_all_fail",
                         lambda m: [setattr(m[k], "mode", "down") for k in ("ch-1", "ch-2", "fb-1")], {}, results,
                         sleep_after=1.5)
                time.sleep(cd)
                scenario(ev, mocks, "e_timeout_after_send", lambda m: setattr(m["slow-1"], "mode", "timeout"),
                         {"model": "slow"}, results, sleep_after=1.5)
                time.sleep(cd)
                scenario(ev, mocks, "n_client_no_log_true", lambda m: None, {"extra_body": {"no-log": True}}, results)
                scenario(ev, mocks, "o_client_ids", lambda m: None,
                         {"extra_body": {"litellm_trace_id": "client-trace-123", "metadata": {"session_id": "client-sess"}},
                          "headers": {"x-litellm-call-id": "client-call-id-abc"}}, results)
            else:
                scenario(ev, mocks, "j_utility_settings_ch1_503", lambda m: setattr(m["ch-1"], "mode", "down"), {}, results,
                         sleep_after=1.0)
                scenario(ev, mocks, "j2_second_request_ch1_still_503", lambda m: setattr(m["ch-1"], "mode", "down"), {}, results,
                         sleep_after=1.0)
        finally:
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
        with open(f"{OUT}/proxy_{cfg}_results.json", "w") as f:
            json.dump(results, f, indent=1, default=str)
        time.sleep(1)


if __name__ == "__main__":
    main()
