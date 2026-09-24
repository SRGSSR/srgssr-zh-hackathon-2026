"""EXP4: (a) tag routing widening by the client, (b) non-chat routes / admin routes with a commune key,
(c) hardened config.  Run: cd lab && ./run.sh proxy/exp4_routes_tags_hardening.py
"""
import copy
import json
import time

import httpx

from harness import BASE_CONFIG, MASTER, MOCK_PORTS, PROXY, Proxy
from mock_sse import start_mocks

mocks = start_mocks(MOCK_PORTS)


def req(method, path, key, body=None, timeout=20):
    r = httpx.request(method, f"{PROXY}{path}", headers={"Authorization": f"Bearer {key}"}, json=body,
                      timeout=timeout)
    try:
        j = r.json()
    except Exception:
        j = r.text[:200]
    return r.status_code, j


def short(j, n=200):
    return json.dumps(j, default=str)[:n]


# ---------------------------------------------------------------------------------------------
# (a) TAG ROUTING: server-side key tag "ch"; can the client add/negate tags to reach "sg"?
for match_any in (True, False):
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["router_settings"]["enable_tag_filtering"] = True
    cfg["router_settings"]["tag_filtering_match_any"] = match_any
    with Proxy(f"exp4tags_{match_any}", config=cfg, env={"PROBE_ENFORCE": "0"}, mocks=mocks) as p:
        print(f"\n##### (a) tag routing enable_tag_filtering=true match_any={match_any}; key sk-commune-t tags=[ch]")
        for label, body, headers in [
            ("no client tags", None, None),
            ("body tags=[sg]", {"tags": ["sg"]}, None),
            ("header x-litellm-tags: sg", None, {"x-litellm-tags": "sg"}),
            ("body metadata.tags=[sg]", {"metadata": {"tags": ["sg"]}}, None),
            ("body tags=[!ch]", {"tags": ["!ch"]}, None),
        ]:
            p.reset()
            st = []
            for _ in range(8):
                r = p.chat("sk-commune-t", model="mixed", body=body, headers=headers)
                st.append(r.status)
            err = r.error()
            print(f"  {label:28s} statuses={sorted(set(st))} counts={p.counts()} "
                  f"err={(err[0][:120] if err else '')!r}")

# ---------------------------------------------------------------------------------------------
# (b) ROUTES with a commune key (config A = Utility-like, and C = with policy hooks)
for label, env in (("A", {"PROBE_ENFORCE": "0"}), ("C", {"PROBE_ENFORCE": "1"})):
    with Proxy(f"exp4routes{label}", env=env, mocks=mocks) as p:
        print(f"\n##### (b) routes, config {label}, key sk-commune-a (models=[apertus-ch])")
        K = "sk-commune-a"
        tests = [
            ("GET", "/health", None),
            ("GET", "/health/readiness", None),
            ("GET", "/v1/models", None),
            ("GET", "/v1/model/info", None),
            ("POST", "/model/new", {"model_name": "apertus-ch", "litellm_params": {
                "model": "openai/evil", "api_base": "http://127.0.0.1:9103/v1", "api_key": "x"},
                "model_info": {"id": "evil-1", "jurisdiction": "CH"}}),
            ("POST", "/v1/responses", {"model": "sealion-sg", "input": "Bürgeranfrage"}),
            ("POST", "/v1/completions", {"model": "sealion-sg", "prompt": "Bürgeranfrage"}),
            ("POST", "/v1/messages", {"model": "sealion-sg", "max_tokens": 10,
                                      "messages": [{"role": "user", "content": "Bürgeranfrage"}]}),
            ("POST", "/v1/embeddings", {"model": "sealion-sg", "input": "Bürgeranfrage"}),
            ("POST", "/openai/deployments/sealion-sg/chat/completions",
             {"messages": [{"role": "user", "content": "Bürgeranfrage"}]}),
            ("POST", "/engines/sealion-sg/chat/completions",
             {"messages": [{"role": "user", "content": "Bürgeranfrage"}]}),
        ]
        for method, path, body in tests:
            p.reset()
            st, j = req(method, path, K, body)
            time.sleep(0.5)
            print(f"  {method} {path:48s} -> {st} counts={p.counts()} other={p.other_paths()} body={short(j, 160)!r}")
        p.reset()
        st, j = req("GET", "/health", MASTER, timeout=60)
        print(f"  [master] GET /health -> {st} counts={p.counts()} (health checks call EVERY deployment)")
        p.reset()
        st, j = req("GET", "/v1/model/info", MASTER)
        print(f"  [master] GET /v1/model/info -> {st} n={len(j.get('data', [])) if isinstance(j, dict) else j}")

# ---------------------------------------------------------------------------------------------
# (c) HARDENED: common checks on custom auth + policy filter + pre-send guard + request guard + failure map
hcfg = copy.deepcopy(BASE_CONFIG)
hcfg["general_settings"]["custom_auth_run_common_checks"] = True
hcfg["litellm_settings"]["enable_post_custom_auth_checks"] = True
henv = {"PROBE_ENFORCE": "1", "PROBE_GUARD": "1", "PROBE_MAP_FAILURE": "1"}
with Proxy("exp4H", config=hcfg, env=henv, mocks=mocks) as p:
    print("\n##### (c) hardened config, key sk-commune-a")
    K = "sk-commune-a"
    CH_DOWN = {"mock-ch-1": "down", "mock-ch-2": "down"}
    cases = [
        ("normal", {}, None, "apertus-ch", None),
        ("CH down -> server fallback sg must be blocked", {}, None, "apertus-ch", CH_DOWN),
        ("body api_key", {"api_key": "client-supplied-key"}, None, "apertus-ch", None),
        ("body fallbacks", {"fallbacks": ["sealion-sg"]}, None, "apertus-ch", CH_DOWN),
        ("router_settings_override", {"router_settings_override": {"fallbacks": [{"apertus-ch": ["bielik-pl"]}]}},
         None, "apertus-ch", CH_DOWN),
        ("body num_retries", {"num_retries": 9}, None, "apertus-ch", CH_DOWN),
        ("header x-litellm-num-retries", {}, {"x-litellm-num-retries": "9"}, "apertus-ch", CH_DOWN),
        ("header x-litellm-timeout", {}, {"x-litellm-timeout": "0.001"}, "apertus-ch", None),
        ("body timeout", {"timeout": 0.001}, None, "apertus-ch", None),
        ("model=deployment id sg-1", {}, None, "sg-1", None),
        ("model=apertus-ch,sealion-sg", {}, None, "apertus-ch,sealion-sg", None),
        ("model=openai/sealion-sg-upstream", {}, None, "openai/sealion-sg-upstream", None),
        ("metadata spoof", {"metadata": {"user_api_key_metadata": {"allowed_jurisdictions": ["SG"]}}}, None,
         "sealion-sg", None),
        ("streaming, CH down", {"stream": True}, None, "apertus-ch", CH_DOWN),
    ]
    for label, body, headers, model, modes in cases:
        p.reset()
        for mname, mode in (modes or {}).items():
            mocks[mname].mode = mode
        body = dict(body)
        stream = body.pop("stream", False)
        r = p.chat(K, body=body, headers=headers, model=model, stream=stream)
        err = r.error() if not stream else ((r.content() or "")[:150],)
        print(f"  {label:48s} -> {r.status} counts={p.counts()} model-id={r.headers.get('x-litellm-model-id')} "
              f"err={(err[0][:150] if err else '')!r}")
    st, j = req("GET", "/health", K)
    print(f"  GET /health with commune key -> {st} {short(j, 150)!r}")
    st, j = req("POST", "/v1/responses", K, {"model": "sealion-sg", "input": "x"})
    print(f"  POST /v1/responses sealion-sg -> {st} {short(j, 150)!r}")
    st, j = req("GET", "/v1/models", K)
    print(f"  GET /v1/models -> {st} {short(j, 200)!r}")
