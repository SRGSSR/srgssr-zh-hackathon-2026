"""Live connectors: public transport, school holidays, federal votes, commercial register, waste (Zürich)."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, datetime

from . import registry
from .core import SourceUnavailable, cite, fetch

# --------------------------------------------------------------------------- public transport

TRANSPORT_API = "https://transport.opendata.ch/v1/connections"
TRANSPORT_SRC = cite(
    "Swiss public transport timetable (transport.opendata.ch, based on opentransportdata.swiss)",
    "https://opentransportdata.swiss/", "Open data platform mobility Switzerland (FOT/BAV mandate)", "semi-official",
)


def _hhmm(ts: str | None) -> str | None:
    return ts[11:16] if ts else None


def connections(origin: str, destination: str, when: str | None, arrive_by: bool, limit: int) -> dict:
    params = {"from": origin, "to": destination, "limit": str(limit)}
    if when:
        d, _, t = when.partition("T" if "T" in when else " ")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            params["date"] = d
            if t:
                params["time"] = t[:5]
        else:
            params["time"] = when[:5]
    if arrive_by:
        params["isArrivalTime"] = "1"
    data = fetch(TRANSPORT_API, params=params, ttl=60)
    out = []
    for c in data.get("connections", []):
        legs = []
        for s in c.get("sections", []):
            j = s.get("journey")
            if j:
                legs.append({
                    "line": f"{j.get('category', '')}{j.get('number', '')}".strip() or j.get("name"),
                    "from": s["departure"]["station"]["name"], "dep": _hhmm(s["departure"]["departure"]),
                    "platform": s["departure"].get("platform"),
                    "to": s["arrival"]["station"]["name"], "arr": _hhmm(s["arrival"]["arrival"]),
                    "direction": j.get("to"),
                })
            elif s.get("walk"):
                legs.append({"walk_min": round((s["walk"].get("duration") or 0) / 60)})
        out.append({
            "date": c["from"]["departure"][:10],
            "dep": _hhmm(c["from"]["departure"]), "arr": _hhmm(c["to"]["arrival"]),
            "duration": re.sub(r"^00d", "", c.get("duration") or "")[:5],
            "transfers": c.get("transfers"), "legs": legs,
            "delay_min": (c["from"].get("delay") or None),
        })
    if not out:
        return {"status": "not_found", "message": f"No connection found for '{origin}' -> '{destination}'. "
                "Check station names (use the official station name).", "sources": [TRANSPORT_SRC]}
    return {"status": "ok", "from": data.get("from", {}).get("name"), "to": data.get("to", {}).get("name"),
            "connections": out, "sources": [TRANSPORT_SRC],
            "notes": ["Timetable data incl. real-time where available; times are local (Europe/Zurich)."]}


# --------------------------------------------------------------------------- school holidays

OH = "https://openholidaysapi.org"


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _find_subdivision(canton: str, municipality: str | None, district: str | None) -> tuple[str, str]:
    tree = fetch(f"{OH}/Subdivisions", params={"countryIsoCode": "CH", "languageIsoCode": "DE"}, ttl=7 * 86400)
    root = next((n for n in tree if n["code"] == f"CH-{canton}"), None)
    if not root:
        raise SourceUnavailable(f"canton {canton} not in holiday dataset")
    targets = [t for t in (municipality, district) if t]
    best: tuple[str, str] = (root["code"], root["name"][0]["text"])

    def walk(node, depth):
        nonlocal best
        for c in node.get("children") or []:
            names = [x["text"] for x in c["name"]] + [c.get("shortName", "")]
            if targets and any(_n(nm) == _n(targets[0]) for nm in names):
                best = (c["code"], c["name"][0]["text"])
                return True
            if walk(c, depth + 1):
                return True
        return False

    if not walk(root, 0) and len(targets) > 1:
        targets.pop(0)
        walk(root, 0)
    return best


def school_holidays(canton: str, municipality: str | None, district: str | None, year: int, lang: str) -> dict:
    code, label = _find_subdivision(canton, municipality, district)
    data = fetch(f"{OH}/SchoolHolidays", params={
        "countryIsoCode": "CH", "subdivisionCode": code, "languageIsoCode": lang.upper(),
        "validFrom": f"{year}-01-01", "validTo": f"{year}-12-31",
    }, ttl=86400)
    items = []
    for h in data:
        name = next((x["text"] for x in h["name"] if x["language"].lower() == lang.lower()), h["name"][0]["text"])
        items.append({"name": name, "start": h["startDate"], "end": h["endDate"]})
    edu = registry.cantons().get(canton, {}).get("education")
    matched_level = "municipality" if municipality and _n(label) == _n(municipality) else (
        "district/region" if code.count("-") >= 2 else "canton")
    notes = [f"Dates apply to subdivision '{label}' ({code}), matched at {matched_level} level. End dates are inclusive."]
    if matched_level != "municipality" and canton in {"GR", "ZH", "BE", "AG", "SG", "LU", "VS", "SZ", "TG"}:
        notes.append("In this canton school holidays are set locally (municipality/school community); "
                     "confirm with the municipality's school administration.")
    src = [cite("OpenHolidays school holiday data (compiled from cantonal/municipal publications)",
                "https://www.openholidaysapi.org/", "OpenHolidays project (non-official aggregator)", "aggregator")]
    if edu:
        src.append(cite(f"Cantonal education department {canton} (authoritative, verify here)", edu,
                        f"Canton {canton}", "cantonal"))
    if not items:
        return {"status": "not_found", "message": f"No school holidays published for {label} in {year}.",
                "sources": src}
    return {"status": "ok", "subdivision": label, "year": year, "holidays": items, "notes": notes, "sources": src}


# --------------------------------------------------------------------------- federal votes

VOTEINFO = "https://ogd-static.voteinfo-app.ch/v1/ogd/sd-t-17-02-{d}-eidgAbstimmung.json"
# Federal voting dates with an OGD file on opendata.swiss or a Federal Council decision (verified 2026-09-24).
FEDERAL_VOTE_DATES = [
    "2025-02-09", "2025-09-28", "2025-11-30", "2026-03-08", "2026-06-14", "2026-09-27", "2026-11-29",
]
# Subjects decided by the Federal Council but not yet in the OGD result feed.
ANNOUNCED = {
    "2026-11-29": {
        "decided": "2026-06-30",
        "url": "https://www.admin.ch/de/newnsb/KpnrPOW9cpZAvB6IXOekf",
        "titles": [
            "Bundesbeschluss vom 19. Juni 2026 über die Zusatzfinanzierung der AHV durch eine Erhöhung der Mehrwertsteuer",
            "Volksinitiative «Für eine Einschränkung von Feuerwerk»",
            "Volksinitiative «Ja zu fairen Bundessteuern auch für Ehepaare – Diskriminierung der Ehe endlich abschaffen!»",
            "Änderung vom 19. Dezember 2025 des Bundesgesetzes über das Kriegsmaterial",
        ],
    },
}
BK_SRC = cite("Federal votes (Volksabstimmungen) - Federal Chancellery", "https://www.bk.admin.ch/bk/de/home/politische-rechte/volksabstimmungen.html",
              "Federal Chancellery", "federal")


def federal_votes(on: str | None, lang: str) -> dict:
    today = date.today().isoformat()
    if on:
        target = on
    else:
        target = next((d for d in FEDERAL_VOTE_DATES if d >= today), FEDERAL_VOTE_DATES[-1])
    url = VOTEINFO.format(d=target.replace("-", ""))
    src = [BK_SRC, cite(f"Federal Statistical Office OGD vote data {target}", url, "Federal Statistical Office FSO/BFS", "federal")]
    try:
        data = fetch(url, ttl=300 if target >= today else 86400)
    except SourceUnavailable:
        nxt = [d for d in FEDERAL_VOTE_DATES if d > target][:1]
        if target in ANNOUNCED:
            a = ANNOUNCED[target]
            return {"status": "ok", "date": target, "upcoming": True, "proposals": [{"title": t} for t in a["titles"]],
                    "notes": [f"Subjects decided by the Federal Council on {a['decided']}; titles in German as published. "
                              "Results feed not yet available."],
                    "sources": [BK_SRC, cite("Federal Council press release", a["url"], "Federal Council", "federal")]}
        return {"status": "not_published", "date": target,
                "message": (f"{target} is a reserved federal voting date, but no ballot subjects are published in the "
                            "official OGD feed yet (the Federal Council fixes subjects at least 4 months ahead; "
                            "check bk.admin.ch)."),
                "next_reserved_date": nxt[0] if nxt else None, "sources": src}
    out = []
    for v in data["schweiz"]["vorlagen"]:
        title = next((t["text"] for t in v["vorlagenTitel"] if t["langKey"] == lang), v["vorlagenTitel"][0]["text"])
        res = v.get("resultat") or {}
        item = {"title": title, "counted": v.get("vorlageBeendet"), "accepted": v.get("vorlageAngenommen"),
                "double_majority_required": v.get("doppeltesMehr")}
        if res.get("jaStimmenInProzent") is not None:
            item["yes_percent"] = res["jaStimmenInProzent"]
            item["turnout_percent"] = res.get("stimmbeteiligungInProzent")
            st = v.get("staende") or {}
            if st.get("jaStaendeGanz") is not None:
                item["cantons_yes"] = st["jaStaendeGanz"] + (st.get("jaStaendeHalb") or 0) / 2
                item["cantons_no"] = st["neinStaendeGanz"] + (st.get("neinStaendeHalb") or 0) / 2
        out.append(item)
    return {"status": "ok", "date": target, "upcoming": target >= today, "data_timestamp": data.get("timestamp"),
            "proposals": out, "sources": src}


# --------------------------------------------------------------------------- commercial register

ZEFIX = "https://www.zefix.ch/ZefixREST/api/v1/firm/search.json"
LEGAL_FORMS = {1: "Einzelunternehmen", 2: "Kollektivgesellschaft", 3: "Aktiengesellschaft", 4: "GmbH",
               5: "Genossenschaft", 6: "Verein", 7: "Stiftung", 8: "Institut des öffentlichen Rechts",
               9: "Zweigniederlassung", 10: "Kommanditgesellschaft", 11: "Zweigniederlassung ausländische Gesellschaft"}


def company_search(name: str, active_only: bool, limit: int) -> dict:
    body = {"name": name, "languageKey": "de", "maxEntries": max(limit * 3, 10)}
    if active_only:
        body["activeOnly"] = True
    data = fetch(ZEFIX, json_body=body, ttl=86400)
    items = []
    for f in data.get("list", [])[:limit]:
        items.append({
            "name": f["name"], "uid": f.get("uidFormatted"), "seat": f.get("legalSeat"),
            "legal_form": LEGAL_FORMS.get(f.get("legalFormId"), f.get("legalFormId")),
            "status": f.get("status"), "last_publication_shab": f.get("shabDate"),
            "cantonal_register_excerpt": f.get("cantonalExcerptWeb"),
        })
    src = [cite("Zefix central business name index", "https://www.zefix.ch/", "Federal Office of Justice FOJ/EHRA", "federal")]
    if not items:
        return {"status": "not_found", "message": f"No entry matching '{name}' in the Swiss commercial register index.",
                "sources": src}
    return {"status": "ok", "matches": items, "sources": src,
            "notes": ["Legally binding information is the cantonal commercial register excerpt linked per entry."]}


# --------------------------------------------------------------------------- waste collection (City of Zürich)

ZH_WASTE = "https://data.stadt-zuerich.ch/dataset/entsorgungskalender_{m}/download/entsorgungskalender_{m}_{y}.csv"
ZH_MATERIALS = {
    "karton": ["karton", "carton", "cartone", "cartun", "cardboard"],
    "papier": ["papier", "altpapier", "paper", "carta"],
    "kehricht": ["kehricht", "abfall", "hauskehricht", "ordure", "dechet", "rifiuti", "spazzatura", "garbage", "waste"],
    "bioabfall": ["bioabfall", "grungut", "biodechet", "organic", "compost"],
    "sonderabfall": ["sonderabfall", "sonderabfallmobil", "dechets speciaux", "rifiuti speciali", "hazardous"],
}


def waste_material(text: str | None) -> str | None:
    t = registry.norm(text or "")
    for mat, words in ZH_MATERIALS.items():
        if any(re.search(rf"\b{w}", t) for w in words):
            return mat
    return None


def waste_collection(muni: dict, material: str | None, from_date: str | None, limit: int) -> dict:
    """Upcoming collection dates. Official data only for the City of Zürich (BFS 261), per postcode."""
    reg = registry.municipality(muni["bfs_nr"]) or {}
    if muni["bfs_nr"] != 261:
        src = [cite(f"Municipality of {muni['municipality']}", reg["website"], f"Municipality of {muni['municipality']}",
                    "municipal")] if reg.get("website") else []
        return {"status": "not_covered", "municipality": muni["municipality"], "canton": muni["canton"],
                "message": (f"Waste collection dates for {muni['municipality']} are published by the municipality and "
                            "are not covered by this server (only the City of Zürich is). Do not guess dates; refer the "
                            "user to the municipality's waste calendar."),
                "sources": src}
    plz = muni.get("postcode")
    if not plz:
        return {"status": "needs_postcode", "municipality": "Zürich",
                "question_for_user": "Collection days in the City of Zürich differ by postcode. What is your postcode (e.g. 8003)?"}
    mat = material if material in ZH_MATERIALS else waste_material(material)
    mats = [mat] if mat else ["karton", "papier", "kehricht", "bioabfall"]
    start = from_date or date.today().isoformat()
    year = int(start[:4])
    out, srcs = {}, []
    for m in mats:
        lines = []
        for y in (year, year + 1):  # next year's calendar covers late-December queries
            try:
                rows = fetch(ZH_WASTE.format(m=m, y=y), as_json=False, ttl=86400)
            except SourceUnavailable:
                if y == year:
                    raise
                continue
            lines += [l.split(",") for l in rows.splitlines()[1:] if l.strip()]
        dates, stations = [], []
        for cols in lines:
            cols = [c.strip().strip('"') for c in cols]
            if cols[0] != plz:
                continue
            d = cols[-1]
            if d >= start:
                dates.append(d)
                if m == "sonderabfall":
                    stations.append({"date": d, "station": ",".join(cols[1:-1]).strip()})
        dates.sort()
        out[m] = stations[:limit] if m == "sonderabfall" else dates[:limit]
        srcs.append(cite(f"Entsorgungskalender {m} {year} - Stadt Zürich (ERZ)",
                         f"https://data.stadt-zuerich.ch/dataset/entsorgungskalender_{m}", "City of Zürich, ERZ Entsorgung + Recycling",
                         "municipal", f"{year}"))
    srcs.append(cite("ERZ Entsorgung + Recycling Zürich", "https://www.stadt-zuerich.ch/erz", "City of Zürich", "municipal"))
    if not any(out.values()):
        return {"status": "not_found", "postcode": plz,
                "message": f"No upcoming collection dates for postcode {plz} in the {year} calendar.", "sources": srcs}
    return {"status": "ok", "municipality": "Zürich", "postcode": plz, "from": start, "next_dates": out,
            "notes": ["Dates from the official City of Zürich collection calendar for this postcode; "
                      "rules for preparing the material are on the ERZ page."],
            "sources": srcs}


# --------------------------------------------------------------------------- mortgage reference interest rate (BWO)

BWO = {"de": "https://www.bwo.admin.ch/de/referenzzinssatz", "fr": "https://www.bwo.admin.ch/fr/taux-de-reference",
       "it": "https://www.bwo.admin.ch/it/tasso-di-riferimento"}
RATE_RE = re.compile(
    r"(?:(?:Aktueller Referenzzinssatz|Taux d.intérêt de référence actuel|Tasso ipotecario di riferimento attuale)\s*:\s*)?"
    r"(\d+,\d{1,2})\s?%\s*(?:gültig seit|valable depuis le|dal)\s*(\d{2}\.\d{2}\.\d{4})"
    r"(?:,\s*(?:unverändert ab|inchangé à partir du|invariato dal)\s*(\d{2}\.\d{2}\.\d{4}))?")


def _iso_date(d: str | None) -> str | None:
    return f"{d[6:]}-{d[3:5]}-{d[:2]}" if d else None


def reference_rate(lang: str) -> dict:
    """Current mortgage reference interest rate for rents (Art. 12a VMWG), published quarterly by the FOH/BWO."""
    url = BWO.get(lang, BWO["de"])
    page = fetch(url, as_json=False, ttl=6 * 3600)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", page))))
    m = RATE_RE.search(text)
    src = [cite("Hypothekarischer Referenzzinssatz - Federal Office for Housing", url,
                "Federal Office for Housing FOH/BWO", "federal")]
    if not m:
        return {"status": "unavailable", "message": "The FOH page was retrieved but the current rate could not be "
                "extracted (page layout changed?). Do not guess; refer the user to the cited page.", "sources": src}
    # Quarterly publication dates are listed after "Publikationsdaten / Dates de publication / Date di pubblicazione".
    pub = re.search(r"(?:Publikationsdaten|Dates? de publication|Date di pubblicazione)(.{0,200})", text[m.end():])
    upcoming = [d for d in re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b", pub.group(1) if pub else "")
                if _iso_date(d) > date.today().isoformat()]
    return {
        "status": "ok",
        "reference_rate_percent": float(m.group(1).replace(",", ".")),
        "valid_since": _iso_date(m.group(2)),
        "last_confirmed": _iso_date(m.group(3)),
        "next_publication": _iso_date(upcoming[0]) if upcoming else None,
        "evidence": m.group(0).strip(),
        "notes": ["Applies to rents of residential and business premises in all of Switzerland; a change of "
                  "0.25 percentage points can justify a rent adjustment (Art. 13 VMWG)."],
        "sources": src,
    }
