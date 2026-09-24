"""Phase 0 / tags: does general_settings.reject_clientside_metadata_tags stop client tag widening? (v1.92.0, mocks only)

Run from lab dir:  ./run.sh tags/proxy_reject_clientside_tags.py [reject_only|reject_common|none]
 - none:          no reject flag (baseline, simple-shuffle)
 - reject_only:   reject_clientside_metadata_tags=true, custom_auth (common_checks NOT run for custom_auth by default)
 - reject_common: reject_clientside_metadata_tags=true + custom_auth_run_common_checks=true
Key sk-commune has metadata.tags=['ch'] (tags/proxy/custom_auth_tags.py). routing_strategy=simple-shuffle for unbiased counts.
"""
import json, os, subprocess, sys, time
import httpx
from tags.mock_ext import start_mocks

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "none"
PORTS = {"a-ch": 9501, "b-us": 9502, "d-ch": 9503, "d-us": 9504}
M = start_mocks(PORTS)
HERE = os.path.dirname(os.path.abspath(__file__))
PDIR = os.path.join(HERE, "proxy")


def dep(group, name, tags=None):
    lp = {"model": f"openai/{name}-model", "api_base": f"http://127.0.0.1:{PORTS[name]}/v1", "api_key": f"sk-mock-{name}"}
    if tags is not None:
        lp["tags"] = tags
    return {"model_name": group, "litellm_params": lp, "model_info": {"id": name}}


gs = {"master_key": "sk-master", "custom_auth": "custom_auth_tags.user_api_key_auth"}
if VARIANT in ("reject_only", "reject_common"):
    gs["reject_clientside_metadata_tags"] = True
if VARIANT == "reject_common":
    gs["custom_auth_run_common_checks"] = True
cfg = {
    "model_list": [dep("A", "a-ch", ["ch"]), dep("B", "b-us", ["us"]), dep("D", "d-ch", ["ch"]), dep("D", "d-us", ["us"])],
    "router_settings": {"enable_tag_filtering": True, "fallbacks": [{"A": ["B"]}], "num_retries": 0, "routing_strategy": "simple-shuffle"},
    "general_settings": gs,
    "litellm_settings": {"drop_params": True, "num_retries": 0},
}
cfg_path = os.path.join(PDIR, f"config_reject_{VARIANT}.yaml")
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=1)
log = open(os.path.join(PDIR, f"proxy_reject_{VARIANT}.log"), "w")
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


def call(name, key="sk-commune", body_extra=None, headers=None, modes=None, n=1, model="D"):
    for m in M.values():
        m.reset()
    for k, v in (modes or {}).items():
        M[k].mode = v
    results, last = {}, None
    for _ in range(n):
        body = {"model": model, "messages": [{"role": "user", "content": "citizen data"}]}
        body.update(json.loads(json.dumps(body_extra or {})))
        h = {"Authorization": f"Bearer {key}"}
        h.update(headers or {})
        r = httpx.post(base + "/v1/chat/completions", json=body, headers=h, timeout=60)
        k = f"{r.status_code}:{r.headers.get('x-litellm-model-id')}"
        results[k] = results.get(k, 0) + 1
        last = r
    counts = {k: m.count for k, m in M.items() if m.count}
    print(f"\n### {name}\n  counts={counts}\n  responses={results}")
    if last.status_code != 200:
        print(f"  last_error={last.text[:220]}")
    sys.stdout.flush()


try:
    call("T0 control: no client tags, model D, n=20", n=20)
    call("T1 body metadata.tags=['us'] n=20", body_extra={"metadata": {"tags": ["us"]}}, n=20)
    call("T2 body root tags=['us'] n=20", body_extra={"tags": ["us"]}, n=20)
    call("T3 header x-litellm-tags: us n=20", headers={"x-litellm-tags": "us"}, n=20)
    call("T4 body litellm_metadata.tags=['us'] n=20", body_extra={"litellm_metadata": {"tags": ["us"]}}, n=20)
    call("T5 body litellm_metadata={} (empty) n=20", body_extra={"litellm_metadata": {}}, n=20)
    call("T6 model A (a-ch down), client fallbacks=[{'model':'B','metadata':{'tags':['us']}}]", model="A",
         modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "B", "metadata": {"tags": ["us"]}}]})
    call("T7 model A (a-ch down), client fallbacks=[{'model':'B','metadata':{}}]", model="A",
         modes={"a-ch": "down"}, body_extra={"fallbacks": [{"model": "B", "metadata": {}}]})
    call("T8 model A (a-ch down), router fallback A->B only", model="A", modes={"a-ch": "down"})
finally:
    proc.terminate()
    try:
        proc.wait(10)
    except Exception:
        proc.kill()
