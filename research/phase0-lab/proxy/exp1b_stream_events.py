"""EXP1b: mid-stream failures + which logging events fire per attempt (for the per-attempt timeline).
Policy enforcement OFF.  Run: cd lab && ./run.sh proxy/exp1b_stream_events.py
"""
import json
import time

from harness import Proxy, show

K = "sk-commune-b"


def dump(p, wait=2.0):
    time.sleep(wait)
    for rec in p.probe():
        keep = {k: rec.get(k) for k in ("deployment_id", "jurisdiction", "decision", "model_id", "model_info_id",
                                        "api_base", "original_model_group", "exception", "in_ids", "out_ids",
                                        "response_model", "litellm_call_id") if rec.get(k) not in (None, "", [])}
        if "exception" in keep:
            keep["exception"] = keep["exception"][:110]
        if "litellm_call_id" in keep:
            keep["litellm_call_id"] = keep["litellm_call_id"][:8]
        print("   probe:", rec["hook"], json.dumps(keep, default=str))


with Proxy("exp1b", env={"PROBE_ENFORCE": "0"}) as p:
    M = p.mocks

    p.reset()
    M["mock-ch-1"].mode = "midstream"
    M["mock-ch-2"].mode = "midstream"
    r = p.chat(K, stream=True)
    show("1g' streaming, CH drops the TCP stream after 2 chunks", r, p)
    dump(p)

    p.reset()
    M["mock-ch-1"].mode = "midstream_err"
    M["mock-ch-2"].mode = "midstream_err"
    r = p.chat(K, stream=True)
    show("1j streaming, CH sends in-band SSE error after 2 chunks -> mid-stream fallback?", r, p)
    for q in M["mock-sg-1"].requests:
        print("   sg-1 received messages:", json.dumps(q["body"].get("messages"), ensure_ascii=False))
    dump(p)

    p.reset()
    M["mock-ch-1"].mode = "down"
    M["mock-ch-2"].mode = "down"
    r = p.chat(K)
    show("1c' both CH down -> fallback sg (full event dump, 2s wait)", r, p)
    dump(p)

    p.reset()
    for m in M.values():
        m.mode = "down"
    r = p.chat(K)
    show("1d' all down (full event dump)", r, p)
    dump(p)
