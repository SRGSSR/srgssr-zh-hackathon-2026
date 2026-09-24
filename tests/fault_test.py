"""Resilience test: sources down -> stale cache disclosed, or honest 'unavailable'. Run: uv run python tests/fault_test.py

1. Warm a temporary cache with live calls.
2. Age the cache files past their TTL (but within SGM_STALE_MAX_DAYS).
3. Restart the server with SGM_FAULT_HOSTS simulating an outage of those sources.
4. Expect: cached answers flagged `served_from_cache` + `data_as_of`; uncached queries -> status `unavailable`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DOWN = "www.bwo.admin.ch,ogd-static.voteinfo-app.ch,transport.opendata.ch"
CACHED = [("reference_interest_rate", {"language": "it"}), ("federal_votes", {"language": "fr"})]
UNCACHED = ("public_transport_connections", {"origin": "Scuol-Tarasp", "destination": "Poschiavo"})


async def session(env: dict, calls: list[tuple[str, dict]]) -> list[dict]:
    params = StdioServerParameters(command=sys.executable, args=["-m", "swiss_grounding.server"],
                                   env={**os.environ, **env})
    out = []
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for name, args in calls:
            res = await s.call_tool(name, args)
            out.append(json.loads(res.content[0].text))
    return out


async def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="sgm-cache-") as cache:
        env = {"SGM_CACHE_DIR": cache}
        warm = await session(env, CACHED)
        assert all(r["status"] == "ok" for r in warm), warm
        old = time.time() - 2 * 86400  # older than any TTL used for these sources, younger than 30 days
        for f in Path(cache).glob("*.json"):
            os.utime(f, (old, old))
        results = await session({**env, "SGM_FAULT_HOSTS": DOWN}, CACHED + [UNCACHED])

    for (name, _), r in zip(CACHED, results[:2]):
        ok = r.get("status") == "ok" and r.get("served_from_cache") and r.get("data_as_of")
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {name:28s} outage -> stale cache disclosed: "
              f"served_from_cache={r.get('served_from_cache')} data_as_of={r.get('data_as_of')}")
    r = results[2]
    ok = r.get("status") == "unavailable" and "retrieval failure" in r.get("message", "")
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {UNCACHED[0]:28s} outage, nothing cached -> {r.get('status')}: "
          f"{r.get('message', '')[:110]}")
    print("failures:", failures)
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
