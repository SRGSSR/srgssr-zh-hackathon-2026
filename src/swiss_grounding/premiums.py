"""Mandatory health insurance (OKP/LAMal/KVG) premiums from the official BAG dataset (prebuilt index)."""

from __future__ import annotations

import sqlite3
import statistics
from functools import lru_cache

from .core import CONFIG, cite

MODELS = {
    "TAR-BASE": "standard model (free choice of doctor)",
    "TAR-HAM": "family-doctor model (Hausarzt)",
    "TAR-HMO": "HMO model",
    "TAR-DIV": "other alternative model (e.g. telemedicine)",
}
ADULT_FRANCHISES = [300, 500, 1000, 1500, 2000, 2500]
CHILD_FRANCHISES = [0, 100, 200, 300, 400, 500, 600]


@lru_cache(maxsize=1)
def _db() -> tuple[sqlite3.Connection, dict]:
    files = sorted(CONFIG.data_dir.glob("premiums_*.sqlite"))
    if not files:
        raise FileNotFoundError("premium index missing: run scripts/build_premiums.py")
    con = sqlite3.connect(f"file:{files[-1]}?mode=ro", uri=True, check_same_thread=False)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    return con, meta


def premiums(bfs_nr: int, age: int, franchise: int, accident: bool | None, model: str | None, limit: int) -> dict:
    con, meta = _db()
    year = meta["year"]
    src = [
        cite(f"BAG premium data {year} (opendata.swiss 'health-insurance-premiums')",
             "https://opendata.swiss/de/dataset/health-insurance-premiums",
             "Federal Office of Public Health FOPH/BAG", "federal", f"01.01.{year}-31.12.{year}"),
        cite("Official premium calculator Priminfo", "https://www.priminfo.admin.ch/",
             "Federal Office of Public Health FOPH/BAG", "federal"),
    ]
    reg = con.execute("SELECT municipality, canton, region FROM regions WHERE bfs=? LIMIT 1", (bfs_nr,)).fetchone()
    if not reg:
        return {"status": "not_found", "message": f"BFS no. {bfs_nr} not in BAG premium regions {year}.", "sources": src}
    muni, canton, region = reg

    if age <= 18:
        age_class, allowed = "AKL-KIN", CHILD_FRANCHISES
    elif age <= 25:
        age_class, allowed = "AKL-JUG", ADULT_FRANCHISES
    else:
        age_class, allowed = "AKL-ERW", ADULT_FRANCHISES
    if franchise not in allowed:
        return {"status": "invalid_input",
                "message": f"Deductible {franchise} does not exist for this age. Allowed: {allowed} CHF.", "sources": src}

    def query(acc: int) -> dict:
        sql = """SELECT p.insurer, COALESCE(i.name, 'BAG-Nr '||p.insurer), p.tariff_type, p.tariff_name, p.premium
                 FROM premiums p LEFT JOIN insurers i ON i.id=p.insurer
                 WHERE p.canton=? AND p.region IN (?, 0) AND p.age_class=? AND p.franchise=? AND p.accident=?
                   AND (p.age_sub IS NULL OR p.age_sub IN ('K1',''))
                   AND (NOT EXISTS (SELECT 1 FROM restricted x
                          WHERE x.insurer=p.insurer AND x.canton=p.canton AND x.region=p.region AND x.tariff=p.tariff)
                        OR EXISTS (SELECT 1 FROM restricted x
                          WHERE x.insurer=p.insurer AND x.canton=p.canton AND x.region=p.region AND x.tariff=p.tariff
                            AND x.bfs=?))"""
        args: list = [canton, region, age_class, franchise, acc, bfs_nr]
        if model:
            sql += " AND p.tariff_type=?"
            args.append(model)
        rows = con.execute(sql + " ORDER BY p.premium", args).fetchall()
        prices = [r[4] for r in rows]
        base = next((r for r in rows if r[2] == "TAR-BASE"), None)
        return {
            "accident_cover_included": bool(acc),
            "offers_count": len(rows),
            "cheapest": [
                {"insurer": r[1], "model": MODELS.get(r[2], r[2]), "product": r[3], "monthly_chf": r[4]}
                for r in rows[:limit]
            ],
            "cheapest_standard_model": (
                {"insurer": base[1], "product": base[3], "monthly_chf": base[4]} if base else None
            ),
            "median_monthly_chf": round(statistics.median(prices), 2) if prices else None,
            "most_expensive_monthly_chf": prices[-1] if prices else None,
        }

    variants = [int(accident)] if accident is not None else [1, 0]
    return {
        "status": "ok",
        "premium_year": int(year),
        "municipality": muni, "bfs_nr": bfs_nr, "canton": canton, "premium_region": region,
        "age_group": {"AKL-KIN": "0-18", "AKL-JUG": "19-25", "AKL-ERW": "26+"}[age_class],
        "deductible_chf": franchise,
        "results": [query(a) for a in variants],
        "notes": [
            "Monthly gross premiums in CHF for mandatory basic insurance (KVG/LAMal), as approved by the FOPH; they "
            "match the 'Prämie' column of the official calculator priminfo.admin.ch.",
            "Priminfo also shows a yearly refund ('Vergütung': environmental levy, for some insurers also a reserve "
            "reduction) that lowers the net amount paid; it is not included here. See priminfo.admin.ch for the net total.",
            "Employees working >= 8 h/week for one employer are covered for accidents by UVG and can exclude accident cover.",
            f"Premiums for {int(year) + 1} are published by the FOPH at the end of September {year}; "
            "a notice to switch insurer must reach the current insurer by 30 November (KVG Art. 7).",
        ],
        "sources": src,
    }
