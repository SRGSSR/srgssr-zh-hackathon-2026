"""Turns raw gateway and app events into the "journey of your letter": stops written for
the resident, with the technical detail kept separately for the jury."""

import datetime as dt
import os
from typing import Dict, List
from zoneinfo import ZoneInfo

from . import i18n
from .endpoints import group_name


LOCAL_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "Europe/Zurich"))


def _time(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%H:%M:%S")


def _name(dep_id, eps: Dict, lang: str) -> str:
    return (eps.get(dep_id or "") or {}).get("name") or dep_id or i18n.t(lang, "common.unknown_service")


def _reason(ev: Dict, lang: str) -> str:
    if "missing metadata" in (ev.get("reason") or ""):
        return i18n.t(lang, "journey.reason_unknown")
    where = i18n.place(lang, ev.get("jurisdiction"))
    return (i18n.t(lang, "journey.reason_place", where=where) if where
            else i18n.t(lang, "journey.reason_outside", code=ev.get("jurisdiction")))


def _ruled_out_item(ev: Dict, eps: Dict, lang: str) -> Dict:
    return {"id": ev.get("deployment_id"), "name": _name(ev.get("deployment_id"), eps, lang), "reason": _reason(ev, lang)}


def _where(lang: str, code) -> str:
    return i18n.place(lang, code) or i18n.t(lang, "place.unknown")


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


RULES = ("CH-only", "CH-then-EU", "CH-EU-then-consent")


def journey(events: List[Dict], eps: Dict, lang: str = "en") -> List[Dict]:
    tr = lambda key, **kw: i18n.t(lang, key, **kw)  # noqa: E731
    name = lambda dep_id: _name(dep_id, eps, lang)  # noqa: E731
    stops: List[Dict] = []
    finished_by = {e.get("deployment_id") for e in events if e.get("type") == "job_done"}
    shown_ruled_out, shown_fallbacks = set(), set()
    primary_group, last_empty_group = None, None
    policy_id, consented = "CH-only", set()
    pending: List[Dict] = []

    for e in events:
        t = e.get("type")
        key = f"{e.get('_source')}:{e.get('gateway_job') or ''}:{e.get('_id') or e.get('ts')}:{t}"

        def add(kind, tone, title, text="", tech="", crossed=None, target=None):
            stops.append({"key": key, "kind": kind, "tone": tone, "title": title, "text": text, "tech": tech,
                          "crossed": crossed or [], "time": _time(e["ts"]), "ts": e["ts"], "target": target})

        if t == "letter_stored":
            stops.append({"key": "letter", "kind": "letter", "tone": "calm", "title": tr("journey.letter"),
                          "text": tr("journey.letter_text"), "tech": f"language {e.get('language')}",
                          "crossed": [], "time": _time(e["ts"]), "ts": e["ts"]})
        elif t == "job_created":
            add("gateway", "calm", tr("journey.gateway"), tr("journey.gateway_text"), f"deferred job {e.get('gateway_job')}")
        elif t == "request_accepted":
            policy_id = e.get("policy_id") or policy_id
            add("rule", "calm", tr("journey.rule"),
                tr(f"journey.rule.{policy_id}") if policy_id in RULES else (e.get("rule") or ""),
                f"policy {e.get('policy_id')}, bound to the key {e.get('key_alias')}")
        elif t == "consent_given":
            consented.update(e.get("jurisdictions") or [])
            where = i18n.join(lang, [_where(lang, j) for j in e.get("jurisdictions") or []])
            add("consent", "wait", tr("journey.consent", where=where), tr("journey.consent_text"),
                (e.get("statement") or "")[:200])
        elif t == "routing_decision":
            group = e.get("model_group")
            primary_group = primary_group or group
            blocked = [ev for ev in e.get("evaluated") or [] if ev.get("decision") == "blocked_before_send"]
            if e.get("selected"):
                last_empty_group = None
                fresh = [ev for ev in blocked if ev.get("deployment_id") not in shown_ruled_out]
                shown_ruled_out.update(ev.get("deployment_id") for ev in fresh)
                pending = [_ruled_out_item(ev, eps, lang) for ev in fresh]
            elif group != primary_group:
                if group in shown_fallbacks:
                    continue
                shown_fallbacks.add(group)
                where = i18n.join(lang, sorted({_where(lang, ev.get("jurisdiction")) for ev in blocked}))
                add("fallback", "bad", tr("journey.fallback", model=group_name(lang, group)),
                    tr("journey.fallback_text", where=where),
                    f"LiteLLM fallback to the model group {group}, blocked before send",
                    [_ruled_out_item(ev, eps, lang) for ev in blocked])
            else:
                if last_empty_group == group:
                    continue
                last_empty_group = group
                add("empty", "warn", tr("journey.empty_ch") if policy_id == "CH-only" else tr("journey.empty"),
                    tr("journey.empty_text"), f"no allowed deployment left in {group}")
        elif t == "dispatch":
            dep = eps.get(e.get("deployment_id") or "", {})
            where = i18n.place(lang, dep.get("jurisdiction") or e.get("jurisdiction"))
            kind = tr("journey.sent_real") if (e.get("endpoint_kind") or dep.get("kind")) == "real" else tr("journey.sent_simulated")
            if (dep.get("jurisdiction") or e.get("jurisdiction")) in consented:
                kind = tr("journey.sent_agreed") + " " + kind
            target = name(e.get("deployment_id"))
            add("sent", "send", tr("journey.sent", name=target), f"{_cap(where)}. {kind}" if where else kind,
                f"{e.get('deployment_id')} at {e.get('api_base')}", pending, target=target)
            pending = []
        elif t == "send_vetoed":
            add("vetoed", "bad", tr("journey.vetoed", name=name(e.get("deployment_id"))), tr("journey.vetoed_text"),
                e.get("reason", ""))
        elif t == "attempt_result":
            who, outcome = name(e.get("deployment_id")), e.get("outcome")
            tech = " ".join(str(x) for x in (e.get("error_type"), e.get("status_code")) if x)
            if outcome == "success":
                if e.get("deployment_id") in finished_by:
                    continue  # the "ready" stop already says who wrote the answer
                add("answer", "good", tr("journey.answered", name=who), "", f"model reported by the endpoint: {e.get('model_returned')}")
            elif outcome == "timeout":
                swiss = (eps.get(e.get("deployment_id") or "", {}).get("jurisdiction")) == "CH"
                add("noanswer", "warn", tr("journey.noanswer", name=who),
                    tr("journey.noanswer_text") + (" " + tr("journey.noanswer_swiss") if swiss else ""), tech)
            elif outcome == "connection_failed":
                add("problem", "warn", tr("journey.unreachable", name=who), tr("journey.unreachable_text"), tech)
            elif outcome == "error":
                add("problem", "warn", tr("journey.error", name=who), tr("journey.error_text"), tech)
        elif t == "job_waiting":
            wait_s = int(e.get("retry_in_s", 0))
            add("waiting", "wait", tr("journey.waiting.CH-only") if policy_id == "CH-only" else tr("journey.waiting.other"),
                tr("journey.waiting_text") + " " + (tr("common.next_try", n=wait_s) if wait_s else tr("journey.try_now")),
                (e.get("gateway_error") or "")[:160])
        elif t in ("job_started", "job_resumed"):
            if t == "job_started" and (e.get("run") or 1) == 1:
                continue
            add("retry", "calm", tr("journey.retry"), "", f"run {e.get('run')}")
        elif t == "retry_requested":
            add("retry", "calm", tr("journey.retry_asked"))
        elif t == "job_resumed_after_restart":
            add("restart", "calm", tr("journey.restart"), tr("journey.restart_text"))
        elif t == "output_invalid_retrying":
            add("retry", "warn", tr("journey.invalid"), "", (e.get("error") or "")[:160])
        elif t == "job_done":
            dep = eps.get(e.get("deployment_id") or "", {})
            where = i18n.place(lang, dep.get("jurisdiction"))
            model = next((x.get("model_returned") for x in events if x.get("type") == "attempt_result"
                          and x.get("outcome") == "success" and x.get("deployment_id") == e.get("deployment_id")), None)
            add("done", "good", tr("journey.done"),
                tr("journey.done_text_where", name=name(e.get("deployment_id")), where=where) if where
                else tr("journey.done_text", name=name(e.get("deployment_id"))),
                f"served by {e.get('deployment_id')}" + (f", model reported by the endpoint: {model}" if model else ""))
        elif t == "job_failed":
            add("failed", "bad", tr("job.title.failed"), "", (e.get("error") or "")[:200])
        elif t == "job_cancelled":
            add("cancelled", "muted", tr("journey.cancelled"))
        elif t == "job_expired":
            add("expired", "bad", tr("journey.expired"), tr("journey.expired_text"))
        elif t == "gateway_unreachable":
            add("problem", "warn", tr("journey.gw_unreachable"), tr("journey.gw_unreachable_text"))
    return stops


def compact(stops: List[Dict], lang: str = "en") -> List[Dict]:
    """A finished retry run that only produced errors becomes one line on its "Trying again" stop.
    The run in progress, sends that got an answer, and timeouts after receipt stay visible."""
    out, i = [], 0
    while i < len(stops):
        s = stops[i]
        if s["kind"] == "retry":
            failed, j = [], i + 1
            while j + 1 < len(stops) and stops[j]["kind"] == "sent" and stops[j + 1]["kind"] == "problem":
                failed.append(stops[j].get("target") or "")
                j += 2
            if j < len(stops) and stops[j]["kind"] == "empty":
                j += 1
            finished = j < len(stops) and stops[j]["kind"] in ("waiting", "consent", "fallback", "done", "cancelled", "expired", "failed")
            if failed and finished:
                out.append({**s, "text": i18n.t(lang, "journey.tried_again", names=i18n.join(lang, failed)), "retried": True})
                i = j
                continue
        out.append(s)
        i += 1
    return _merge_waits(out, lang)


def _merge_waits(stops: List[Dict], lang: str) -> List[Dict]:
    """Repeated "waiting, tried again, nothing" pairs become one waiting stop with a count.
    The last waiting stop of such a sequence stays on its own: it may be the live one."""
    out, i = [], 0
    while i < len(stops):
        j, tries = i, 0
        while (stops[j]["kind"] == "waiting" and j + 2 < len(stops)
               and stops[j + 1]["kind"] == "retry" and stops[j + 1].get("retried")
               and stops[j + 2]["kind"] == "waiting"):
            tries += 1
            j += 2
        if tries:
            text = i18n.t(lang, "journey.waited_one") if tries == 1 else i18n.t(lang, "journey.waited_many", n=tries)
            out.append({**stops[i], "text": text})
            out.append(stops[j])
            i = j + 1
        else:
            out.append(stops[i])
            i += 1
    return out


def receipt(events: List[Dict], eps: Dict, lang: str = "en") -> Dict:
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
                    ruled.setdefault(ev.get("deployment_id"), _ruled_out_item(ev, eps, lang))
                    if e.get("model_group") != primary:
                        fallbacks.setdefault(e.get("model_group"), set()).add(_where(lang, ev.get("jurisdiction")))
        elif t == "attempt_result" and e.get("outcome") == "timeout" and e.get("deployment_id") not in timeouts:
            timeouts.append(e.get("deployment_id"))
        elif t == "consent_given":
            consented += [_where(lang, j) for j in e.get("jurisdictions") or [] if _where(lang, j) not in consented]
    sent_to = [{"id": i, "name": _name(i, eps, lang), "jurisdiction": (eps.get(i) or {}).get("jurisdiction"),
                "place": _where(lang, (eps.get(i) or {}).get("jurisdiction")), "kind": (eps.get(i) or {}).get("kind")}
               for i in sent if i]
    return {
        "sent_to": sent_to,
        "all_swiss": bool(sent_to) and all(s["jurisdiction"] == "CH" for s in sent_to),
        "places": list(dict.fromkeys(s["place"] for s in sent_to)),
        "consented": consented,
        "ruled_out": list(ruled.values()),
        "fallbacks_blocked": [{"group": group_name(lang, g), "places": sorted(p)} for g, p in fallbacks.items()],
        "timeouts": [_name(i, eps, lang) for i in timeouts],
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
