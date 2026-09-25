"""Turns raw gateway and app events into the "journey of your letter": stops written for
the resident, with the technical detail kept separately for the jury."""

import datetime as dt
import os
from typing import Dict, List
from zoneinfo import ZoneInfo

from .endpoints import GROUPS, place


LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "Europe/Zurich"))


def _time(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%H:%M:%S")


def _name(dep_id, eps: Dict) -> str:
    return (eps.get(dep_id or "") or {}).get("name") or dep_id or "an unknown service"


def _reason(ev: Dict) -> str:
    if "missing metadata" in (ev.get("reason") or ""):
        return "its location is unknown"
    where = place(ev.get("jurisdiction"))
    return f"it is in {where}" if where else f"it is outside the rule ({ev.get('jurisdiction')})"


def _ruled_out_item(ev: Dict, eps: Dict) -> Dict:
    return {"id": ev.get("deployment_id"), "name": _name(ev.get("deployment_id"), eps), "reason": _reason(ev)}


RULE_TEXT = {
    "CH-only": "Only services in Switzerland may read your letter. Services whose location is unknown are never used.",
    "CH-then-EU": "Services in Switzerland first. If none can answer, services in the EU. Never anywhere else.",
    "CH-EU-then-consent": "Services in Switzerland first, then in the EU. Anywhere else only if you agree, for this letter.",
}
WAITING_FOR = {"CH-only": "a Swiss service", "CH-then-EU": "a service in Switzerland or the EU",
               "CH-EU-then-consent": "a service in Switzerland or the EU"}


def journey(events: List[Dict], eps: Dict) -> List[Dict]:
    stops: List[Dict] = []
    finished_by = {e.get("deployment_id") for e in events if e.get("type") == "job_done"}
    shown_ruled_out, shown_fallbacks = set(), set()
    primary_group, last_empty_group = None, None
    policy_id, consented = "CH-only", set()
    pending: List[Dict] = []

    for e in events:
        t = e.get("type")
        key = f"{e.get('_source')}:{e.get('gateway_job') or ''}:{e.get('_id') or e.get('ts')}:{t}"

        def add(kind, tone, title, text="", tech="", crossed=None):
            stops.append({"key": key, "kind": kind, "tone": tone, "title": title, "text": text, "tech": tech,
                          "crossed": crossed or [], "time": _time(e["ts"]), "ts": e["ts"]})

        if t == "letter_stored":
            stops.append({"key": "letter", "kind": "letter", "tone": "calm", "title": "Your letter arrived",
                          "text": "This service keeps it, in Switzerland.", "tech": f"language {e.get('language')}",
                          "crossed": [], "time": _time(e["ts"]), "ts": e["ts"]})
        elif t == "job_created":
            add("gateway", "calm", "Handed to the commune's gateway",
                "The gateway keeps it until a service allowed by the rule can answer.", f"deferred job {e.get('gateway_job')}")
        elif t == "request_accepted":
            policy_id = e.get("policy_id") or policy_id
            add("rule", "calm", "Your commune's rule applies", RULE_TEXT.get(policy_id, e.get("rule") or ""),
                f"policy {e.get('policy_id')}, bound to the key {e.get('key_alias')}")
        elif t == "consent_given":
            consented.update(e.get("jurisdictions") or [])
            where = " and ".join(place(j) or j for j in e.get("jurisdictions") or [])
            add("consent", "wait", f"You agreed to send this letter to a service in {where}",
                "For this letter only. Your agreement is recorded here.", (e.get("statement") or "")[:200])
        elif t == "routing_decision":
            group = e.get("model_group")
            primary_group = primary_group or group
            blocked = [ev for ev in e.get("evaluated") or [] if ev.get("decision") == "blocked_before_send"]
            if e.get("selected"):
                last_empty_group = None
                fresh = [ev for ev in blocked if ev.get("deployment_id") not in shown_ruled_out]
                shown_ruled_out.update(ev.get("deployment_id") for ev in fresh)
                pending = [_ruled_out_item(ev, eps) for ev in fresh]
            elif group != primary_group:
                if group in shown_fallbacks:
                    continue
                shown_fallbacks.add(group)
                where = sorted({place(ev.get("jurisdiction")) or "an unknown place" for ev in blocked})
                add("fallback", "bad", f"The backup plan wanted to use {GROUPS.get(group, group)}",
                    f"It runs in {', '.join(where)}. Your commune's rule does not allow that, so nothing was sent.",
                    f"LiteLLM fallback to the model group {group}, blocked before send",
                    [_ruled_out_item(ev, eps) for ev in blocked])
            else:
                if last_empty_group == group:
                    continue
                last_empty_group = group
                add("empty", "warn", "Every Swiss service has been tried" if policy_id == "CH-only"
                    else "Every service the rule allows has been tried", "None of them could answer just now.",
                    f"no allowed deployment left in {group}")
        elif t == "dispatch":
            dep = eps.get(e.get("deployment_id") or "", {})
            where = place(dep.get("jurisdiction") or e.get("jurisdiction"))
            kind = "A real service." if (e.get("endpoint_kind") or dep.get("kind")) == "real" else "A simulated service for this demo."
            if (dep.get("jurisdiction") or e.get("jurisdiction")) in consented:
                kind = "You agreed to this. " + kind
            add("sent", "send", f"Sent to {_name(e.get('deployment_id'), eps)}",
                f"In {where}. {kind}" if where else kind,
                f"{e.get('deployment_id')} at {e.get('api_base')}", pending)
            pending = []
        elif t == "send_vetoed":
            add("vetoed", "bad", f"Stopped at the last check before {_name(e.get('deployment_id'), eps)}",
                "Nothing was sent.", e.get("reason", ""))
        elif t == "attempt_result":
            name, outcome = _name(e.get("deployment_id"), eps), e.get("outcome")
            tech = " ".join(str(x) for x in (e.get("error_type"), e.get("status_code")) if x)
            if outcome == "success":
                if e.get("deployment_id") in finished_by:
                    continue  # the "ready" stop already says who wrote the answer
                add("answer", "good", f"{name} answered", "", f"model reported by the endpoint: {e.get('model_returned')}")
            elif outcome == "timeout":
                swiss = (eps.get(e.get("deployment_id") or "", {}).get("jurisdiction")) == "CH"
                add("noanswer", "warn", f"{name} received your letter but never answered",
                    "A copy may have reached it." + (" It is a Swiss service, so this is still within the rule." if swiss else ""),
                    tech)
            elif outcome == "connection_failed":
                add("problem", "warn", f"Could not reach {name}", "Nothing was received there.", tech)
            elif outcome == "error":
                add("problem", "warn", f"{name} did not work", "It received the request and answered with an error.", tech)
        elif t == "job_waiting":
            add("waiting", "wait", f"Waiting for {WAITING_FOR.get(policy_id, 'an allowed service')}",
                "Your letter stays here, in Switzerland, and is not sent anywhere else. "
                + (f"Next try in {int(e.get('retry_in_s', 0))} seconds." if int(e.get("retry_in_s", 0)) else "Trying again right away."),
                (e.get("gateway_error") or "")[:160])
        elif t in ("job_started", "job_resumed"):
            if t == "job_started" and (e.get("run") or 1) == 1:
                continue
            add("retry", "calm", "Trying again", "", f"run {e.get('run')}")
        elif t == "retry_requested":
            add("retry", "calm", "Trying again now, as you asked")
        elif t == "job_resumed_after_restart":
            add("restart", "calm", "The gateway restarted", "Your letter was still there, and the work continues.")
        elif t == "output_invalid_retrying":
            add("retry", "warn", "The answer was not in the right form, so we asked once more", "", (e.get("error") or "")[:160])
        elif t == "job_done":
            dep = eps.get(e.get("deployment_id") or "", {})
            where = place(dep.get("jurisdiction"))
            model = next((x.get("model_returned") for x in events if x.get("type") == "attempt_result"
                          and x.get("outcome") == "success" and x.get("deployment_id") == e.get("deployment_id")), None)
            add("done", "good", "Your explanation is ready",
                f"Written by {_name(e.get('deployment_id'), eps)}" + (f", in {where}." if where else "."),
                f"served by {e.get('deployment_id')}" + (f", model reported by the endpoint: {model}" if model else ""))
        elif t == "job_failed":
            add("failed", "bad", "This did not work", "", (e.get("error") or "")[:200])
        elif t == "job_cancelled":
            add("cancelled", "muted", "Cancelled")
        elif t == "job_expired":
            add("expired", "bad", "No Swiss service for too long", "The request was dropped. Please try again later.")
        elif t == "gateway_unreachable":
            add("problem", "warn", "The commune's gateway could not be reached", "Your letter is still kept here.")
    return stops


def compact(stops: List[Dict]) -> List[Dict]:
    """A finished retry run that only produced errors becomes one line on its "Trying again" stop.
    The run in progress, sends that got an answer, and timeouts after receipt stay visible."""
    out, i = [], 0
    while i < len(stops):
        s = stops[i]
        if s["kind"] == "retry":
            failed, j = [], i + 1
            while j + 1 < len(stops) and stops[j]["kind"] == "sent" and stops[j + 1]["kind"] == "problem":
                failed.append(stops[j]["title"][len("Sent to "):])
                j += 2
            if j < len(stops) and stops[j]["kind"] == "empty":
                j += 1
            finished = j < len(stops) and stops[j]["kind"] in ("waiting", "consent", "fallback", "done", "cancelled", "expired", "failed")
            if failed and finished:
                out.append({**s, "text": f"Tried {', '.join(failed)} again. None could answer."})
                i = j
                continue
        out.append(s)
        i += 1
    return _merge_waits(out)


def _merge_waits(stops: List[Dict]) -> List[Dict]:
    """Repeated "waiting, tried again, nothing" pairs become one waiting stop with a count.
    The last waiting stop of such a sequence stays on its own: it may be the live one."""
    out, i = [], 0
    while i < len(stops):
        j, tries = i, 0
        while (stops[j]["kind"] == "waiting" and j + 2 < len(stops)
               and stops[j + 1]["kind"] == "retry" and stops[j + 1]["text"].startswith("Tried")
               and stops[j + 2]["kind"] == "waiting"):
            tries += 1
            j += 2
        if tries:
            times = "time" if tries == 1 else "times"
            out.append({**stops[i], "text": f"Your letter stays here and is not sent anywhere else. We tried again {tries} {times}; "
                                            "none of the allowed services could answer."})
            out.append(stops[j])
            i = j + 1
        else:
            out.append(stops[i])
            i += 1
    return out


def receipt(events: List[Dict], eps: Dict) -> Dict:
    """What happened to the letter, in one place: where it went and what was ruled out."""
    sent, ruled, fallbacks, timeouts, consented = [], {}, {}, [], []
    primary = None
    for e in events:
        t = e.get("type")
        if t == "dispatch" and e.get("deployment_id") not in sent:
            sent.append(e.get("deployment_id"))
        elif t == "routing_decision":
            primary = primary or e.get("model_group")
            for ev in e.get("evaluated") or []:
                if ev.get("decision") == "blocked_before_send":
                    ruled.setdefault(ev.get("deployment_id"), _ruled_out_item(ev, eps))
                    if e.get("model_group") != primary:
                        fallbacks.setdefault(e.get("model_group"), set()).add(place(ev.get("jurisdiction")) or "an unknown place")
        elif t == "attempt_result" and e.get("outcome") == "timeout" and e.get("deployment_id") not in timeouts:
            timeouts.append(e.get("deployment_id"))
        elif t == "consent_given":
            consented += [place(j) or j for j in e.get("jurisdictions") or [] if (place(j) or j) not in consented]
    sent_to = [{"id": i, "name": _name(i, eps), "place": place((eps.get(i) or {}).get("jurisdiction")),
                "kind": (eps.get(i) or {}).get("kind")} for i in sent if i]
    return {
        "sent_to": sent_to,
        "all_swiss": bool(sent_to) and all(s["place"] == "Switzerland" for s in sent_to),
        "places": list(dict.fromkeys(s["place"] or "an unknown place" for s in sent_to)),
        "consented": consented,
        "ruled_out": list(ruled.values()),
        "fallbacks_blocked": [{"group": GROUPS.get(g, g), "places": sorted(p)} for g, p in fallbacks.items()],
        "timeouts": [_name(i, eps) for i in timeouts],
    }


def summary(events: List[Dict]) -> Dict:
    """Machine-readable summary used by the test bench."""
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
