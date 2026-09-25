"""The gateway's local store: deferred requests and their timeline.

A citizen's request waits here while no approved endpoint is available, so this file must
live in the authorized environment (the gateway's own volume, see docker-compose.yml).
The request body is deleted as soon as the job ends (done, failed, cancelled, expired);
the result and the timeline are kept for the caller to fetch.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = os.environ.get("DEFERRED_DB", "/data/deferred.db")
# Per-process secret. The deferred worker signs the job id it attaches to its own router calls;
# policy.py only files an event under a job id whose signature verifies, so a client that puts
# a job id into its request metadata cannot write into someone else's timeline.
_RUN_SECRET = secrets.token_bytes(32)
TERMINAL = ("done", "failed", "cancelled", "expired")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,          -- hash of the submitting API key: only that key can read the job
    key_alias TEXT,
    team_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,         -- queued | running | waiting | done | failed | cancelled | expired
    status_reason TEXT,
    runs INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL,
    auth_json TEXT NOT NULL,      -- server-side key/team metadata (routing policy) captured at submit
    request_json TEXT,            -- deleted when the job ends
    client_metadata_json TEXT,
    result_json TEXT,
    served_by TEXT,
    error TEXT,
    consent_json TEXT             -- a resident's recorded agreement to widen the rule for this job only
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status, next_retry_at);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_job ON events(job_id, ts);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _lock, _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()}
        if "consent_json" not in cols:  # stores created before consent existed
            c.execute("ALTER TABLE jobs ADD COLUMN consent_json TEXT")


def create_job(job_id: str, owner: str, key_alias: Optional[str], team_id: Optional[str],
               auth: dict, request: dict, client_metadata: dict) -> None:
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO jobs (id, owner, key_alias, team_id, created_at, updated_at, status, auth_json, request_json, "
            "client_metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, owner, key_alias, team_id, now, now, "queued", json.dumps(auth), json.dumps(request),
             json.dumps(client_metadata)),
        )


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(r) if r else None


def transition(job_id: str, from_statuses: Iterable[str], **fields: Any) -> bool:
    """Atomic conditional update: only if the job is still in one of from_statuses.
    Ending a job deletes its request body."""
    fields["updated_at"] = time.time()
    if fields.get("status") in TERMINAL:
        fields["request_json"] = None
        fields["next_retry_at"] = None
    froms = list(from_statuses)
    cols = ", ".join(f"{k}=?" for k in fields)
    q = f"UPDATE jobs SET {cols} WHERE id=? AND status IN ({','.join('?' * len(froms))})"
    with _lock, _conn() as c:
        return c.execute(q, (*fields.values(), job_id, *froms)).rowcount == 1


def list_jobs(owner: str, statuses: Optional[List[str]] = None, limit: int = 20) -> List[Dict[str, Any]]:
    q, args = "SELECT * FROM jobs WHERE owner=?", [owner]
    if statuses:
        q += f" AND status IN ({','.join('?' * len(statuses))})"
        args += statuses
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def due_jobs(now: float) -> List[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM jobs WHERE status='queued' OR (status='waiting' AND (next_retry_at IS NULL OR next_retry_at<=?)) "
            "ORDER BY created_at",
            (now,),
        ).fetchall()
    return [r["id"] for r in rows]


def interrupted_jobs() -> List[str]:
    with _conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM jobs WHERE status='running'").fetchall()]


def expirable_jobs(created_before: float) -> List[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM jobs WHERE status IN ('queued','waiting') AND created_at<?", (created_before,)
        ).fetchall()
    return [r["id"] for r in rows]


def sign(job_id: str) -> str:
    return hmac.new(_RUN_SECRET, job_id.encode(), hashlib.sha256).hexdigest()


def verify(job_id: Optional[str], signature: Optional[str]) -> bool:
    return bool(job_id and signature) and hmac.compare_digest(sign(job_id), str(signature))


def add_event(job_id: str, event: Dict[str, Any]) -> None:
    ts = float(event.get("ts") or time.time())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO events (job_id, ts, type, data) VALUES (?,?,?,?)",
            (job_id, ts, event.get("type", "unknown"), json.dumps(event, default=str)),
        )


def events(job_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM events WHERE job_id=? ORDER BY ts, id LIMIT ?", (job_id, limit)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d.update({"_id": r["id"], "job_id": r["job_id"], "ts": r["ts"]})
        out.append(d)
    return out


init()
