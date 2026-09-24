"""End-to-end smoke test over MCP stdio (what a real client does). Run: uv run python tests/smoke_test.py"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CASES = [
    # (tool, args, check(result) -> bool, label)
    ("resolve_swiss_location", {"place": "Konstanz"}, lambda r: r["status"] == "not_found", "Konstanz is not Swiss"),
    ("resolve_swiss_location", {"place": "Wil"}, lambda r: r["status"] == "ambiguous", "Wil -> ask which one"),
    ("resolve_swiss_location", {"place": "Bahnhofstrasse 1, 8001 Zürich"}, lambda r: r.get("bfs_nr") == 261, "address"),
    ("health_insurance_premiums", {"place": "Lugano", "age": 30, "deductible": 2500},
     lambda r: r["status"] == "ok" and r["results"][0]["cheapest"][0]["monthly_chf"] > 0, "sample Q3 Lugano"),
    ("health_insurance_premiums", {"place": "Lugano", "age": 30, "deductible": 400},
     lambda r: r["status"] == "invalid_input", "invalid deductible"),
    ("school_holidays", {"place": "Scuol", "year": 2026, "language": "rm"},
     lambda r: any("Herbst" in h["name"] for h in r["holidays"]), "sample Q4 Scuol autumn"),
    ("public_transport_connections", {"origin": "Zürich HB", "destination": "Bellinzona"},
     lambda r: r["status"] == "ok", "next connection Bellinzona"),
    ("federal_votes", {"language": "fr"}, lambda r: r["status"] in ("ok", "not_published"), "next federal vote"),
    ("search_swiss_guidance", {"query": "échanger permis de conduire étranger", "language": "fr"},
     lambda r: r["status"] == "ok" and "permis" in r["results"][0]["url"], "sample Q2 guidance"),
    ("company_register_search", {"name": "Swisscom"}, lambda r: r["status"] in ("ok", "blocked"), "zefix / robots"),
    ("server_coverage", {}, lambda r: "scope" in r, "coverage"),
]


def payload(res) -> dict:
    return json.loads(res.content[0].text)


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "swiss_grounding.server"])
    failures = 0
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print(f"{len(tools.tools)} tools:", ", ".join(t.name for t in tools.tools))
        for name, args, check, label in CASES:
            t0 = time.perf_counter()
            res = await s.call_tool(name, args)
            ms = (time.perf_counter() - t0) * 1000
            try:
                data = payload(res)
                ok = bool(check(data))
            except Exception as e:  # noqa: BLE001
                data, ok = {"error": repr(e), "raw": str(res)[:400]}, False
            failures += not ok
            size = len(json.dumps(data, ensure_ascii=False))
            print(f"{'PASS' if ok else 'FAIL'} {label:32s} {name:28s} {ms:7.0f} ms {size:6d} chars"
                  + ("" if ok else f"\n     {json.dumps(data, ensure_ascii=False)[:500]}"))
    print("failures:", failures)
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
