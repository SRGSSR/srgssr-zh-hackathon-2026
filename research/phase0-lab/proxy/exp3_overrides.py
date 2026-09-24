"""EXP3: request-side override vectors sent with the commune key. For each: which mock gets traffic,
and what do the router-level hooks see (did client-supplied metadata survive?).

Config A = Utility-like, no enforcement (raw LiteLLM behaviour)
Config C = same + probe policy enforcement (PROBE_ENFORCE=1)
Run: cd lab && ./run.sh proxy/exp3_overrides.py [A|C]
"""
import json
import sys
import time

import httpx

from harness import MASTER, MOCK_PORTS, PROXY, Proxy
from mock_sse import start_mocks

SPOOF = {
    "user_api_key_metadata": {"policy_id": "none", "allowed_jurisdictions": ["CH", "SG", "EU", None]},
    "user_api_key_team_metadata": {"policy_id": "none"},
    "user_api_key_alias": "admin",
    "user_api_key_team_id": "team-admin",
    "allowed_jurisdictions": ["SG"],
    "policy_id": "none",
    "tags": ["sg"],
    "model_info": {"id": "ch-1", "jurisdiction": "CH"},
}
CH_DOWN = {"mock-ch-1": "down", "mock-ch-2": "down"}

VECTORS = [
    ("V01 baseline", dict()),
    ("V02 body metadata spoof (user_api_key_*, tags, model_info) + model=sealion-sg",
     dict(model="sealion-sg", body={"metadata": SPOOF})),
    ("V03 litellm_metadata spoof + model=sealion-sg", dict(model="sealion-sg", body={"litellm_metadata": SPOOF})),
    ("V04 metadata as JSON string spoof + model=sealion-sg",
     dict(model="sealion-sg", body={"metadata": json.dumps(SPOOF)})),
    ("V05 top-level tags=[sg] model=mixed x6", dict(model="mixed", body={"tags": ["sg"]}, repeat=6)),
    ("V06 header x-litellm-tags: sg model=mixed x6", dict(model="mixed", headers={"x-litellm-tags": "sg"}, repeat=6)),
    ("V07 body fallbacks=[sealion-sg], CH down", dict(body={"fallbacks": ["sealion-sg"]}, modes=CH_DOWN)),
    ("V08 body router_settings_override.fallbacks, CH down",
     dict(body={"router_settings_override": {"fallbacks": [{"apertus-ch": ["bielik-pl"]}]}}, modes=CH_DOWN)),
    ("V09 body api_base -> sg mock", dict(body={"api_base": "http://127.0.0.1:9103/v1"})),
    ("V10 body base_url -> sg mock", dict(body={"base_url": "http://127.0.0.1:9103/v1"})),
    ("V11 body api_key only (clientside credential)", dict(body={"api_key": "client-supplied-key"})),
    ("V12 model = deployment id 'sg-1'", dict(model="sg-1")),
    ("V13 model = litellm_params.model 'openai/sealion-sg-upstream'", dict(model="openai/sealion-sg-upstream")),
    ("V14 model = unlisted 'openai/gpt-x'", dict(model="openai/gpt-x")),
    ("V15 model = 'apertus-ch,sealion-sg' (comma -> batch completion)", dict(model="apertus-ch,sealion-sg")),
    ("V16 mock_response", dict(body={"mock_response": "FAKE"})),
    ("V17 mock_testing_fallbacks=true (all up)", dict(body={"mock_testing_fallbacks": True})),
    ("V18 disable_fallbacks=true, CH down", dict(body={"disable_fallbacks": True}, modes=CH_DOWN)),
    ("V19 body num_retries=4, CH down", dict(body={"num_retries": 4}, modes=CH_DOWN)),
    ("V20 header x-litellm-num-retries: 4, CH down", dict(headers={"x-litellm-num-retries": "4"}, modes=CH_DOWN)),
    ("V21 top-level model_info spoof + model=sealion-sg",
     dict(model="sealion-sg", body={"model_info": {"id": "ch-1", "jurisdiction": "CH"}})),
    ("V22 header x-litellm-timeout: 0.001 (all up)", dict(headers={"x-litellm-timeout": "0.001"})),
    ("V23 user_config with own model_list",
     dict(body={"user_config": {"model_list": [{"model_name": "apertus-ch", "litellm_params": {
         "model": "openai/x", "api_base": "http://127.0.0.1:9103/v1", "api_key": "x"}}]}})),
    ("V24 extra_body.api_base", dict(body={"extra_body": {"api_base": "http://127.0.0.1:9103/v1"}})),
    ("V25 body timeout=0.001 (all up)", dict(body={"timeout": 0.001})),
    ("V26 specific_deployment=true + model=sealion-sg-upstream name",
     dict(model="sealion-sg", body={"specific_deployment": True})),
]


def model_count():
    r = httpx.get(f"{PROXY}/v1/model/info", headers={"Authorization": f"Bearer {MASTER}"}, timeout=10)
    try:
        return len(r.json()["data"])
    except Exception:
        return f"? {r.status_code}"


def run(label, key="sk-commune-a"):
    env = {"PROBE_ENFORCE": "1" if label == "C" else "0"}
    mocks = start_mocks(MOCK_PORTS)
    with Proxy(f"exp3{label}", env=env, mocks=mocks) as p:
        print(f"\n################ CONFIG {label}  key={key}  deployments={model_count()}")
        for name, spec in VECTORS:
            p.reset()
            for mname, mode in (spec.get("modes") or {}).items():
                mocks[mname].mode = mode
            results = []
            for _ in range(spec.get("repeat", 1)):
                r = p.chat(key, body=spec.get("body"), headers=spec.get("headers"),
                           model=spec.get("model", "apertus-ch"))
                results.append(r)
            r = results[-1]
            err = r.error()
            print(f"\n--- {name}")
            print(f"    status={[x.status for x in results]} counts={p.counts()} "
                  f"model-id={r.headers.get('x-litellm-model-id')} group={r.headers.get('x-litellm-model-group')} "
                  f"body.model={r.model()!r} content={r.content()!r}")
            if err:
                print(f"    error={err[0][:230]!r} code={err[2]}")
            time.sleep(0.6)
            recs = p.probe()
            f = next((x for x in recs if x["hook"] == "async_filter_deployments"), None)
            if f:
                md = f["meta"]
                print(f"    [filter] model={f['model']} in={f['in_ids']} out={f['out_ids']} "
                      f"policy(user_api_key_metadata)={f['policy']} tags={md.get('tags')} "
                      f"alias={md.get('user_api_key_alias')} team={md.get('user_api_key_team_id')} "
                      f"md.allowed_jurisdictions={md.get('allowed_jurisdictions')} md.policy_id={md.get('policy_id')}")
                if f["top"]:
                    print(f"    [filter] top-level kwargs: {json.dumps(f['top'], default=str)[:300]}")
            else:
                print("    [filter] async_filter_deployments NOT called")
            for d in (x for x in recs if x["hook"] == "async_pre_call_deployment_hook"):
                print(f"    [pre_send] dep={d['deployment_id']} jur={d['jurisdiction']} api_base={d['api_base']} "
                      f"decision={d['decision']} kw.model_info={d['top'].get('model_info')} "
                      f"kw.api_key={d['top'].get('api_key')} num_retries={d['top'].get('num_retries')}")
            for h in (x for x in recs if x["hook"] == "async_post_call_response_headers_hook"):
                ci = h.get("litellm_call_info") or {}
                print(f"    [resp_headers_hook] litellm_call_info.model_id={ci.get('model_id')} "
                      f"model_info={ci.get('model_info')}")
            for mname, m in mocks.items():
                for q in m.requests:
                    auth = q["headers"].get("authorization", "")
                    print(f"    [{mname}] got model={q['body'].get('model')} auth={auth[:22]!r} "
                          f"extra_keys={sorted(set(q['body']) - {'model', 'messages', 'stream'})}")
        print(f"\n    deployments after all vectors: {model_count()}")


if __name__ == "__main__":
    for label in (sys.argv[1:] or ["A", "C"]):
        run(label)
