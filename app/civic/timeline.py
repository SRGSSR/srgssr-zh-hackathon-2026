"""Turns raw gateway + app events into timeline rows for the citizen and the jury."""

import datetime as dt
from typing import Dict, List

KIND_LABEL = {"real": "REAL", "simulated": "SIMULATED"}


def _t(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]


def _ep(e: Dict, eps: Dict) -> Dict:
    info = eps.get(e.get("deployment_id") or "", {})
    return {
        "id": e.get("deployment_id"),
        "provider": e.get("provider") or info.get("provider"),
        "jurisdiction": e.get("jurisdiction") or info.get("jurisdiction"),
        "kind": KIND_LABEL.get(e.get("endpoint_kind") or info.get("kind"), "?"),
    }


def rows(events: List[Dict], eps: Dict) -> List[Dict]:
    out = []
    last_empty_group = None
    for e in events:
        t, typ = e.get("type"), _t(e["ts"])
        # LiteLLM retries an exhausted group a few times; show "nothing approved left" once per group
        if t == "routing_decision" and not e.get("selected"):
            if last_empty_group == e.get("model_group"):
                continue
            last_empty_group = e.get("model_group")
        elif t in ("routing_decision", "job_started", "job_resumed"):
            last_empty_group = None
        row = {"ts": typ, "type": t, "tone": "info", "title": t, "detail": "", "entries": []}
        if t == "job_created":
            row.update(title="Letter received and stored locally", detail=f"Output language: {e.get('language')}")
        elif t in ("job_started", "job_resumed"):
            row.update(title="Job resumed" if t == "job_resumed" else "Job started", detail=f"Run {e.get('run')}",
                       tone="info" if t == "job_started" else "good")
        elif t == "request_accepted":
            row.update(title=f"Rule applied: {e.get('policy_id')}", detail=f"Bound to API key '{e.get('key_alias')}', not to the request. {e.get('rule') or ''}")
        elif t == "request_rejected":
            row.update(title="Request rejected by the routing policy", tone="bad", entries=e.get("reasons") or [])
        elif t == "routing_decision":
            sel = e.get("selected")
            row.update(
                title=f"Attempt {e.get('attempt')} · {e.get('model_group')}: " + (f"selected {sel}" if sel else "no approved endpoint left"),
                tone="info" if sel else "warn",
            )
            for ev in e.get("evaluated") or []:
                dec = ev.get("decision")
                label = {"selected": "selected", "standby": "standby", "blocked_before_send": "blocked before send"}.get(dec, dec)
                row["entries"].append(
                    {
                        "text": f"{ev.get('deployment_id')} ({KIND_LABEL.get(ev.get('endpoint_kind'), '?')}, jurisdiction {ev.get('jurisdiction') or '—'})",
                        "tag": label,
                        "tone": {"selected": "good", "standby": "muted", "blocked_before_send": "bad"}.get(dec, "muted"),
                        "reason": ev.get("reason"),
                    }
                )
        elif t == "dispatch":
            ep = _ep(e, eps)
            row.update(title=f"Sent to {ep['id']}", detail=f"{ep['provider']} · jurisdiction {ep['jurisdiction']} · {ep['kind']} endpoint", tone="send")
        elif t == "send_vetoed":
            row.update(title=f"Send vetoed at the last check: {e.get('deployment_id')}", detail=e.get("reason", ""), tone="bad")
        elif t == "attempt_result":
            o = e.get("outcome")
            ep = _ep(e, eps)
            if o == "success":
                row.update(title=f"Answer from {ep['id']}", detail=f"Model reported by the endpoint: {e.get('model_returned')}", tone="good")
            elif o == "timeout":
                row.update(title=f"{ep['id']}: data received, no response", detail=e.get("meaning", ""), tone="warn")
            elif o == "connection_failed":
                row.update(title=f"{ep['id']}: connection failed", detail=e.get("meaning", ""), tone="warn")
            elif o == "error":
                row.update(title=f"{ep['id']}: error {e.get('status_code') or ''}".strip(), detail=e.get("meaning", ""), tone="warn")
            elif o in ("no_deployment", "rejected", "blocked"):
                continue  # already shown by routing_decision / request_rejected
            else:
                row.update(title=f"Attempt outcome: {o}", detail=e.get("meaning", ""))
        elif t == "output_invalid_retrying":
            row.update(title="Answer was not valid JSON, asking once more", detail=e.get("error", "")[:200], tone="warn")
        elif t == "job_waiting":
            row.update(
                title="Waiting: no approved endpoint available",
                detail=f"Job kept in the local database, nothing sent elsewhere. Next try in {int(e.get('retry_in_s', 0))} s.",
                tone="warn",
            )
        elif t == "job_resumed_after_restart":
            row.update(title="Job recovered after a restart", tone="good")
        elif t == "job_done":
            row.update(title="Done", detail=f"Answered by {e.get('deployment_id')} ({e.get('llm_calls')} model call(s))", tone="good")
        elif t == "job_cancelled":
            row.update(title="Cancelled by the user", tone="muted")
        elif t == "job_failed":
            row.update(title="Failed", detail=e.get("error", "")[:300], tone="bad")
        out.append(row)
    return out


def summary(events: List[Dict]) -> Dict:
    sent, blocked, received_no_answer = set(), set(), set()
    for e in events:
        if e.get("type") == "dispatch":
            sent.add(e.get("deployment_id"))
        elif e.get("type") == "routing_decision":
            for ev in e.get("evaluated") or []:
                if ev.get("decision") == "blocked_before_send":
                    blocked.add(ev.get("deployment_id"))
        elif e.get("type") == "attempt_result" and e.get("outcome") == "timeout":
            received_no_answer.add(e.get("deployment_id"))
    return {"sent_to": sorted(x for x in sent if x), "blocked": sorted(x for x in blocked if x), "timeouts": sorted(x for x in received_no_answer if x)}
