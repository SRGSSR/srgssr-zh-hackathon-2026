"""The app's own records: which letters were submitted, which gateway jobs belong to them,
and the validated result. Waiting and retrying happen in the gateway, not here."""

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("DB_PATH", "/data/app.db")
TERMINAL = ("done", "failed", "cancelled", "expired")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS letters (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    status TEXT NOT NULL,              -- mirrors the gateway job: queued | running | waiting | done | failed | cancelled | expired
    status_reason TEXT,
    letter TEXT NOT NULL,
    language TEXT NOT NULL,
    gateway_jobs TEXT NOT NULL DEFAULT '[]',  -- deferred job ids, the last one is current
    validation_retries INTEGER NOT NULL DEFAULT 0,
    runs INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL,
    served_by TEXT,
    result_json TEXT,
    error TEXT,
    service TEXT NOT NULL DEFAULT 'social',   -- which office's rule (and key) applies
    consent_options TEXT,                      -- places the resident could still agree to (from the gateway)
    consent_json TEXT                          -- the agreement the resident gave, if any
);
CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    letter_id TEXT NOT NULL,
    ts REAL NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS app_events_letter ON app_events(letter_id, ts);
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
        cols = {r["name"] for r in c.execute("PRAGMA table_info(letters)").fetchall()}
        for col, decl in (("service", "TEXT NOT NULL DEFAULT 'social'"), ("consent_options", "TEXT"), ("consent_json", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE letters ADD COLUMN {col} {decl}")


def create(letter: str, language: str, service: str = "social") -> str:
    letter_id = "job-" + uuid.uuid4().hex[:10]
    now = time.time()
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO letters (id, created_at, updated_at, status, letter, language, service) VALUES (?,?,?,?,?,?,?)",
            (letter_id, now, now, "queued", letter, language, service),
        )
    return letter_id


def get(letter_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM letters WHERE id=?", (letter_id,)).fetchone()
    if not r:
        return None
    job = dict(r)
    job["gateway_jobs"] = json.loads(job["gateway_jobs"] or "[]")
    job["consent_options"] = json.loads(job.get("consent_options") or "[]")
    job["consent"] = json.loads(job["consent_json"]) if job.get("consent_json") else None
    job["result"] = json.loads(job["result_json"]) if job.get("result_json") else None
    return job


def update(letter_id: str, **fields: Any) -> None:
    for k in ("gateway_jobs", "consent_options"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    if "consent" in fields:
        consent = fields.pop("consent")
        fields["consent_json"] = json.dumps(consent) if consent else None
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, _conn() as c:
        c.execute(f"UPDATE letters SET {cols} WHERE id=?", (*fields.values(), letter_id))


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT id, created_at, status, language FROM letters ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def add_event(letter_id: str, event: Dict[str, Any]) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO app_events (letter_id, ts, type, data) VALUES (?,?,?,?)",
            (letter_id, float(event.get("ts") or time.time()), event.get("type", "unknown"), json.dumps(event, default=str)),
        )


def events(letter_id: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM app_events WHERE letter_id=? ORDER BY ts, id", (letter_id,)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d.update({"ts": r["ts"], "_source": "app", "_id": r["id"]})
        out.append(d)
    return out
