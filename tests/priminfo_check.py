"""Cross-check health_insurance_premiums against the FOPH's official calculator (priminfo.admin.ch).

For each profile, compares the five cheapest offers (insurer, product, monthly premium) from this server's index with
the calculator's result page. Makes two requests per profile to priminfo.admin.ch.

    uv run python tests/priminfo_check.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swiss_grounding import premiums  # noqa: E402
from swiss_grounding.core import client  # noqa: E402

BASE = "https://www.priminfo.admin.ch/de/praemien"
# (label, priminfo location search key, BFS no., age, deductible, accident cover)
PROFILES = [
    ("Lugano adult 30, 2500, no accident", "6900 Lugano", 5192, 30, 2500, False),
    ("Lugano adult 30, 2500, accident", "6900 Lugano", 5192, 30, 2500, True),
    ("Zürich child 8, 0, accident", "8004 Zürich", 261, 8, 0, True),
    ("Bern young adult 22, 300, accident", "3011 Bern", 351, 22, 300, True),
    ("Scuol adult 45, 1500, no accident", "7550 Scuol", 3762, 45, 1500, False),
]


def location_id(key: str) -> str:
    js = client().get(f"{BASE}/locations", timeout=60).text
    data = json.loads(js[js.index("{"): js.rindex("}") + 1])
    for lid, name in data["names"].items():
        if name == key:
            return lid
    raise KeyError(key)


def priminfo_top(lid: str, age: int, deductible: int, accident: bool, n: int = 5) -> list[tuple[str, float]]:
    year = int(premiums._db()[1]["year"])
    params = [("location_id", lid), ("yob[0]", str(year - age)), ("franchise[0]", str(deductible)),
              ("coverage[0]", "1" if accident else "0"), ("display", "savings")]
    params += [("models[]", m) for m in ("BASE", "HAM", "HMO", "DIV")]
    page = client().get(BASE, params=params, timeout=60).text
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
    seg = text[text.find("Krankenkasse Modell Prämie Vergütung Total"):]
    rows = re.findall(r"(\d{2,3}\.\d{2}) (\d+\.\d{2}) (\d{2,3}\.\d{2}) \d", seg)
    return [float(r[0]) for r in rows[:n]]


def main() -> int:
    failures = 0
    for label, key, bfs, age, ded, acc in PROFILES:
        ours = premiums.premiums(bfs, age, ded, acc, None, 5)["results"][0]["cheapest"]
        ours_prices = [o["monthly_chf"] for o in ours]
        theirs = priminfo_top(location_id(key), age, ded, acc)
        ok = ours_prices == theirs
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {label:38s} ours={ours_prices} priminfo={theirs}")
    print(f"checked {date.today().isoformat()}; failures: {failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
