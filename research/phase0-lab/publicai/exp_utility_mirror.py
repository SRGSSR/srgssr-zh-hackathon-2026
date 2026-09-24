"""Experiment: what a Public AI API client can / cannot observe, reproduced on the pinned image.

Mirrors the Utility's swiss-ai/apertus-v1.5-70b model group (two deployments: Infomaniak + Featherless,
same upstream model id) and its cross-model fallback chain (-> aisingapore/Qwen-SEA-LION-v4-32B-IT ->
speakleash/Bielik-11B-v3.0-Instruct), with drop_params: true exactly like templates/configmap.yaml.
All upstreams are local mocks. No real provider is called.

Questions answered:
  Q1  GET /v1/models without auth on a LiteLLM proxy with master_key -> status?
  Q2  Is response_format {"type":"json_object"} forwarded to an openai/ deployment when drop_params=true?
  Q3  Is response_format {"type":"json_schema",...} forwarded unchanged?
  Q4  Which response headers / body fields reveal the serving deployment (api_base, model id, model)?
  Q5  When both Apertus deployments fail, does the proxy silently answer from the SEA-LION group,
      and what does the client see (status, body.model, x-litellm-attempted-fallbacks, api_base header)?
  Q6  Deployment-level litellm_params (temperature/top_p/max_tokens) vs client-provided values: which is sent?

Run: cd lab && ./run.sh publicai/exp_utility_mirror.py
"""
import json
import os
import subprocess
import sys
import time

import httpx
import yaml

sys.path.insert(0, "/lab")
from mock_openai import start_mocks  # noqa: E402

HERE = "/lab/publicai"
PROXY = "http://127.0.0.1:4000"
MASTER = "sk-master-local-test"

PORTS = {"infomaniak": 9201, "featherless": 9202, "sealion": 9203, "bielik": 9204}


def dep(group, upstream_model, port, dep_id, extra=None):
    lp = {
        "model": f"openai/{upstream_model}",
        "api_base": f"http://127.0.0.1:{port}/v1",
        "api_key": f"k-{dep_id}",
    }
    lp.update(extra or {})
    return {"model_name": group, "litellm_params": lp, "model_info": {"id": dep_id}}


APERTUS_PARAMS = {"supports_vision": True, "weight": 1, "temperature": 0.8, "top_p": 0.9, "max_tokens": 8192}

CONFIG = {
    "model_list": [
        dep("swiss-ai/apertus-v1.5-70b", "swiss-ai/Apertus-v1.5-70B", PORTS["infomaniak"], "infomaniak-70b", APERTUS_PARAMS),
        dep("swiss-ai/apertus-v1.5-70b", "swiss-ai/Apertus-v1.5-70B", PORTS["featherless"], "featherless-70b", APERTUS_PARAMS),
        dep("aisingapore/Qwen-SEA-LION-v4-32B-IT", "aisingapore/Qwen-SEA-LION-v4-32B-IT", PORTS["sealion"], "sealion-32b"),
        dep("speakleash/Bielik-11B-v3.0-Instruct", "speakleash/Bielik-11B-v3.0-Instruct", PORTS["bielik"], "bielik-11b"),
    ],
    "router_settings": {
        "routing_strategy": "latency-based-routing",  # Utility values.yaml router.routingStrategy
        "fallbacks": [
            {"swiss-ai/apertus-v1.5-70b": ["aisingapore/Qwen-SEA-LION-v4-32B-IT", "speakleash/Bielik-11B-v3.0-Instruct"]}
        ],
    },
    "litellm_settings": {
        "num_retries": 1,  # Utility uses 5; 1 keeps the run short, semantics identical
        "allowed_fails": 1,
        "cooldown_time": 30,
        "drop_params": True,  # Utility configmap.yaml
        "request_timeout": 5,
    },
    "general_settings": {"master_key": MASTER},
}


def wait_ready(proc, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"proxy exited with {proc.returncode}")
        try:
            if httpx.get(f"{PROXY}/health/liveliness", timeout=2).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("proxy not ready")


def chat(body, auth=True):
    h = {"Content-Type": "application/json", "User-Agent": "exp/1.0"}
    if auth:
        h["Authorization"] = f"Bearer {MASTER}"
    r = httpx.post(f"{PROXY}/v1/chat/completions", json=body, headers=h, timeout=60)
    hdrs = {k: v for k, v in r.headers.items() if k.startswith("x-litellm")}
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:500]}
    return r.status_code, hdrs, j


def last_body(m):
    return m.requests[-1]["body"] if m.requests else None


def main():
    mocks = start_mocks({n: p for n, p in PORTS.items()})
    cfg_path = f"{HERE}/config_utility_mirror.yaml"
    with open(cfg_path, "w") as f:
        yaml.safe_dump(CONFIG, f, sort_keys=False)
    log = open(f"{HERE}/proxy_utility_mirror.log", "w")
    proc = subprocess.Popen(
        ["litellm", "--config", cfg_path, "--port", "4000", "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "LITELLM_LOG": "ERROR"},
    )
    results = {}
    try:
        wait_ready(proc)

        # Q1
        r = httpx.get(f"{PROXY}/v1/models", headers={"User-Agent": "exp/1.0"}, timeout=10)
        results["Q1_models_noauth"] = {"status": r.status_code, "body": r.text[:300]}
        r = httpx.get(f"{PROXY}/v1/models", headers={"Authorization": f"Bearer {MASTER}"}, timeout=10)
        results["Q1_models_auth"] = {"status": r.status_code, "ids": [d["id"] for d in r.json().get("data", [])]}

        msgs = [{"role": "user", "content": "Reply with JSON {\"ok\": true}"}]

        # Q2 json_object
        for m in mocks.values():
            m.reset()
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs,
                          "response_format": {"type": "json_object"}})
        served = [n for n, m in mocks.items() if m.count]
        b = last_body(mocks[served[0]]) if served else None
        results["Q2_json_object"] = {
            "status": st, "served_by": served,
            "upstream_received_response_format": (b or {}).get("response_format"),
            "upstream_body_keys": sorted((b or {}).keys()),
        }

        # Q3 json_schema
        schema_rf = {"type": "json_schema", "json_schema": {"name": "ok", "strict": True, "schema": {
            "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
            "additionalProperties": False}}}
        for m in mocks.values():
            m.reset()
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs, "response_format": schema_rf})
        served = [n for n, m in mocks.items() if m.count]
        b = last_body(mocks[served[0]]) if served else None
        results["Q3_json_schema"] = {
            "status": st, "served_by": served,
            "forwarded_unchanged": (b or {}).get("response_format") == schema_rf,
            "upstream_received_response_format": (b or {}).get("response_format"),
        }

        # Q4 + Q6: headers/body on a normal success; deployment defaults vs client values
        for m in mocks.values():
            m.reset()
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs})
        served = [n for n, m in mocks.items() if m.count]
        b_default = last_body(mocks[served[0]]) if served else None
        results["Q4_success_visibility"] = {
            "status": st, "served_by": served, "body_model": j.get("model"),
            "x_litellm_headers": {k: hd.get(k) for k in (
                "x-litellm-model-api-base", "x-litellm-model-id", "x-litellm-model-group",
                "x-litellm-attempted-fallbacks", "x-litellm-attempted-retries", "x-litellm-version")},
        }
        for m in mocks.values():
            m.reset()
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs,
                          "temperature": 0.1, "max_tokens": 50})
        served = [n for n, m in mocks.items() if m.count]
        b_client = last_body(mocks[served[0]]) if served else None
        results["Q6_param_precedence"] = {
            "no_client_params_upstream_got": {k: (b_default or {}).get(k) for k in ("temperature", "top_p", "max_tokens")},
            "client_temp0.1_max50_upstream_got": {k: (b_client or {}).get(k) for k in ("temperature", "top_p", "max_tokens")},
        }

        # Q5 cross-model fallback when both Apertus deployments are down
        for m in mocks.values():
            m.reset()
        mocks["infomaniak"].mode = "down"
        mocks["featherless"].mode = "down"
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs,
                          "response_format": {"type": "json_object"}})
        results["Q5_cross_model_fallback"] = {
            "client_requested": "swiss-ai/apertus-v1.5-70b",
            "status": st,
            "body_model": j.get("model"),
            "content": (j.get("choices") or [{}])[0].get("message", {}).get("content"),
            "mock_counts": {n: m.count for n, m in mocks.items()},
            "x_litellm_headers": {k: hd.get(k) for k in (
                "x-litellm-model-api-base", "x-litellm-model-id", "x-litellm-model-group",
                "x-litellm-attempted-fallbacks", "x-litellm-attempted-retries")},
            "sealion_received_same_prompt": bool(mocks["sealion"].requests) and
            mocks["sealion"].requests[-1]["body"].get("messages") == msgs,
        }

        # Q7 client-side body param "disable_fallbacks": true (as an outbound caller of a
        # Utility-like proxy we could send it as defense-in-depth; NOT a policy mechanism)
        for m in mocks.values():
            m.reset()
        mocks["infomaniak"].mode = "down"
        mocks["featherless"].mode = "down"
        st, hd, j = chat({"model": "swiss-ai/apertus-v1.5-70b", "messages": msgs, "disable_fallbacks": True})
        results["Q7_client_disable_fallbacks"] = {
            "status": st,
            "error": (j.get("error") or {}).get("message", "")[:200] if isinstance(j, dict) else None,
            "mock_counts": {n: m.count for n, m in mocks.items()},
        }
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
    out = json.dumps(results, indent=1, default=str)
    print(out)
    open(f"{HERE}/exp_utility_mirror.out.json", "w").write(out)


if __name__ == "__main__":
    main()
