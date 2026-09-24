"""Build data/fedlex_acts.json: SR number, abbreviation and title of every national act in force (DE/FR/IT/RM/EN).

Source: Fedlex linked data (SPARQL endpoint of the Federal Chancellery), which robots.txt allows. International
treaties (SR 0.xxx) are left out. The law texts themselves are not downloaded: fedlex.data.admin.ch/filestore is
disallowed for bots by robots.txt.

Usage:
    uv run python scripts/build_fedlex_acts.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swiss_grounding.core import client  # noqa: E402

ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
OUT = Path(__file__).resolve().parents[1] / "data" / "fedlex_acts.json"
LANGS = {"de": "DEU", "fr": "FRA", "it": "ITA", "rm": "ROH", "en": "ENG"}
QUERY = """
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?act ?sr ?title ?short WHERE {{
  ?act a jolux:ConsolidationAbstract ; jolux:isRealizedBy ?e .
  ?e jolux:language <http://publications.europa.eu/resource/authority/language/{lang}> ;
     jolux:title ?title ; jolux:historicalLegalId ?sr .
  OPTIONAL {{ ?e jolux:titleShort ?short }}
  FILTER(!STRSTARTS(STR(?sr), "0."))
  FILTER NOT EXISTS {{ ?act jolux:dateNoLongerInForce ?end . FILTER(?end <= "{today}"^^<http://www.w3.org/2001/XMLSchema#date>) }}
}}
"""


def main() -> None:
    acts: dict[str, dict] = {}
    today = date.today().isoformat()
    for lang, code in LANGS.items():
        r = client().post(ENDPOINT, data={"query": QUERY.format(lang=code, today=today)},
                          headers={"Accept": "application/sparql-results+json"}, timeout=300)
        r.raise_for_status()
        rows = r.json()["results"]["bindings"]
        for b in rows:
            eli = b["act"]["value"].removeprefix("https://fedlex.data.admin.ch/eli/")
            a = acts.setdefault(eli, {"sr": b["sr"]["value"], "title": {}, "short": {}})
            a["title"][lang] = " ".join(b["title"]["value"].split())
            if b.get("short"):
                a["short"][lang] = b["short"]["value"].strip()
        print(lang, len(rows), "rows", flush=True)
    OUT.write_text(json.dumps({"meta": {"source": ENDPOINT, "built": today, "acts": len(acts)}, "acts": acts},
                              ensure_ascii=False, separators=(",", ":")))
    print(OUT, OUT.stat().st_size // 1024, "KiB", len(acts), "acts")


if __name__ == "__main__":
    main()
