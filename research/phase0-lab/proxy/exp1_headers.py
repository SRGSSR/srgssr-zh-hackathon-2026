"""EXP1: which response headers does the real proxy return (success / retry / fallback / error / streaming)?
Policy enforcement OFF (pure LiteLLM behaviour). Key: sk-commune-b (no models allowlist).
Run: cd lab && ./run.sh proxy/exp1_headers.py
"""
import json

from harness import Proxy, show

K = "sk-commune-b"

with Proxy("exp1", env={"PROBE_ENFORCE": "0"}) as p:
    M = p.mocks

    p.reset()
    r = p.chat(K)
    show("1a non-streaming success (all up)", r, p)
    print("ALL response header names:", sorted(r.headers.keys()))

    p.reset()
    M["mock-ch-1"].mode = "down"
    for i in range(3):
        r = p.chat(K)
        show(f"1b ch-1 down, ch-2 up (try {i})", r, p)

    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(K)
    show("1c both CH down -> router fallback to sealion-sg (NOT enforced)", r, p)
    for rec in p.probe():
        if rec["hook"] in ("async_pre_call_deployment_hook", "async_log_failure_event", "async_log_success_event",
                           "log_success_fallback_event", "async_post_call_response_headers_hook"):
            print("  probe:", rec["hook"], {k: rec.get(k) for k in ("deployment_id", "jurisdiction", "model_id",
                                                                       "litellm_call_id", "litellm_call_info",
                                                                       "original_model_group", "exception")
                                            if rec.get(k) is not None})

    p.reset()
    r = p.chat(K, body={"include_fallback_errors": True}) if False else None
    for m in M.values():
        m.mode = "down"
    r = p.chat(K)
    show("1d everything down -> error", r, p)
    print("ALL error header names:", sorted(r.headers.keys()))

    p.reset()
    r = p.chat(K, stream=True)
    show("1e streaming success", r, p)

    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(K, stream=True)
    show("1f streaming, both CH down before first byte -> fallback", r, p)

    p.reset()
    M["mock-ch-1"].mode = "midstream"
    M["mock-ch-2"].mode = "midstream"
    r = p.chat(K, stream=True)
    show("1g streaming, CH breaks MID-STREAM", r, p)
    print("  sg requests:", [q["body"].get("messages") for q in M["mock-sg-1"].requests])

    p.reset()
    M["mock-ch-1"].mode = "timeout"
    M["mock-ch-2"].mode = "timeout"
    r = p.chat(K)
    show("1h both CH time out AFTER receiving data (request_timeout=3) -> fallback", r, p)
    print("  ch-1 received:", M["mock-ch-1"].count, "ch-2 received:", M["mock-ch-2"].count)
    for rec in p.probe():
        if rec["hook"] in ("async_log_failure_event",):
            print("  probe failure:", rec.get("model_info_id"), rec.get("exception")[:160])

    p.reset()
    r = p.chat(K, body={"include_fallback_errors": True})
    show("1i include_fallback_errors=true, all up", r, p)
