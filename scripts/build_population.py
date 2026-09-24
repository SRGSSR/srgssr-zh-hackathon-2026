"""Build data/population.json: permanent resident population per municipality, canton and Switzerland.

Source: Federal Statistical Office (FSO/BFS), STATPOP, PxWeb table px-x-0102010000_101 (reference date 31 December).
The data changes once a year, so it is shipped prebuilt instead of queried live.

Usage:
    uv run python scripts/build_population.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swiss_grounding.core import client  # noqa: E402

TABLE = "px-x-0102010000_101"
API = f"https://www.pxweb.bfs.admin.ch/api/v1/de/{TABLE}/{TABLE}.px"
PAGE = f"https://www.pxweb.bfs.admin.ch/pxweb/de/{TABLE}/{TABLE}/{TABLE}.px/"
GEO = "Kanton (-) / Bezirk (>>) / Gemeinde (......)"
OUT = Path(__file__).resolve().parents[1] / "data" / "population.json"


def main() -> None:
    c = client()
    meta = c.get(API, timeout=120).json()
    var = {v["code"]: v for v in meta["variables"]}
    years = var["Jahr"]["values"][-2:]
    # keep Switzerland (8100), cantons (2 letters) and municipalities (4 digits); skip districts (6 digits)
    geo = [(code, text) for code, text in zip(var[GEO]["values"], var[GEO]["valueTexts"])
           if code == "8100" or re.fullmatch(r"[A-Z]{2}", code) or re.fullmatch(r"\d{4}", code)]
    query = {"query": [
        {"code": "Jahr", "selection": {"filter": "item", "values": years}},
        {"code": GEO, "selection": {"filter": "item", "values": [g for g, _ in geo]}},
        {"code": "Bevölkerungstyp", "selection": {"filter": "item", "values": ["1"]}},
        {"code": "Staatsangehörigkeit (Kategorie)", "selection": {"filter": "item", "values": ["-99999", "2"]}},
        {"code": "Geschlecht", "selection": {"filter": "item", "values": ["-99999"]}},
        {"code": "Alter", "selection": {"filter": "item", "values": ["-99999"]}},
    ], "response": {"format": "json-stat2"}}
    data = c.post(API, json=query, timeout=180).json()
    dims, sizes = data["id"], data["size"]
    idx = {d: data["dimension"][d]["category"]["index"] for d in dims}

    def value(year: str, area: str, nat: str) -> int | None:
        pos = 0
        for d, size in zip(dims, sizes):
            key = {"Jahr": year, GEO: area, "Staatsangehörigkeit (Kategorie)": nat}.get(d)
            pos = pos * size + (idx[d][key] if key is not None else 0)
        return data["value"][pos]

    rows = {}
    for code, text in geo:
        name = re.sub(r"^[.\-\s]*(\d{4}\s+)?", "", text).strip()
        rows[code] = {"name": name, "values": {y: [value(y, code, "-99999"), value(y, code, "2")] for y in years}}

    page = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c.get(PAGE, timeout=120).text)))
    notes = {}
    for key, pat in (("reference_date", r"Stichtag:\s*([^:]+?)\s+Raumbezug"),
                     ("database_state", r"Stand der Datenbank:\s*([^:]+?)\s+Stichtag"),
                     ("boundaries_as_of", r"Raumbezug:\s*Gemeinden\s*/\s*(\d{2}\.\d{2}\.\d{4})")):
        if m := re.search(pat, page):
            notes[key] = m.group(1).strip()
    OUT.write_text(json.dumps({"meta": {"table": TABLE, "api": API, "page": PAGE, "years": years,
                                        "built": date.today().isoformat(), **notes},
                               "rows": rows}, ensure_ascii=False, separators=(",", ":")))
    print(OUT, OUT.stat().st_size // 1024, "KiB", len(rows), "areas", years, notes)


if __name__ == "__main__":
    main()
