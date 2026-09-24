"""Swiss Grounding MCP server: jurisdiction-first access to authoritative Swiss public information."""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import time
from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlparse

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import geo, guidance, premiums, registry, router, sources
from .core import CONFIG, FETCH_LOG, METRICS, SourceBlocked, SourceUnavailable

log = logging.getLogger("swiss_grounding")

INSTRUCTIONS = """\
Swiss Grounding: authoritative Swiss public information (federal, cantonal, municipal) with citations.

Start with `swiss_ground(question)` whenever you are unsure which tool fits or whether the question is answerable.
It returns a decision: out_of_scope | ambiguous | needs_jurisdiction | varies_by_canton | unsupported | routed
(with a prefilled `next_call` or ch.ch evidence). Follow its `instruction` field.

Grounding policy for the assistant:
1. Jurisdiction first. If the answer depends on where the person lives (premiums, holidays, waste, taxes, offices)
   and the place is not stated ("bei uns", "chez moi", "where I live"), ask ONLY for the municipality or postcode.
   Do not ask for anything else you do not need. If the place is given, call the tool directly - tools accept
   municipality names, postcodes or addresses and resolve them via the official federal gazetteer.
2. Switzerland only. If a tool reports a place is not Swiss (status not_found from resolve_swiss_location) or the
   question concerns another country (e.g. Konstanz/Germany, France), say clearly that it is outside Switzerland
   and outside this server's scope. Do not answer with Swiss rules, and do not fill in the foreign answer from
   memory either (no amounts, dates or rules): unverified figures are guesses. You may name the kind of authority
   responsible abroad, without facts.
3. Cite. Every result carries `sources` (url, publisher, level, validity). Cite them and state the reference
   year/date. Prefer federal/cantonal/municipal sources over 'aggregator' or 'unverified' ones and say when a
   source is non-official.
4. Honest failure. status not_found / unavailable / blocked / not_published means: say you could not verify it and
   point to the cited official page. Never fill gaps from memory.
5. Answer in the user's language (de, fr, it, rm, en). Pass `language` to tools when available.
6. Freshness. If a source is marked `freshness: stale`, say when it was last updated and that rules may have changed.
For procedures (moving, permits, driving licence, unemployment, AHV, taxes, customs ...) use search_swiss_guidance,
then read_official_page on the cantonal/municipal authority link it returns.
"""

mcp = MCPServer(
    name="swiss-grounding",
    title="Swiss Grounding MCP",
    instructions=INSTRUCTIONS,
    version="0.1.0",
)

RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
Lang = Literal["de", "fr", "it", "rm", "en"]


def tool(fn):
    """Register a read-only tool with metrics and uniform honest error envelopes.

    Results are returned as compact JSON text (no indentation, no duplicate structured copy) to save tokens.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        token = FETCH_LOG.set([])
        try:
            result = _call(*args, **kwargs)
            if isinstance(result, dict):
                _attach_provenance(result, FETCH_LOG.get() or [])
        finally:
            FETCH_LOG.reset(token)
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)

    def _call(*args, **kwargs):
        name = fn.__name__
        METRICS.calls[name] = METRICS.calls.get(name, 0) + 1
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        except SourceBlocked as e:
            METRICS.errors[name] = METRICS.errors.get(name, 0) + 1
            return {"status": "blocked", "message": f"{e}. The source's robots.txt forbids automated access; "
                    "tell the user to consult the source directly. Operators can set SGM_RESPECT_ROBOTS=false."}
        except SourceUnavailable as e:
            METRICS.errors[name] = METRICS.errors.get(name, 0) + 1
            return {"status": "unavailable", "message": f"Authoritative source unreachable ({e}) and no cached copy "
                    "exists. This is a retrieval failure, not evidence that the information does not exist. Do not "
                    "guess or substitute another source/jurisdiction; tell the user it could not be verified right now."}
        finally:
            log.info("tool=%s ms=%d", name, (time.perf_counter() - t0) * 1000)

    wrapper.__annotations__ = {**fn.__annotations__, "return": str}
    return mcp.tool(annotations=RO, structured_output=False)(wrapper)


def _attach_provenance(result: dict, events: list[dict]) -> None:
    """Disclose cached evidence: stale fallbacks get an explicit warning, cache hits a data_as_of timestamp."""
    stale = {(e["host"], e["fetched_at"]) for e in events if e["origin"] == "stale_cache"}
    if stale:
        result["served_from_cache"] = [{"host": h, "retrieved": t} for h, t in sorted(stale)]
        result.setdefault("notes", []).append(
            "The live source was unreachable; this answer uses a cached copy (see served_from_cache for the "
            "retrieval date). Tell the user the data may be outdated.")
    # Jurisdiction lookups (geo.admin.ch) are not evidence; only date the evidence sources.
    cached = [e["fetched_at"] for e in events
              if e["origin"] in ("cache", "stale_cache") and e["host"] != "api3.geo.admin.ch"]
    if cached:
        result["data_as_of"] = min(cached)
    # A citation's `retrieved` must be when the data was actually fetched, not when it was served.
    fetched = {}
    for e in events:
        fetched[e["host"]] = min(fetched.get(e["host"], e["fetched_at"]), e["fetched_at"])
    for src in result.get("sources", []) or []:
        host = urlparse(src.get("url", "")).netloc
        if host in fetched:
            src["retrieved"] = fetched[host]


def _resolve(place: str) -> tuple[dict | None, dict | None]:
    """Returns (municipality, early_response). early_response is set when the caller must stop."""
    p = place.strip()
    if p.isdigit() and len(p) != 4:  # BFS municipality number (4-digit numbers are postcodes)
        row = premiums._db()[0].execute("SELECT municipality, canton FROM regions WHERE bfs=? LIMIT 1", (int(p),)).fetchone()
        if not row:
            return None, {"status": "not_found", "message": f"No Swiss municipality with BFS number {p}."}
        return geo._muni(row[0], row[1], int(p)), None
    r = geo.locate(place)
    if r["status"] == "resolved":
        return r, None
    return None, r


# ----------------------------------------------------------------------------------------------- tools


@tool
def swiss_ground(
    question: Annotated[str, Field(description="The user's question, verbatim, in any language (de/fr/it/rm/en)")],
    place: Annotated[str | None, Field(description="Municipality/postcode/address if already known from the conversation")] = None,
    language: Annotated[Lang | None, Field(description="Answer language; detected from the question if omitted")] = None,
) -> dict:
    """Start here for any question about Switzerland. Detects topic, jurisdiction (municipality/canton) and foreign
    places, then decides: out_of_scope (not Switzerland), ambiguous / needs_jurisdiction (ask the user exactly the
    returned question_for_user), varies_by_canton (no single Swiss rule), unsupported (no authoritative source), or
    routed (authority chain + prefilled next_call to the right data tool, or ch.ch evidence with URLs)."""
    return router.ground(question, place, language)


@tool
def resolve_swiss_location(
    place: Annotated[str, Field(description="Municipality, locality, 4-digit postcode or street address in Switzerland")],
) -> dict:
    """Resolve a place to its official Swiss municipality (BFS number), canton and canton languages.

    Use to check jurisdiction before answering, or to detect places outside Switzerland (status not_found)
    and ambiguous names (status ambiguous -> ask the user which one). Source: swisstopo federal gazetteer.
    """
    return geo.locate(place)


@tool
def health_insurance_premiums(
    place: Annotated[str, Field(description="Municipality, postcode or address of residence (or BFS number)")],
    age: Annotated[int, Field(ge=0, le=120, description="Age of the insured person in years")],
    deductible: Annotated[int, Field(description="Annual deductible (Franchise/franchise/franchigia) in CHF. "
                                     "Adults: 300,500,1000,1500,2000,2500. Children: 0-600 in steps of 100")],
    accident_cover: Annotated[bool | None, Field(description="Include accident cover. Omit if unknown: both variants are returned")] = None,
    model: Annotated[Literal["standard", "family_doctor", "hmo", "telmed_other"] | None,
                     Field(description="Restrict to an insurance model; omit for all models")] = None,
    limit: Annotated[int, Field(ge=1, le=20)] = 5,
) -> dict:
    """Official monthly premiums for Swiss mandatory basic health insurance (KVG/LAMal/LAMal) for one person.

    Returns the cheapest offers (insurer, model, product, CHF/month), the cheapest standard-model offer, median
    and maximum, for the person's premium region. Data: FOPH/BAG approved premiums (current premium year).
    """
    muni, early = _resolve(place)
    if early:
        return early
    m = {"standard": "TAR-BASE", "family_doctor": "TAR-HAM", "hmo": "TAR-HMO", "telmed_other": "TAR-DIV"}.get(model or "")
    return premiums.premiums(muni["bfs_nr"], age, deductible, accident_cover, m, limit)


@tool
def school_holidays(
    place: Annotated[str, Field(description="Municipality or postcode (school holidays can differ per municipality)")],
    year: Annotated[int | None, Field(description="Calendar year; default current year")] = None,
    language: Lang = "de",
) -> dict:
    """School holiday periods (Schulferien/vacances scolaires/vacanze scolastiche) for a Swiss municipality."""
    muni, early = _resolve(place)
    if early:
        return early
    lang = language if language in ("de", "fr", "it", "en") else "de"  # dataset has no Romansh labels
    r = sources.school_holidays(muni["canton"], muni["municipality"], None, year or date.today().year, lang)
    if language == "rm":
        r.setdefault("notes", []).append("Holiday names are given in German; the dataset has no Romansh labels.")
    return r


@tool
def waste_collection(
    place: Annotated[str, Field(description="Postcode or street address (collection days differ by postcode)")],
    material: Annotated[str | None, Field(description="e.g. Karton/carton, Papier, Kehricht, Bioabfall, Sonderabfall; omit for all")] = None,
    from_date: Annotated[str | None, Field(description="'YYYY-MM-DD', default today")] = None,
    limit: Annotated[int, Field(ge=1, le=10)] = 3,
) -> dict:
    """Next waste collection dates (cardboard, paper, household waste, organic, hazardous-waste mobile) from the
    official municipal calendar. Covered: City of Zürich. Other municipalities return not_covered + their website."""
    muni, early = _resolve(place)
    if early:
        return early
    return sources.waste_collection(muni, material, from_date, limit)


@tool
def public_transport_connections(
    origin: Annotated[str, Field(description="Departure station/stop or address, e.g. 'Zürich HB'")],
    destination: Annotated[str, Field(description="Arrival station/stop or address, e.g. 'Bellinzona'")],
    when: Annotated[str | None, Field(description="'YYYY-MM-DD HH:MM' or 'HH:MM' local time; default now")] = None,
    arrive_by: Annotated[bool, Field(description="Interpret `when` as latest arrival time")] = False,
    limit: Annotated[int, Field(ge=1, le=6)] = 3,
) -> dict:
    """Next public transport connections in Switzerland (train, bus, tram, boat) from the official timetable."""
    return sources.connections(origin, destination, when, arrive_by, limit)


@tool
def federal_votes(
    vote_date: Annotated[str | None, Field(description="Voting Sunday 'YYYY-MM-DD'; omit for the next upcoming vote")] = None,
    language: Lang = "de",
) -> dict:
    """Swiss federal popular votes: subjects of the next (or a given) voting date and official results."""
    return sources.federal_votes(vote_date, language)


@tool
def reference_interest_rate(language: Lang = "de") -> dict:
    """Current Swiss mortgage reference interest rate for rents (hypothekarischer Referenzzinssatz / taux de
    référence / tasso di riferimento): rate, valid-since date, last confirmation and next publication date,
    with the exact supporting sentence from the Federal Office for Housing."""
    return sources.reference_rate(language if language in ("de", "fr", "it") else "de")


@tool
def municipality_population(
    place: Annotated[str | None, Field(description="Municipality, postcode or address (or BFS number)")] = None,
    canton: Annotated[str | None, Field(description="Two-letter canton code (e.g. VS) for canton-level figures only")] = None,
) -> dict:
    """Permanent resident population of a Swiss municipality on 31 December of the latest year (FSO STATPOP), with
    the previous year, change, share of foreign nationals, and the same figures for its canton and Switzerland.
    Pass `canton` instead of `place` for a canton's figures."""
    if not place:
        code = (canton or "").strip().upper()
        if code not in registry.cantons():
            return {"status": "invalid_input", "message": "Give a municipality (place) or a two-letter canton code."}
        return sources.canton_population(code)
    muni, early = _resolve(place)
    if early:
        return early
    return sources.population(muni)


@tool
def search_swiss_guidance(
    query: Annotated[str, Field(description="Keywords in the user's language, e.g. 'ausländischer Führerausweis umtauschen'")],
    language: Annotated[Lang | None, Field(description="Preferred page language")] = None,
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict:
    """Search ch.ch (official portal of Swiss authorities, all 5 languages) for procedures and rights:
    moving and registration, permits, driving licences, taxes, AHV/pensions, unemployment, family, customs,
    vehicles, housing, voting. Returns relevant sections with URLs plus links to the responsible cantonal/federal
    authority pages (read those with read_official_page for canton-specific rules)."""
    return guidance.search(query, language, limit)


@tool
def read_official_page(
    url: Annotated[str, Field(description="URL of a Swiss authority page (admin.ch, ch.ch, canton or municipality)")],
    focus: Annotated[str | None, Field(description="Keywords to extract only the relevant sections")] = None,
    max_chars: Annotated[int, Field(ge=500, le=12000)] = 3500,
) -> dict:
    """Fetch an official Swiss web page and return its relevant sections, links and an authority label
    (federal/cantonal/semi-official/unverified). Only Swiss domains are read. Respects robots.txt by default."""
    return guidance.read_page(url, focus, max_chars)


@tool
def company_register_search(
    name: Annotated[str, Field(description="Company name or part of it")],
    active_only: bool = True,
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict:
    """Look up companies in the Swiss commercial register index (Zefix): name, UID, seat, legal form, status."""
    return sources.company_search(name, active_only, limit)


@tool
def server_coverage() -> dict:
    """Declared scope, data freshness, configuration and runtime health of this server. Call when unsure whether
    a question is covered."""
    con, meta = premiums._db()
    return {
        "scope": {
            "geography": "Switzerland only (all 26 cantons, all municipalities via the federal gazetteer).",
            "covered": {
                "jurisdiction": "place/postcode/address -> municipality, BFS no., canton (swisstopo)",
                "health_insurance": f"all approved KVG premiums {meta['year']}, all municipalities (FOPH)",
                "school_holidays": "all cantons, municipality level where published (OpenHolidays aggregator)",
                "public_transport": "Swiss timetable connections (opentransportdata.swiss)",
                "federal_votes": "subjects and results of federal votes 2025-2026 (FSO / Federal Chancellery)",
                "procedures": "ch.ch citizen portal, ~350 topics x 5 languages, plus linked cantonal pages",
                "population": "permanent resident population per municipality/canton, 31.12 of latest year (FSO STATPOP, prebuilt)",
                "reference_rate": "current mortgage reference interest rate for rents (FOH/BWO, live)",
                "waste_collection": "City of Zürich official collection calendar by postcode (ERZ open data)",
                "router": f"swiss_ground: {len(registry.topics())} topics, 26 cantons, "
                          f"{len(registry.registry().get('municipalities', {}))} municipal websites in the source registry",
                "companies": "Zefix commercial register index (blocked when robots.txt is respected)",
            },
            "not_covered": [
                "Countries other than Switzerland", "tax calculations", "waste calendars outside the City of Zürich",
                "legal advice / full law texts (Fedlex articles only via read_official_page)",
                "weather and statistics other than municipal population",
                "non-public or personal data",
            ],
        },
        "config": {"respect_robots": CONFIG.respect_robots, "cache": CONFIG.cache_enabled, "ipv4_only": CONFIG.ipv4_only},
        "data": {
            "premium_index": meta,
            "chch_index": (dict(guidance._index().execute("SELECT key, value FROM meta"))
                           if guidance._index() is not None else None),
            "population": {k: v for k, v in sources._population_snapshot()["meta"].items()
                           if k in ("years", "built", "reference_date", "database_state", "boundaries_as_of")},
        },
        "health": METRICS.snapshot(),
    }


# ----------------------------------------------------------------------------------------------- entry


def main() -> None:
    ap = argparse.ArgumentParser(description="Swiss Grounding MCP server")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default=os.getenv("SGM_TRANSPORT", "stdio"))
    ap.add_argument("--host", default=os.getenv("SGM_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", os.getenv("SGM_PORT", "8000"))))
    args = ap.parse_args()
    logging.basicConfig(level=os.getenv("SGM_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        from mcp.server.transport_security import TransportSecuritySettings

        hosts = [h.strip() for h in os.getenv("SGM_ALLOWED_HOSTS", "").split(",") if h.strip()]
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts, allowed_origins=[])
        mcp.run("streamable-http", host=args.host, port=args.port, stateless_http=True,
                json_response=True, transport_security=security)


if __name__ == "__main__":
    main()
