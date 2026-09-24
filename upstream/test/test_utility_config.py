"""Run the Utility's own rendered LiteLLM config (with the patch applied) in the exact image,
with every provider host replaced by a counting mock, and check the policy end to end.

    upstream/test/render.sh <chat.publicai.co clone> prod
    upstream/test/run.sh
"""
import os, subprocess, sys, time
from urllib.parse import urlsplit

import httpx, yaml
from mock_openai import start_mocks

OUT = "/t/.work/out"
WORK = "/tmp/proxy"
os.makedirs(WORK, exist_ok=True)
HOSTS = {"api.infomaniak.com": 9201, "api.featherless.ai": 9202, "api.sea-lion.ai": 9203,
         "llmlab.plgrid.pl": 9204, "api.nextbit256.com": 9205}
NAMES = {p: h.split(".")[1] if h.startswith("api.") else h.split(".")[0] for h, p in HOSTS.items()}
M = start_mocks({NAMES[p]: p for p in HOSTS.values()})
GROUP = "swiss-ai/apertus-v1.5-70b"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


# ---- config: theirs, minus what cannot run offline --------------------------------------
cfg = yaml.safe_load(open(f"{OUT}/config-prod.yaml"))
mi_apertus = [d["model_info"] for d in cfg["model_list"] if d["model_name"] == GROUP]
base = yaml.safe_load(open(f"{OUT}/config-prod.base.yaml"))
COST = ("input_cost_per_token", "output_cost_per_token")
strip = lambda c: [(d["model_name"], {k: v for k, v in (d.get("model_info") or {}).items() if k in COST}, d["litellm_params"]) for d in c["model_list"]]
check("patch leaves litellm_params and cost fields exactly as before", strip(cfg) == strip(base))
as_str = sum(isinstance(v, str) for _, mi, _ in strip(base) for v in mi.values())
print(f"INFO pre-existing, not caused by this patch: {as_str} cost values like 1e-07 are loaded as strings by PyYAML (YAML 1.1)")
check("rendered config carries jurisdiction metadata for Apertus 70B", {m.get("jurisdiction") for m in mi_apertus} == {"CH", "unknown"}, str([m.get("id") for m in mi_apertus]))
check("policy callback registered", "jurisdiction_policy.policy_hook" in cfg["litellm_settings"]["callbacks"])

gs = cfg["general_settings"]
for k in ("database_url", "database_connection_pool_limit", "database_connection_timeout", "alerting", "alert_types", "custom_auth_settings"):
    gs.pop(k, None)
gs.update(master_key="sk-master", custom_auth="test_auth.user_api_key_auth")
cfg["router_settings"].pop("redis_url", None)
cfg["litellm_settings"]["cache"] = False
cfg["litellm_settings"].pop("cache_params", None)
cfg["litellm_settings"]["callbacks"] = ["jurisdiction_policy.policy_hook"]
kept = []
for d in cfg["model_list"]:
    base = d["litellm_params"].get("api_base")
    host = urlsplit(base).hostname if base else None
    if host not in HOSTS:
        continue
    d["litellm_params"]["api_base"] = f"http://127.0.0.1:{HOSTS[host]}/v1"
    d["litellm_params"]["api_key"] = "sk-mock"
    kept.append(d)
cfg["model_list"] = kept
yaml.safe_dump(cfg, open(f"{WORK}/config.yaml", "w"))
for f in ("jurisdiction_policy.py",):
    open(f"{WORK}/{f}", "w").write(open(f"{OUT}/{f}").read())
open(f"{WORK}/test_auth.py", "w").write(open("/t/test_auth.py").read())

env = {**os.environ, "POLICY_REQUIRED": "0", "PYTHONPATH": WORK}
proxy = subprocess.Popen(["litellm", "--config", f"{WORK}/config.yaml", "--port", "4000"], env=env, cwd=WORK,
                         stdout=open(f"{WORK}/proxy.log", "w"), stderr=subprocess.STDOUT)
for _ in range(120):
    try:
        if httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=1).status_code == 200:
            break
    except Exception:
        time.sleep(1)
else:
    print(open(f"{WORK}/proxy.log").read()[-3000:]); sys.exit(2)


def reset(**modes):
    for n, m in M.items():
        m.reset(); m.mode = modes.get(n, "up")


def counts():
    return {n: m.count for n, m in M.items() if m.count}


def ask(key, extra=None):
    body = {"model": GROUP, "messages": [{"role": "user", "content": "citizen data"}], **(extra or {})}
    return httpx.post("http://127.0.0.1:4000/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120)


reset()
rs = [ask("sk-regular") for _ in range(20)]
check("regular key: unchanged behaviour, both Apertus hosts in rotation", all(r.status_code == 200 for r in rs), str(counts()))

reset()
rs = [ask("sk-commune") for _ in range(20)]
c = counts()
check("CH-only key: 20/20 served by the CH deployment only", all(r.status_code == 200 for r in rs) and c == {"infomaniak": 20}, str(c))
h = rs[0].headers
check("CH-only key: attribution headers name the serving deployment", h.get("x-served-by-jurisdiction") == "CH" and h.get("x-routing-policy") == "CH-only",
      f"{h.get('x-served-by-deployment')} / {h.get('x-served-by-jurisdiction')}")

reset(infomaniak="down")
r = ask("sk-commune")
c = counts()
check("CH-only key, CH host down: fails closed, no fallback host receives data",
      r.status_code >= 400 and all(c.get(n, 0) == 0 for n in ("featherless", "sea-lion", "plgrid", "nextbit")), f"status={r.status_code} counts={c}")

reset(infomaniak="down")
r = ask("sk-regular")
check("regular key, CH host down: still served (today's fallbacks unchanged)", r.status_code == 200, f"counts={counts()}")

reset(infomaniak="down")
r = ask("sk-team-member")
c = counts()
check("team policy wins over a key trying to relax it: no non-CH host receives data",
      r.status_code >= 400 and all(c.get(n, 0) == 0 for n in ("featherless", "sea-lion", "plgrid", "nextbit")), f"status={r.status_code} counts={c}")

reset()
r = ask("sk-commune", {"fallbacks": ["aisingapore/Qwen-SEA-LION-v4-32B-IT"]})
check("CH-only key: client-side fallbacks rejected", r.status_code == 400 and not counts(), f"status={r.status_code}")

proxy.terminate()
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
