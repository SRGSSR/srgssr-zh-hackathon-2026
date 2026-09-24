"""Jurisdiction resolver: free text place/address/postcode -> official municipality (BFS no.) and canton.

Source: swisstopo / geo.admin.ch federal geodata API (official municipal boundaries swissBOUNDARIES3D).
"""

from __future__ import annotations

import re
import unicodedata

from . import registry
from .core import cite, fetch

SEARCH = "https://api3.geo.admin.ch/rest/services/api/SearchServer"
IDENTIFY = "https://api3.geo.admin.ch/rest/services/api/MapServer/identify"
BOUNDARY_LAYER = "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"


SOURCE = cite(
    "swissBOUNDARIES3D municipal boundaries via geo.admin.ch API",
    "https://api3.geo.admin.ch/services/sdiservices.html",
    "Federal Office of Topography swisstopo",
    "federal",
)


def _norm(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _strip_canton(label: str) -> tuple[str, str | None]:
    label = re.sub(r"<[^>]+>", "", label).strip()
    m = re.match(r"^(.*?)\s*\(([A-Z]{2})\)\s*$", label)
    return (m.group(1), m.group(2)) if m else (label, None)


def municipality_at(lat: float, lon: float) -> dict | None:
    data = fetch(
        IDENTIFY,
        params={
            "geometryType": "esriGeometryPoint", "geometry": f"{lon},{lat}", "sr": "4326",
            "layers": f"all:{BOUNDARY_LAYER}", "tolerance": "0", "returnGeometry": "false", "lang": "de",
        },
        ttl=30 * 86400,
    )
    for r in data.get("results", []):
        a = r["attributes"]
        if a.get("is_current_jahr") and a.get("objektart_lookup") in ("gemeindegebiet", "politische_gemeinde"):
            return _muni(a["gemname"], a["kanton"], a["gde_nr"])
    return None


def _muni(name: str, canton: str, bfs: int) -> dict:
    c = registry.cantons().get(canton, {})
    out = {
        "municipality": name, "bfs_nr": int(bfs), "canton": canton, "canton_name": c.get("name", canton),
        "official_languages_canton": c.get("languages", []),
        "canton_website": f"https://www.{c['domain']}" if c.get("domain") else None,
    }
    m = registry.municipality(bfs)
    if m:
        out["municipality_website"] = m["website"]
    return out


def _search(text: str, origins: str | None = None, limit: int = 8) -> list[dict]:
    params = {"searchText": text, "type": "locations", "limit": str(limit), "sr": "4326"}
    if origins:
        params["origins"] = origins
    return [r["attrs"] for r in fetch(SEARCH, params=params, ttl=7 * 86400).get("results", [])]


def locate(query: str) -> dict:
    """Resolve a Swiss place. Returns status resolved | ambiguous | not_found."""
    q = query.strip()
    nq = _norm(q)
    looks_like_address = bool(re.search(r"[a-zA-Z]", q) and re.search(r"\d", q)) and not re.fullmatch(r"\d{4}", q)

    # 1) Official municipality name (gg25). Exact name match only; the search itself is fuzzy.
    tiers: list[dict[int, dict]] = [{}, {}, {}]  # full name, one half of a bilingual name, prefix
    for a in _search(q, "gg25"):
        name, canton = _strip_canton(a["label"])
        bfs = int(a["featureId"])
        if _norm(name) == nq or _norm(f"{name} {canton}") == nq:
            tier = 0
        elif nq in [_norm(p) for p in name.split("/")]:  # Biel/Bienne
            tier = 1
        elif _norm(name).startswith(nq + " "):
            tier = 2
        else:
            continue
        tiers[tier].setdefault(bfs, _muni(name, canton, bfs))
    munis = list(next((t for t in tiers if t), {}).values())
    if len(munis) == 1:
        return {"status": "resolved", "match_type": "municipality", **munis[0], "sources": [SOURCE]}
    if len(munis) > 1:
        return {
            "status": "ambiguous",
            "question_for_user": f"Several Swiss municipalities are called '{q}'. Which one is meant?",
            "candidates": munis, "sources": [SOURCE],
        }

    # 2) Postcode or street address -> point -> municipality polygon.
    if re.fullmatch(r"\d{4}", q) or looks_like_address:
        hits = _search(q, "zipcode" if re.fullmatch(r"\d{4}", q) else "address", limit=5)
        seen: dict[int, dict] = {}
        for a in hits:
            if re.fullmatch(r"\d{4}", q) and not _norm(a["label"]).startswith(q):
                continue
            m = municipality_at(a["lat"], a["lon"])
            if m:
                label = re.sub(r"<[^>]+>", "", a["label"])
                plz = re.search(r"\b(\d{4})\b", label)
                seen.setdefault(m["bfs_nr"], {**m, "matched": label, "postcode": plz.group(1) if plz else None})
            if not re.fullmatch(r"\d{4}", q):
                break  # best address hit is enough
        if len(seen) == 1:
            return {"status": "resolved", "match_type": "postcode" if q.isdigit() else "address",
                    **next(iter(seen.values())), "sources": [SOURCE]}
        if len(seen) > 1:
            return {"status": "ambiguous",
                    "question_for_user": f"Postcode {q} spans several municipalities. Which one?",
                    "candidates": list(seen.values()), "sources": [SOURCE]}

    # 3) Named locality/village inside a municipality (gazetteer, type "Ort").
    for a in _search(q, "gazetteer"):
        kind = re.search(r"<i>(.*?)</i>", a["label"])
        name = re.search(r"<b>(.*?)</b>", a["label"], re.S)
        if kind and kind.group(1) == "Ort" and name and _norm(name.group(1)) == nq:
            m = municipality_at(a["lat"], a["lon"])
            if m:
                return {"status": "resolved", "match_type": "locality", "locality": q, **m,
                        "note": f"'{q}' is a locality within the municipality of {m['municipality']}.",
                        "sources": [SOURCE]}

    return {
        "status": "not_found",
        "message": (
            f"'{q}' is not a municipality, postcode or locality in the official Swiss federal gazetteer. "
            "If this place is outside Switzerland, the question is out of scope for this server; "
            "do not answer it with Swiss rules."
        ),
        "sources": [SOURCE],
    }
