"""Background worker: runs queued jobs, parks them as "waiting" when no approved
endpoint is available, and resumes them with backoff until an endpoint is back."""

import asyncio
import json
import os
import time

from . import db
from .llm import GatewayRejected, GatewayUnavailable, InvalidOutput, explain_letter

RETRY_MAX_SECONDS = float(os.environ.get("RETRY_MAX_SECONDS", "20"))
RETRY_BASE_SECONDS = float(os.environ.get("RETRY_BASE_SECONDS", "2"))
POLL_SECONDS = 1.0

_inflight: set = set()


def backoff(runs: int) -> float:
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** max(0, runs - 1)))


async def run_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if not job or job["status"] not in ("queued", "waiting"):
        return
    runs = job["runs"] + 1
    resumed = job["status"] == "waiting"
    db.update_job(job_id, status="running", runs=runs, status_reason=None)
    db.add_event(job_id, "app", {"type": "job_resumed" if resumed else "job_started", "run": runs})

    def on_event(e):
        db.add_event(job_id, "app", e)

    try:
        out = await explain_letter(job["letter"], job["language"], job_id, on_event=on_event)
    except GatewayUnavailable as e:
        wait = backoff(runs)
        reason = (
            "No approved endpoint is available right now. Your letter stays in this service "
            "and is not sent anywhere else. We will retry automatically."
        )
        db.update_job(job_id, status="waiting", next_retry_at=time.time() + wait, status_reason=reason, error=str(e))
        db.add_event(job_id, "app", {"type": "job_waiting", "run": runs, "retry_in_s": wait, "gateway_error": str(e)})
        return
    except GatewayRejected as e:
        db.update_job(job_id, status="failed", status_reason="The request was rejected.", error=str(e))
        db.add_event(job_id, "app", {"type": "job_failed", "error": str(e)})
        return
    except InvalidOutput as e:
        db.update_job(job_id, status="failed", status_reason="The model did not return a valid answer twice.", error=str(e))
        db.add_event(job_id, "app", {"type": "job_failed", "error": f"invalid output after retry: {e}"})
        return
    except Exception as e:  # keep the job, never lose it
        wait = backoff(runs)
        db.update_job(job_id, status="waiting", next_retry_at=time.time() + wait, status_reason="Unexpected error, retrying.", error=repr(e))
        db.add_event(job_id, "app", {"type": "job_waiting", "run": runs, "retry_in_s": wait, "gateway_error": repr(e)})
        return

    if (db.get_job(job_id) or {}).get("status") == "cancelled":
        return
    db.update_job(job_id, status="done", result_json=json.dumps(out["result"]), error=None, next_retry_at=None)
    db.add_event(job_id, "app", {"type": "job_done", "deployment_id": out["deployment_id"], "llm_calls": out["calls"]})


async def _guarded(job_id: str) -> None:
    try:
        await run_job(job_id)
    finally:
        _inflight.discard(job_id)


async def loop() -> None:
    db.requeue_interrupted()
    while True:
        for j in db.due_jobs(time.time()):
            if j["id"] not in _inflight:
                _inflight.add(j["id"])
                asyncio.create_task(_guarded(j["id"]))
        await asyncio.sleep(POLL_SECONDS)


def wake(job_id: str) -> None:
    """Retry a waiting job now (e.g. after an endpoint was restored in the demo)."""
    job = db.get_job(job_id)
    if job and job["status"] == "waiting":
        db.update_job(job_id, next_retry_at=None)
