"""End-to-end run of the Utility's REAL rendered LiteLLM config inside the exact image (v1.92.0 local).

Usage (from lab dir):  ./run.sh utility/exp_utility_proxy.py [current|patched]
  current -> utility/rendered/config-prod.yaml          (today's template output)
  patched -> utility/rendered/config-prod-patched.yaml  (template patch + proposed jurisdiction schema)

Rewrites only what cannot run offline: every api_base host -> local mock, drops Bedrock models,
database_url, redis, slack alerting, prometheus. Keeps: routing_strategy, fallbacks, litellm_settings
num_retries/allowed_fails/cooldown_time, custom_auth (mode auto), custom_lago_callback, user_header_mappings.
Adds timeline_probe.probe callback. Lago API is mocked to capture billing events.
"""
import copy, json, os, re, shutil, subprocess, sys, threading, time
import httpx, uvicorn, yaml
from fastapi import FastAPI, Request
from mock_openai import start_mocks

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "current"
SRC = {"current": "/lab/utility/rendered/config-prod.yaml",
       "patched": "/lab/utility/rendered/config-prod-patched.yaml"}[VARIANT]
WORK = f"/lab/utility/proxy/run-{VARIANT}"
HOSTS = {  # real host -> (mock name, port)
    "api.infomaniak.com": ("infomaniak", 9201), "api.featherless.ai": ("featherless", 9202),
    "api.sea-lion.ai": ("sealion", 9203), "llmlab.plgrid.pl": ("plgrid", 9204),
    "api.nextbit256.com": ("nextbit", 9205), "router.huggingface.co": ("hf", 9206),
    "www.example.com": ("example", 9207),
}
MASTER = "sk-lab-master"
OUT = []


def log(*a):
    s = " ".join(str(x) for x in a)
    OUT.append(s)
    print(s, flush=True)
    try:
        with open(f"{WORK}/results.txt", "a") as f:
            f.write(s + "\n")
    except FileNotFoundError:
        pass


# ---------- build config ----------
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
for f in ("custom_auth.py", "custom_lago_callback.py", "timeline_probe.py"):
    shutil.copy(f"/lab/utility/proxy/{f}", WORK)
raw = open(SRC).read()
cfg = yaml.safe_load(raw)
log(f"== VARIANT {VARIANT}  source={SRC}")
# YAML typing check (PyYAML/YAML 1.1: '1e-07' without a dot is a STRING)
for m in cfg["model_list"]:
    mi = m.get("model_info") or {}
    for k in ("input_cost_per_token", "output_cost_per_token"):
        if k in mi and not isinstance(mi[k], float):
            log(f"  YAML-TYPE {m['model_name']} {k}={mi[k]!r} parsed as {type(mi[k]).__name__}")
gs = cfg["general_settings"]
for k in ("database_url", "database_connection_pool_limit", "database_connection_timeout", "alerting", "alert_types"):
    gs.pop(k, None)
cfg["router_settings"].pop("redis_url", None)
ls = cfg["litellm_settings"]
ls["cache"] = False
ls.pop("cache_params", None)
ls["callbacks"] = [c for c in ls.get("callbacks", []) if c != "prometheus"] + ["timeline_probe.probe"]
new_list = []
for m in cfg["model_list"]:
    lp = m["litellm_params"]
    if lp["model"].startswith("bedrock/") or lp["model"].startswith("auto_router/"):
        continue
    host = re.sub(r"^https?://([^/]+).*$", r"\1", lp["api_base"])
    name, port = HOSTS[host]
    lp["api_base"] = f"http://127.0.0.1:{port}/v1"
    new_list.append(m)
cfg["model_list"] = new_list
yaml.safe_dump(cfg, open(f"{WORK}/config.yaml", "w"), sort_keys=False)
log(f"  model_list entries kept: {len(new_list)}; fallbacks entries: {len(cfg['router_settings'].get('fallbacks', []))}")

# ---------- mocks ----------
mocks = start_mocks({n: p for n, p in HOSTS.values()})
lago_events = []
lago = FastAPI()


@lago.post("/api/v1/events")
async def _ev(req: Request):
    lago_events.append(await req.json())
    return {"ok": True}


threading.Thread(target=uvicorn.Server(uvicorn.Config(lago, host="127.0.0.1", port=9299, log_level="warning")).run,
                 daemon=True).start()

# ---------- proxy ----------
env = dict(os.environ, LITELLM_MASTER_KEY=MASTER, LAGO_API_BASE="http://127.0.0.1:9299", LAGO_API_KEY="lago-dummy",
           LAGO_API_EVENT_CODE="public_ai_models", LAGO_API_CHARGE_BY="end_user_id", PROBE_OUT=f"{WORK}/timeline.jsonl",
           LITELLM_LOG="INFO")
for v in ("INFOMANIAK_API_KEY", "FEATHERLESS_API_KEY", "SEALION_API_KEY", "BIELIK_API_KEY", "NEXBIT_API_KEY",
          "HF_CURRENT_AI_CREDITS", "CSCS_API_KEY", "PHOENIQS_API_KEY"):
    env[v] = f"dummy-{v.lower()}"
env.pop("DATABASE_URL", None)
plog = open(f"{WORK}/proxy.log", "w")
proc = subprocess.Popen(["litellm", "--config", f"{WORK}/config.yaml", "--port", "4000"], env=env, stdout=plog,
                        stderr=subprocess.STDOUT, cwd=WORK)
c = httpx.Client(base_url="http://127.0.0.1:4000", timeout=900)
for _ in range(120):
    try:
        if c.get("/health/liveliness").status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    log("PROXY DID NOT START");
    print(open(f"{WORK}/proxy.log").read()[-4000:]);
    sys.exit(1)
log("  proxy up")

H = {"Authorization": f"Bearer {MASTER}"}
RH = ("x-litellm-model-id", "x-litellm-model-api-base", "x-litellm-model-group", "x-litellm-attempted-retries",
      "x-litellm-attempted-fallbacks", "x-litellm-response-cost", "x-litellm-version")


def counts():
    return {n: m.count for n, m in mocks.items() if m.count}


def reset(wait=0):
    for m in mocks.values():
        m.reset()
    open(f"{WORK}/timeline.jsonl", "w").close()
    if wait:
        time.sleep(wait)


def chat(model, extra_headers=None, key=None, body_extra=None):
    h = dict(H if key is None else {"Authorization": f"Bearer {key}"})
    h.update(extra_headers or {})
    body = {"model": model, "messages": [{"role": "user", "content": "Grüezi"}]}
    body.update(body_extra or {})
    t0 = time.time()
    r = c.post("/v1/chat/completions", headers=h, json=body)
    dt = time.time() - t0
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:300]}
    return r.status_code, {k: r.headers.get(k) for k in RH if r.headers.get(k) is not None}, \
        (j.get("model") if isinstance(j, dict) else None), (j.get("error", {}) or {}).get("message", "")[:200] if isinstance(j, dict) and "error" in j else None, round(dt, 2)


def timeline():
    try:
        return [json.loads(l) for l in open(f"{WORK}/timeline.jsonl") if l.strip()]
    except FileNotFoundError:
        return []


def show_timeline(max_rows=40):
    for e in timeline()[:max_rows]:
        keep = {k: v for k, v in e.items() if v not in (None, {}, []) and k != "t"}
        log("     TL", json.dumps(keep, default=str)[:900])


# T1: normal request, OpenWebUI + Zuplo subscription headers (custom_auth + lago path)
reset()
st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b",
                               {"X-OpenWebUI-User-Id": "owui-user-1", "x-zuplo-subscription-id": "sub-123"})
time.sleep(2)
log(f"T1 normal apertus-v1.5-70b: status={st} model={model} err={err} dt={dt}\n   headers={hdr}\n   mock_counts={counts()}")
log(f"   lago_events={json.dumps(lago_events)}")
show_timeline()

# T2: load balancing between the two deployments of apertus-v1.5-70b (infomaniak=CH, featherless=?)
reset()
dist = {}
for i in range(20):
    st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b")
    dist[hdr.get("x-litellm-model-api-base")] = dist.get(hdr.get("x-litellm-model-api-base"), 0) + 1
log(f"T2 20 requests to apertus-v1.5-70b (both up): by api_base={dist} mock_counts={counts()}")

# T3: both apertus-v1.5-70b deployments down -> retries + fallback chain from the Utility config
reset(wait=6)
mocks["infomaniak"].mode = "down"
mocks["featherless"].mode = "down"
st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b")
time.sleep(2)
log(f"T3 apertus-v1.5-70b both deployments 503: status={st} model={model} err={err} dt={dt}\n   headers={hdr}\n   mock_counts={counts()}")
show_timeline()

# T4: whole chain down (apertus both + sealion + plgrid) -> final error; how many requests hit each host
reset(wait=6)
for n in ("infomaniak", "featherless", "sealion", "plgrid"):
    mocks[n].mode = "down"
st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b")
time.sleep(2)
log(f"T4 entire fallback chain 503: status={st} err={err} dt={dt}\n   headers={hdr}\n   mock_counts={counts()}")

# T5: effective cooldown_time (config says litellm_settings.cooldown_time: 30)
reset(wait=6)
mocks["infomaniak"].mode = "down"
mocks["featherless"].mode = "down"
chat("swiss-ai/apertus-v1.5-70b")  # puts both apertus deployments into cooldown
t_fail = time.time()
for m in ("infomaniak", "featherless"):
    mocks[m].mode = "up"
before = counts()
probe_at = {}
for t in (1, 7, 12, 20):
    time.sleep(max(0, t_fail + t - time.time()))
    st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b")
    probe_at[t] = (hdr.get("x-litellm-model-api-base"), model)
log(f"T5 cooldown probe after both apertus lanes failed then recovered: counts_after_fail={before} "
    f"served_by_at_seconds_after_failure={probe_at}")

# T6: auth - wrong key (custom_auth auto mode must NOT grant access); no-DB behaviour of /customer/info
reset(wait=6)
st, hdr, model, err, dt = chat("swiss-ai/apertus-v1.5-70b", {"X-OpenWebUI-User-Id": "owui-user-2"}, key="sk-not-a-real-key")
log(f"T6 wrong key + OpenWebUI header: status={st} err={err} mock_counts={counts()}")
r = c.get("/customer/info", headers=H, params={"end_user_id": "owui-user-1"})
log(f"T6b GET /customer/info without DB: status={r.status_code} body={r.text[:200]}")

# T7: model metadata as exposed by the proxy API
r = c.get("/v1/model/info", headers=H)
for d in r.json().get("data", []):
    if d["model_name"] == "swiss-ai/apertus-v1.5-70b":
        mi = d.get("model_info", {})
        log("T7 /v1/model/info apertus-v1.5-70b: id=", mi.get("id"), "api_base=", d.get("litellm_params", {}).get("api_base"),
            "custom=", {k: mi.get(k) for k in ("hosting_provider", "datacenter_country", "jurisdiction")},
            "tags=", d.get("litellm_params", {}).get("tags"), "input_cost_per_token=", repr(mi.get("input_cost_per_token")))
r = c.get("/v1/models", headers=H)
log("T7b /v1/models ids:", [m["id"] for m in r.json().get("data", [])])

proc.terminate()
proc.wait(timeout=20)
plog.close()
pl = open(f"{WORK}/proxy.log").read()
for pat in ("Customer", "customer", "LagoCustomCallback", "Lago", "custom_auth", "Error checking", "Traceback",
            "not a valid argument", "Ignoring this key"):
    hits = [l for l in pl.splitlines() if pat in l]
    if hits:
        log(f"   proxy.log '{pat}': {len(hits)} lines, e.g. {hits[0][:220]!r}")
log("== DONE")
