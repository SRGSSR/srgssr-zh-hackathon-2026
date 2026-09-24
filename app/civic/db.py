"""SQLite storage. This database is the commune's "authorized local environment":
the citizen's letter stays here while no approved endpoint is available."""

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("DB_PATH", "/data/app.db")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,            -- queued | running | waiting | done | failed | cancelled
    letter TEXT NOT NULL,
    language TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0, -- how many times the worker tried the job
    next_retry_at REAL,
    status_reason TEXT,
    result_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,            -- gateway | app
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


def create_job(letter: str, language: str) -> str:
    job_id = "job-" + uuid.uuid4().hex[:10]
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO jobs (id, created_at, updated_at, status, letter, language) VALUES (?,?,?,?,?,?)",
            (job_id, now, now, "queued", letter, language),
        )
    add_event(job_id, "app", {"type": "job_created", "language": language, "chars": len(letter)})
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not r:
        return None
    job = dict(r)
    job["result"] = json.loads(job["result_json"]) if job.get("result_json") else None
    return job


def cancel_job(job_id: str) -> bool:
    with _lock, _conn() as c:
        n = c.execute(
            "UPDATE jobs SET status='cancelled', next_retry_at=NULL, updated_at=? WHERE id=? AND status IN ('queued','waiting')",
            (time.time(), job_id),
        ).rowcount
    if n:
        add_event(job_id, "app", {"type": "job_cancelled"})
    return bool(n)


def pending_job_ids() -> List[str]:
    with _conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM jobs WHERE status IN ('queued','waiting','running')").fetchall()]


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT id, created_at, status, language FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def due_jobs(now: float) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM jobs WHERE status='queued' OR (status='waiting' AND (next_retry_at IS NULL OR next_retry_at<=?)) "
            "ORDER BY created_at",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def requeue_interrupted() -> int:
    """Jobs that were running when the app stopped are resumed, never lost."""
    with _lock, _conn() as c:
        rows = c.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
        c.execute("UPDATE jobs SET status='waiting', next_retry_at=NULL, status_reason='resumed after restart' WHERE status='running'")
    for r in rows:
        add_event(r["id"], "app", {"type": "job_resumed_after_restart"})
    return len(rows)


def add_event(job_id: Optional[str], source: str, event: Dict[str, Any]) -> None:
    ts = float(event.get("ts") or time.time())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO events (job_id, ts, source, type, data) VALUES (?,?,?,?,?)",
            (job_id, ts, source, event.get("type", "unknown"), json.dumps(event, default=str)),
        )


def events(job_id: Optional[str] = None, since_id: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
    q, args = "SELECT * FROM events WHERE id>?", [since_id]
    if job_id is not None:
        q += " AND job_id=?"
        args.append(job_id)
    q += " ORDER BY ts, id LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d.update({"_id": r["id"], "_source": r["source"], "job_id": r["job_id"], "ts": r["ts"]})
        out.append(d)
    return out
