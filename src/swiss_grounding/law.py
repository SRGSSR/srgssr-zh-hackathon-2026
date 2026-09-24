"""Federal law (Fedlex): identify an act and article, the version in force, upcoming versions, official link.

Act metadata comes from a prebuilt index (scripts/build_fedlex_acts.py) and the Fedlex SPARQL endpoint. Article
text lives in fedlex.data.admin.ch/filestore, which robots.txt disallows for bots: it is only fetched when
SGM_RESPECT_ROBOTS=false.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from functools import lru_cache

from . import registry
from .core import CONFIG, SourceBlocked, cite, fetch, robots_allowed

ENDPOINT = "https://fedlex.data.admin.ch/sparqlendpoint"
LANG_CODES = {"de": "DEU", "fr": "FRA", "it": "ITA", "rm": "ROH", "en": "ENG"}
SR_RE = re.compile(r"^\d{3}(\.\d+)*$")


@lru_cache(maxsize=1)
def _acts() -> dict:
    return json.loads((CONFIG.data_dir / "fedlex_acts.json").read_text(encoding="utf-8"))


def _sparql(query: str, ttl: int = 86400) -> list[dict]:
    data = fetch(ENDPOINT, params={"query": query}, ttl=ttl, headers={"Accept": "application/sparql-results+json"})
    return data["results"]["bindings"]


@lru_cache(maxsize=1)
def abbreviations() -> frozenset[str]:
    return frozenset(x for v in _acts()["acts"].values() for x in v["short"].values())


@lru_cache(maxsize=1)
def sr_numbers() -> frozenset[str]:
    return frozenset(v["sr"] for v in _acts()["acts"].values())


def resolve_act(act: str, lang: str) -> list[tuple[str, dict]]:
    """Candidates for an act given as SR number, abbreviation (OR, CO, KVG, LAMal) or title words."""
    acts = _acts()["acts"]
    a = act.strip().removeprefix("SR ").strip()
    if SR_RE.match(a):
        return [(eli, v) for eli, v in acts.items() if v["sr"] == a]
    exact = [(eli, v) for eli, v in acts.items() if a in v["short"].values()]
    if exact:  # prefer the abbreviation in the user's language (CO = Code des obligations in fr/it)
        own = [(eli, v) for eli, v in exact if v["short"].get(lang) == a]
        return own or exact
    words = [w for w in registry.norm(a).split() if len(w) >= 3]
    scored = []
    for eli, v in acts.items():
        title = registry.norm(v["title"].get(lang) or v["title"].get("de", ""))
        hits = sum(1 for w in words if w in title)
        if words and hits == len(words):
            scored.append((len(title), eli, v))  # shorter titles = more general acts first
    return [(eli, v) for _, eli, v in sorted(scored)[:5]]


def _article_id(article: str) -> tuple[str, str]:
    """'266c', 'Art. 266 c', '335c' -> ('art_266_c', '266c')."""
    m = re.match(r"(?i)^\s*(?:art\.?|artikel|article|articolo)?\s*(\d+)\s*([a-z]{0,6})\s*$", article.strip())
    if not m:
        raise ValueError(article)
    num, suffix = m.group(1), m.group(2).lower()
    return (f"art_{num}_{suffix}" if suffix else f"art_{num}"), f"{num}{suffix}"


def _versions(eli: str) -> list[dict]:
    rows = _sparql(f"""
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?cons ?from ?to WHERE {{
  ?cons jolux:isMemberOf <https://fedlex.data.admin.ch/eli/{eli}> ; jolux:dateApplicability ?from .
  OPTIONAL {{ ?cons jolux:dateEndApplicability ?to }}
}} ORDER BY ?from""")
    return [{"version": r["cons"]["value"].rsplit("/", 1)[-1], "from": r["from"]["value"],
             "to": r.get("to", {}).get("value")} for r in rows]


def _html_file(eli: str, version: str, lang: str) -> str | None:
    rows = _sparql(f"""
PREFIX jolux: <http://data.legilux.public.lu/resource/ontology/jolux#>
SELECT ?file WHERE {{
  <https://fedlex.data.admin.ch/eli/{eli}/{version}/{lang}/html> jolux:isExemplifiedBy ?file }}""", ttl=7 * 86400)
    return rows[0]["file"]["value"] if rows else None


def _clean(fragment: str) -> str:
    fragment = re.sub(r"(?is)<sup[^>]*>.*?</sup>", "", fragment)  # footnote markers
    fragment = re.sub(r"(?i)</p>|<br\s*/?>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*", "\n", text)).strip()


def law(act: str, article: str | None, query: str | None, lang: str) -> dict:
    lang = lang if lang in LANG_CODES else "de"
    cands = resolve_act(act, lang)
    if not cands:
        return {"status": "not_found", "message": f"No federal act in force matches '{act}' (SR number, "
                "abbreviation such as OR/CO/KVG, or title words). Cantonal law is not covered."}
    if len(cands) > 1 and not SR_RE.match(act.strip()):
        return {"status": "ambiguous", "question_for_user": "Which act is meant?",
                "candidates": [{"sr": v["sr"], "abbreviation": v["short"].get(lang) or v["short"].get("de"),
                                "title": v["title"].get(lang) or v["title"].get("de")} for _, v in cands[:5]]}
    eli, meta = cands[0]
    today = date.today().isoformat()
    versions = _versions(eli)
    in_force = next((v for v in reversed(versions) if v["from"] <= today and (not v["to"] or v["to"] >= today)), None)
    upcoming = [v["from"] for v in versions if v["from"] > today]
    title = meta["title"].get(lang) or meta["title"].get("de")
    abbr = meta["short"].get(lang) or meta["short"].get("de")
    page = f"https://www.fedlex.admin.ch/eli/{eli}/{lang}"
    out: dict = {
        "status": "ok", "sr": meta["sr"], "abbreviation": abbr, "title": title,
        "version_in_force": {"since": in_force["from"], "until": in_force["to"]} if in_force else None,
        "upcoming_versions_from": upcoming, "url": page,
    }
    notes = []
    if upcoming:
        notes.append(f"A new version applies from {upcoming[0]}; check whether the question concerns a date after it.")
    art_id = None
    if article:
        try:
            art_id, art_label = _article_id(article)
        except ValueError:
            return {"status": "invalid_input", "message": f"Unrecognised article '{article}' (use e.g. 266c)."}
        out["article"] = {"number": art_label, "url": f"{page}#{art_id}"}

    text_status = "not_requested"
    if in_force and (article or query):
        file = _html_file(eli, in_force["version"], lang)
        if not file:
            text_status = "no_html_version"
        elif not robots_allowed(file):
            text_status = "blocked_by_robots"
            notes.append("Article text not retrieved: fedlex.data.admin.ch/filestore disallows automated access in "
                         "robots.txt (SGM_RESPECT_ROBOTS=true). Cite the official link; do not quote the article "
                         "from memory.")
        else:
            try:
                doc = fetch(file, as_json=False, ttl=7 * 86400)
            except SourceBlocked:
                doc = None
            if doc:
                text_status = "ok"
                articles = {m.group(1): m.group(2) for m in
                            re.finditer(r'(?is)<article id="(art_[^"]+)">(.*?)</article>', doc)}
                if art_id:
                    body = articles.get(art_id)
                    if body is None:
                        text_status = "article_not_found"
                        notes.append(f"Article {art_label} does not exist in the version in force.")
                    else:
                        out["article"]["text"] = _clean(body)[:3000]
                elif query:
                    terms = list(dict.fromkeys(w[:6] for w in registry.norm(query).split() if len(w) >= 4))
                    scored = []
                    for k, b in articles.items():
                        text = registry.norm(_clean(b))
                        distinct = sum(1 for t in terms if t in text)  # breadth of match beats repetition
                        if distinct:
                            scored.append((distinct, sum(text.count(t) for t in terms), k))
                    scored.sort(reverse=True)
                    out["matching_articles"] = [
                        {"id": k, "url": f"{page}#{k}", "text": _clean(articles[k])[:700]} for _, _, k in scored[:3]]
    out["text_status"] = text_status
    out["notes"] = notes + ["Federal law only (Classified Compilation, SR). Cantonal and municipal law is not "
                            "covered by this tool."]
    out["sources"] = [cite(f"{abbr or meta['sr']}: {title}", out.get("article", {}).get("url", page),
                           "Federal Chancellery, Fedlex (Classified Compilation SR)", "federal",
                           f"{in_force['from']}–{in_force['to'] or 'open'}" if in_force else None)]
    return out
