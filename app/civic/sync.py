"""Keeps a letter in step with its gateway job. Called whenever the letter is read (the page
polls every second): there is no background worker in the app any more."""

import asyncio
from typing import Dict, List, Optional

from . import db, gateway
from .llm import InvalidOutput, build_messages, content_of, correction_messages, parse_result

_locks: Dict[str, asyncio.Lock] = {}


async def submit(letter_id: str) -> None:
    """Hand the letter to the gateway. If the gateway itself is unreachable, the letter stays
    in the app and is handed over on the next read."""
    job = db.get(letter_id)
    try:
        g = await gateway.submit(build_messages(job["letter"], job["language"]), {"app_letter_id": letter_id})
    except gateway.GatewayUnreachable as e:
        db.update(letter_id, status="queued", status_reason="The gateway is not reachable; your letter is kept here.", error=str(e))
        return
    except gateway.GatewayRejected as e:
        db.update(letter_id, status="failed", status_reason="The gateway rejected the request.", error=str(e))
        return
    db.update(letter_id, gateway_jobs=job["gateway_jobs"] + [g["id"]], status=g["status"], status_reason=None, error=None)


async def refresh(letter_id: str) -> Optional[dict]:
    job = db.get(letter_id)
    if job is None or job["status"] in db.TERMINAL:
        return job
    lock = _locks.setdefault(letter_id, asyncio.Lock())
    async with lock:
        job = db.get(letter_id)
        if job["status"] in db.TERMINAL:
            return job
        if not job["gateway_jobs"]:
            await submit(letter_id)
            return db.get(letter_id)
        try:
            g = await gateway.job(job["gateway_jobs"][-1])
        except gateway.GatewayUnreachable:
            return job  # nothing changes for the letter; the gateway still holds the job
        except gateway.GatewayRejected as e:
            db.update(letter_id, status="failed", status_reason="The gateway no longer knows this request.", error=str(e))
            return db.get(letter_id)

        status = g["status"]
        if status != "done":
            db.update(letter_id, status=status, status_reason=g.get("status_reason"), runs=g.get("runs", 0),
                      next_retry_at=g.get("next_retry_at"), error=g.get("error"))
            return db.get(letter_id)

        content = content_of(g)
        try:
            result = parse_result(content)
        except InvalidOutput as e:
            if job["validation_retries"] == 0:
                db.add_event(letter_id, {"type": "output_invalid_retrying", "error": str(e), "deployment_id": g.get("served_by")})
                try:
                    g2 = await gateway.submit(correction_messages(job["letter"], job["language"], content, str(e)),
                                              {"app_letter_id": letter_id, "validation_retry": True})
                except (gateway.GatewayUnreachable, gateway.GatewayRejected) as ex:
                    db.update(letter_id, status="failed", status_reason="Could not ask the model again.", error=str(ex))
                    return db.get(letter_id)
                db.update(letter_id, gateway_jobs=job["gateway_jobs"] + [g2["id"]], validation_retries=1, status=g2["status"])
            else:
                db.add_event(letter_id, {"type": "job_failed", "error": f"invalid output after retry: {e}"})
                db.update(letter_id, status="failed", status_reason="The model did not return a valid answer twice.", error=str(e))
            return db.get(letter_id)

        db.update(letter_id, status="done", status_reason=None, error=None, served_by=g.get("served_by"),
                  result_json=result.model_dump_json(), runs=g.get("runs", 0), next_retry_at=None)
        return db.get(letter_id)


async def events(letter_id: str) -> List[dict]:
    """Timeline = the gateway's events for every job of this letter + the app's own events."""
    job = db.get(letter_id)
    out = [{"type": "letter_stored", "ts": job["created_at"], "language": job["language"], "_source": "app"}]
    out += db.events(letter_id)
    for gid in job["gateway_jobs"]:
        try:
            out += [{**e, "_source": "gateway", "gateway_job": gid} for e in await gateway.events(gid)]
        except (gateway.GatewayUnreachable, gateway.GatewayRejected):
            out.append({"type": "gateway_unreachable", "ts": job["updated_at"], "gateway_job": gid, "_source": "app"})
    return sorted(out, key=lambda e: e.get("ts") or 0)


async def wake(letter_id: str) -> None:
    job = db.get(letter_id)
    if job and job["gateway_jobs"] and job["status"] == "waiting":
        try:
            await gateway.retry(job["gateway_jobs"][-1])
        except (gateway.GatewayUnreachable, gateway.GatewayRejected):
            pass


async def cancel(letter_id: str) -> None:
    job = db.get(letter_id)
    if not job or job["status"] in db.TERMINAL:
        return
    if job["gateway_jobs"]:
        try:
            await gateway.cancel(job["gateway_jobs"][-1])
        except (gateway.GatewayUnreachable, gateway.GatewayRejected):
            pass
    else:
        db.add_event(letter_id, {"type": "job_cancelled"})  # otherwise the gateway records it
    db.update(letter_id, status="cancelled", status_reason="Cancelled by you.")
