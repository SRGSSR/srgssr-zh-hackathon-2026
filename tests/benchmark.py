"""Run the adversarial benchmark over MCP stdio. Usage: uv run python tests/benchmark.py [--only ID] [--json out.json]"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent


def check(case: dict, r: dict, chars: int, ms: float, defaults: dict) -> list[str]:
    e, errs = case.get("expect", {}), []
    topic = (r.get("topic") or {}).get("id") if isinstance(r.get("topic"), dict) else r.get("topic")
    jur = r.get("jurisdiction") or {}
    nc = r.get("next_call") or {}

    def want(name, got, exp):
        if got != exp:
            errs.append(f"{name}: expected {exp!r}, got {got!r}")

    for k in ("decision", "status", "support", "language", "missing", "freshness"):
        if k in e:
            want(k, r.get(k), e[k])
    if "status_in" in e and r.get("status") not in e["status_in"]:
        errs.append(f"status: expected one of {e['status_in']}, got {r.get('status')!r}")
    if "topic" in e:
        want("topic", topic, e["topic"])
    if "canton" in e:
        want("canton", jur.get("canton", r.get("canton")), e["canton"])
    if "bfs_nr" in e:
        want("bfs_nr", jur.get("bfs_nr", r.get("bfs_nr")), e["bfs_nr"])
    if "next_tool" in e:
        want("next_tool", nc.get("tool"), e["next_tool"])
    for k, v in (e.get("next_args") or {}).items():
        want(f"next_args.{k}", (nc.get("args") or {}).get(k), v)
    if "next_missing" in e:
        want("next_missing", nc.get("missing"), e["next_missing"])
    if "evidence_url_contains" in e:
        urls = [h["url"] for h in r.get("evidence", [])]
        if not any(e["evidence_url_contains"] in u for u in urls):
            errs.append(f"evidence: no URL containing {e['evidence_url_contains']!r} in {urls}")
    if "excerpt_contains_any" in e:
        text = " ".join(h.get("excerpt", "") for h in r.get("evidence", []))
        if not any(x in text for x in e["excerpt_contains_any"]):
            errs.append(f"excerpt: none of {e['excerpt_contains_any']} in evidence excerpts")
    if "jurisdictions_bfs" in e:
        want("jurisdictions_bfs", [j["jurisdiction"].get("bfs_nr") for j in r.get("jurisdictions", [])], e["jurisdictions_bfs"])
    for k in ("reference_rate_percent", "valid_since"):
        if k in e and not r.get(k):
            errs.append(f"{k}: missing")
    if "chain_office" in e and e["chain_office"] not in [c.get("url") for c in r.get("authority_chain", [])
                                                         if c.get("office")]:
        errs.append(f"authority_chain: office {e['chain_office']} missing")
    for k, v in (e.get("fields") or {}).items():  # arbitrary top-level result fields
        want(k, r.get(k), v)
    if "chain_level" in e and e["chain_level"] not in [c.get("level") for c in r.get("authority_chain", [])]:
        errs.append(f"authority_chain: no {e['chain_level']} entry")
    if chars > case.get("max_chars", defaults["max_chars"]):
        errs.append(f"response too large: {chars} chars")
    if ms > case.get("max_ms", defaults["max_ms"]):
        errs.append(f"too slow: {ms:.0f} ms")
    return errs


async def run(only: str | None) -> tuple[list[dict], int]:
    spec = yaml.safe_load((HERE / "benchmark.yaml").read_text(encoding="utf-8"))
    defaults = spec["defaults"]
    cases = [c for c in spec["cases"] if not only or c["id"] == only]
    params = StdioServerParameters(command=sys.executable, args=["-m", "swiss_grounding.server"])
    report = []
    async with stdio_client(params) as (rd, wr), ClientSession(rd, wr) as s:
        await s.initialize()

        async def call(tool, args):
            t0 = time.perf_counter()
            res = await s.call_tool(tool, args)
            ms = (time.perf_counter() - t0) * 1000
            text = res.content[0].text if res.content else "{}"
            try:
                return json.loads(text), len(text), ms
            except json.JSONDecodeError:
                return {"status": "error", "raw": text[:300]}, len(text), ms

        for c in cases:
            tool = c.get("tool", "swiss_ground")
            args = c.get("args") or {"question": c["question"], **({"place": c["place"]} if c.get("place") else {})}
            r, chars, ms = await call(tool, args)
            errs = check(c, r, chars, ms, defaults)
            calls, total_chars, total_ms = 1, chars, ms
            if c.get("follow") and not errs:
                nc = r.get("next_call") or {}
                r2, ch2, ms2 = await call(nc["tool"], nc["args"])
                calls, total_chars, total_ms = 2, chars + ch2, ms + ms2
                if r2.get("status") != "ok":
                    errs.append(f"follow-up {nc['tool']} returned {r2.get('status')}: {str(r2)[:200]}")
            report.append({"id": c["id"], "category": c["category"], "pass": not errs, "errors": errs,
                           "calls": calls, "chars": total_chars, "ms": round(total_ms)})
    return report, sum(not x["pass"] for x in report)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--json", default=str(HERE / "benchmark_report.json"))
    a = ap.parse_args()
    report, failures = asyncio.run(run(a.only))
    for x in report:
        print(f"{'PASS' if x['pass'] else 'FAIL'} {x['category']:18s} {x['id']:30s} calls={x['calls']} "
              f"{x['chars']:6d} chars {x['ms']:6d} ms" + "".join(f"\n      - {e}" for e in x["errors"]))
    by = defaultdict(lambda: [0, 0])
    for x in report:
        by[x["category"]][0] += x["pass"]
        by[x["category"]][1] += 1
    print("\nby category: " + ", ".join(f"{k} {p}/{n}" for k, (p, n) in sorted(by.items())))
    n = len(report)
    print(f"total {n - failures}/{n} passed; median response {sorted(x['chars'] for x in report)[n // 2]} chars; "
          f"median latency {sorted(x['ms'] for x in report)[n // 2]} ms")
    Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return failures


if __name__ == "__main__":
    sys.exit(main())
