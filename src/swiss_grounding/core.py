"""Shared plumbing: configuration, cached HTTP with robots.txt policy, citations, metrics."""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import ssl
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("swiss_grounding")


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # Respect robots.txt of every source by default. Swisscom can switch it off for testing.
    respect_robots: bool = _bool_env("SGM_RESPECT_ROBOTS", True)
    cache_dir: Path = Path(os.getenv("SGM_CACHE_DIR", ".cache"))
    cache_enabled: bool = _bool_env("SGM_CACHE", True)
    timeout_s: float = float(os.getenv("SGM_TIMEOUT", "15"))
    user_agent: str = os.getenv(
        "SGM_USER_AGENT", "Mozilla/5.0 (compatible; swiss-grounding-mcp/0.1; hackathon prototype)"
    )
    # Many networks (WSL, Docker, hotel Wi-Fi) resolve AAAA records but cannot route IPv6.
    ipv4_only: bool = _bool_env("SGM_IPV4_ONLY", True)
    # Serve an expired cached copy when a source is down, up to this age.
    stale_max_days: float = float(os.getenv("SGM_STALE_MAX_DAYS", "30"))
    # Comma-separated hosts treated as unreachable (resilience testing / demos).
    fault_hosts: frozenset = frozenset(h.strip() for h in os.getenv("SGM_FAULT_HOSTS", "").split(",") if h.strip())
    data_dir: Path = Path(os.getenv("SGM_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


CONFIG = Config()


class SourceBlocked(Exception):
    """robots.txt disallows the request and SGM_RESPECT_ROBOTS is on."""


class SourceUnavailable(Exception):
    """Upstream authoritative source failed; callers must say so instead of guessing.

    `status` is the HTTP status code when the server answered (e.g. 404), None for network/TLS failures, so callers
    can tell "does not exist" apart from "could not be retrieved".
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cite(title: str, url: str, publisher: str, level: str, valid_for: str | None = None,
         last_updated: str | None = None) -> dict:
    """Citation object attached to every answer. level: federal|cantonal|municipal|semi-official|aggregator|unverified."""
    c = {"title": title, "url": url, "publisher": publisher, "level": level, "retrieved": now_iso()}
    if valid_for:
        c["valid_for"] = valid_for
    if last_updated:
        c["last_updated"] = last_updated
    return c


@dataclass
class Metrics:
    started: float = field(default_factory=time.time)
    calls: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    upstream_requests: int = 0
    upstream_ms: float = 0.0
    stale_served: int = 0

    def snapshot(self) -> dict:
        return {
            "uptime_s": round(time.time() - self.started),
            "tool_calls": self.calls,
            "tool_errors": self.errors,
            "cache_hits": self.cache_hits,
            "upstream_requests": self.upstream_requests,
            "stale_cache_served": self.stale_served,
            "avg_upstream_ms": round(self.upstream_ms / self.upstream_requests) if self.upstream_requests else None,
        }


METRICS = Metrics()

_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_mem: dict[str, tuple[float, Any, float]] = {}  # key -> (expires, data, fetched_at)
_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        # OS trust store (works behind corporate TLS proxies); SGM_CA_BUNDLE overrides.
        ctx = ssl.create_default_context(cafile=os.getenv("SGM_CA_BUNDLE") or None)
        _client = httpx.Client(
            transport=httpx.HTTPTransport(verify=ctx, local_address="0.0.0.0" if CONFIG.ipv4_only else None, retries=1),
            headers={"User-Agent": CONFIG.user_agent, "Accept-Language": "de,fr,it,en"},
            timeout=CONFIG.timeout_s,
            follow_redirects=True,
        )
    return _client


def robots_allowed(url: str) -> bool:
    if not CONFIG.respect_robots:
        return True
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = client().get(base + "/robots.txt", timeout=5)
            if r.status_code >= 400 or "text/plain" not in r.headers.get("content-type", ""):
                rp = None  # no (valid) robots.txt => allowed; some SPAs answer with an HTML page
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp = None
        _robots[base] = rp
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(CONFIG.user_agent, url)


def _cache_key(method: str, url: str, params: Any, body: Any) -> str:
    raw = json.dumps([method, url, params, body], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


# Provenance of every upstream read during the current tool call (reset by the server's tool wrapper).
FETCH_LOG: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar("fetch_log", default=None)


def _log_fetch(url: str, fetched_at: float, origin: str) -> None:
    events = FETCH_LOG.get()
    if events is not None:
        events.append({"host": urlparse(url).netloc, "fetched_at": _iso(fetched_at), "origin": origin})


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat()


def _stale_copy(key: str) -> tuple[float, Any] | None:
    """Expired cache entry usable as a fallback when the source is down (bounded by SGM_STALE_MAX_DAYS)."""
    if not CONFIG.cache_enabled:
        return None
    hit = _mem.get(key)
    if hit:
        return hit[2], hit[1]
    f = CONFIG.cache_dir / f"{key}.json"
    if f.exists() and f.stat().st_mtime > time.time() - CONFIG.stale_max_days * 86400:
        return f.stat().st_mtime, json.loads(f.read_text())
    return None


def fetch(
    url: str,
    *,
    params: dict | None = None,
    json_body: Any = None,
    ttl: int = 3600,
    as_json: bool = True,
) -> Any:
    """GET (or POST when json_body is given) with a two-level TTL cache and stale-if-error fallback.

    Memory cache for hot keys, disk cache so restarts don't hammer public sources. If the source is unreachable
    (network error or 5xx), the last cached copy is served and recorded in FETCH_LOG as origin "stale_cache" so the
    answer can disclose it. 4xx responses are never masked: the resource genuinely does not exist (any more).
    """
    method = "POST" if json_body is not None else "GET"
    key = _cache_key(method, url, params, json_body)
    now = time.time()
    if CONFIG.cache_enabled and ttl > 0:
        hit = _mem.get(key)
        if hit and hit[0] > now:
            METRICS.cache_hits += 1
            _log_fetch(url, hit[2], "cache")
            return hit[1]
        f = CONFIG.cache_dir / f"{key}.json"
        if f.exists() and f.stat().st_mtime + ttl > now:
            data = json.loads(f.read_text())
            mtime = f.stat().st_mtime
            _mem[key] = (mtime + ttl, data, mtime)
            METRICS.cache_hits += 1
            _log_fetch(url, mtime, "cache")
            return data

    if not robots_allowed(url):
        raise SourceBlocked(f"robots.txt of {urlparse(url).netloc} disallows {url} (SGM_RESPECT_ROBOTS=true)")

    t0 = time.perf_counter()
    try:
        if urlparse(url).netloc in CONFIG.fault_hosts:  # fault injection for resilience tests
            raise httpx.ConnectError(f"simulated outage (SGM_FAULT_HOSTS) for {urlparse(url).netloc}")
        r = client().request(method, url, params=params, json=json_body)
        r.raise_for_status()
    except httpx.HTTPError as e:
        # 4xx means the resource is really gone - except 429 (rate limited), which is transient like a 5xx.
        is_client_error = (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
                           and e.response.status_code != 429)
        stale = None if is_client_error or ttl <= 0 else _stale_copy(key)
        if stale:
            METRICS.stale_served += 1
            log.warning("serving stale cache for %s (%s)", url, e.__class__.__name__)
            _log_fetch(url, stale[0], "stale_cache")
            return stale[1]
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        raise SourceUnavailable(f"{urlparse(url).netloc}: {e.__class__.__name__}: {e}", status) from e
    finally:
        METRICS.upstream_requests += 1
        METRICS.upstream_ms += (time.perf_counter() - t0) * 1000

    data = r.json() if as_json else r.text
    _log_fetch(url, now, "live")
    if CONFIG.cache_enabled and ttl > 0:
        _mem[key] = (now + ttl, data, now)
        try:
            CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
            (CONFIG.cache_dir / f"{key}.json").write_text(json.dumps(data))
        except OSError:
            log.warning("disk cache not writable: %s", CONFIG.cache_dir)
    return data
