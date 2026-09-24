"""EXP2: DB-less policy binding via custom_auth. Is the key-level `models` allowlist enforced
(direct call, server-side router fallbacks, client-side fallbacks)? What do router hooks see?

Configs:
  A  = Utility-like: custom_auth + custom_auth_settings.mode=auto (nothing else)
  B  = A + general_settings.custom_auth_run_common_checks + litellm_settings.enable_post_custom_auth_checks
  C  = A + our probe policy enforcement (PROBE_ENFORCE=1: async_filter_deployments + pre_call_deployment_hook)
Run: cd lab && ./run.sh proxy/exp2_key_binding.py
"""
import copy
import json
import time

from harness import BASE_CONFIG, MOCK_PORTS, Proxy, show
from mock_sse import start_mocks

mocks = start_mocks(MOCK_PORTS)


def cfg_B():
    c = copy.deepcopy(BASE_CONFIG)
    c["general_settings"]["custom_auth_run_common_checks"] = True
    c["litellm_settings"]["enable_post_custom_auth_checks"] = True
    return c


def summary(p, r):
    return f"status={r.status} counts={p.counts()} model-id={r.headers.get('x-litellm-model-id')} " \
           f"group={r.headers.get('x-litellm-model-group')} err={(r.error() or ('',))[0][:140]!r}"


def battery(p, label, key="sk-commune-a"):
    print(f"\n##### config {label}, key {key}")
    M = p.mocks
    p.reset()
    r = p.chat(key)
    print("t1 normal apertus-ch          :", summary(p, r))
    if label == "A":
        time.sleep(1)
        for rec in p.probe():
            if rec["hook"] == "async_pre_call_hook":
                print("   [pre_call_hook] user_api_key_dict:", json.dumps(rec["uak"], default=str))
            if rec["hook"] in ("async_pre_call_hook", "async_pre_routing_hook", "async_filter_deployments",
                               "async_pre_call_deployment_hook"):
                print(f"   [{rec['hook']}] metadata:", json.dumps(rec["meta"], default=str)[:900])
    p.reset()
    r = p.chat(key, model="sealion-sg")
    print("t2 model=sealion-sg direct    :", summary(p, r))
    p.reset()
    r = p.chat(key, model="nometa")
    print("t2b model=nometa direct       :", summary(p, r))
    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(key)
    print("t3 CH down, server fallback sg:", summary(p, r))
    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(key, body={"fallbacks": ["bielik-pl"]})
    print("t4 CH down, body fallbacks pl :", summary(p, r))
    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(key, body={"disable_fallbacks": True})
    print("t5 CH down, disable_fallbacks :", summary(p, r))
    return r


with Proxy("exp2A", env={"PROBE_ENFORCE": "0"}, mocks=mocks) as p:
    battery(p, "A")
    battery(p, "A", key="sk-commune-b")
    p.reset()
    r = p.chat("sk-unknown-key")
    print("\nunknown key (falls through to LiteLLM auth, no DB):", r.status, r.error())

with Proxy("exp2B", config=cfg_B(), env={"PROBE_ENFORCE": "0"}, mocks=mocks) as p:
    battery(p, "B")
    battery(p, "B", key="sk-commune-b")

with Proxy("exp2C", env={"PROBE_ENFORCE": "1"}, mocks=mocks) as p:
    battery(p, "C")
    battery(p, "C", key="sk-commune-b")
    # show error headers + probe decisions for the all-approved-down case
    p.reset()
    mocks["mock-ch-1"].mode = "down"
    mocks["mock-ch-2"].mode = "down"
    r = p.chat("sk-commune-b")
    show("C: commune-b, both CH down, policy enforced", r, p)
    time.sleep(1)
    for rec in p.probe():
        if rec["hook"] in ("async_filter_deployments", "async_pre_call_deployment_hook", "log_failure_fallback_event",
                           "async_log_failure_event"):
            print("   ", rec["hook"], {k: rec.get(k) for k in ("model", "in_ids", "out_ids", "policy", "deployment_id",
                                                              "decision", "exception", "original_model_group")
                                       if rec.get(k) is not None})
    # master key has no policy -> unrestricted (shows that the policy is per key)
    p.reset()
    mocks["mock-ch-1"].mode = "down"
    mocks["mock-ch-2"].mode = "down"
    r = p.chat("sk-master")
    print("\nC: master key, CH down:", summary(p, r))
