"""Procedural guidance: search the prebuilt ch.ch index and read official pages with authority labelling."""

from __future__ import annotations

import html
import re
import sqlite3
import unicodedata
from datetime import date
from functools import lru_cache
from urllib.parse import urlparse

from .core import CONFIG, cite, fetch
from . import registry

authority = registry.authority


@lru_cache(maxsize=1)
def _index() -> sqlite3.Connection | None:
    f = CONFIG.data_dir / "chch_index.sqlite"
    if not f.exists():
        return None
    return sqlite3.connect(f"file:{f}?mode=ro", uri=True, check_same_thread=False)


STOP = {"der", "die", "das", "und", "ich", "wie", "was", "les", "des", "une", "pour", "est", "comment", "que",
        "the", "and", "how", "what", "per", "con", "che", "del", "della", "mon", "mein", "meine", "puis", "kann"}


def _fts_query(q: str) -> str:
    """OR of terms; long words become prefix queries (cheap multilingual stemming: échanger -> echang*)."""
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) >= 3 and w not in STOP]
    terms = []
    for w in words[:12]:
        w = unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode() or w
        terms.append(f'"{w[:max(5, len(w) - 2)]}"*' if len(w) >= 6 else f'"{w}"')
    return " OR ".join(terms)


HOW_LONG = re.compile(r"combien de temps|quel delai|delai|wie lange|welche frist|\bfrist|bis wann|quanto tempo|entro quanto|"
                      r"termine|how long|deadline|within how|kura ditg|quant ditg")
DURATION = re.compile(r"\b(\d+|un|une|deux|trois|six|douze|ein|einem|zwei|drei|sechs|zwolf|uno|una|due|tre|sei|dodici|"
                      r"one|two|three|six|twelve)\s+(jours?|semaines?|mois|ans?|annees?|tage?n?|wochen?|monate?n?|jahre?n?|"
                      r"giorni|settimane|mesi|anni|days?|weeks?|months?|years?|dis|emnas|mais|onns)\b")


# Interrogative / function words (5-char stems) that say nothing about the content of a sentence.
QUESTION_WORDS = set("""come posso poss mia mio entro quant tempo combi temps comme puis pour faire lange wie darf
    kann welch wann how long what when which much many dove quale quand ditg cura""".split())


def _snippet(text: str, terms: list[str], size: int, wants_duration: bool = False) -> str:
    """Excerpt centred on the sentence that best matches the query (distinct terms; durations for 'how long')."""
    sentences = [m for m in re.finditer(r"[^.!?\n]+[.!?]?", text) if m.group(0).strip()]
    if not sentences:
        return text[:size]
    nterms = [n for t in terms if (n := registry.norm(t)) and n not in QUESTION_WORDS]

    def score(m) -> float:
        ns = registry.norm(m.group(0))
        sc = sum(1 for t in set(nterms) if t in ns)
        if wants_duration and DURATION.search(ns):
            sc += 3
        return sc

    best = max(sentences, key=score)
    if score(best) == 0:
        best = sentences[0]
    start = max(0, best.start() - size // 5)
    # start at a sentence boundary when possible, so the excerpt reads cleanly
    boundary = text.rfind(". ", 0, best.start())
    if boundary != -1 and best.start() - boundary < size // 3:
        start = boundary + 2
    s = text[start:start + size].replace("\n", " ").strip()
    return ("…" if start else "") + s + ("…" if start + size < len(text) else "")


def _page_updated(db: sqlite3.Connection, url: str) -> str | None:
    try:
        row = db.execute("SELECT updated FROM pages WHERE url=?", (url,)).fetchone()
    except sqlite3.OperationalError:  # index built before the 'updated' column existed
        return None
    return row[0] if row else None


def search(query: str, lang: str | None, limit: int) -> dict:
    db = _index()
    if db is None:
        return {"status": "unavailable", "message": "ch.ch index missing: run scripts/build_chch_index.py"}
    fq = _fts_query(query)
    if not fq:
        return {"status": "invalid_input", "message": "Query needs at least one word of 3+ letters."}
    terms = [w[:5] for w in re.findall(r"\w+", query.lower()) if len(w) >= 3 and w not in STOP]
    wants_duration = bool(HOW_LONG.search(registry.norm(query)))

    def run(lang_filter):
        sql = ("SELECT url, lang, title, heading, body, bm25(sections, 0, 0, 4.0, 3.0, 1.0) AS s "
               "FROM sections WHERE sections MATCH ?")
        args: list = [fq]
        if lang_filter:
            sql += " AND lang = ?"
            args.append(lang_filter)
        return db.execute(sql + " ORDER BY s LIMIT ?", args + [limit * 4]).fetchall()

    rows = run(lang) or run(None)
    seen, hits = set(), []
    for url, lg, title, heading, body, _ in rows:
        key = (title, heading)  # the same ch.ch page is published under several paths
        if key in seen:
            continue
        seen.add(key)
        page_hits = sum(1 for h in hits if h["url"] == url)
        if page_hits >= 2:
            continue
        hit = {"title": title, "section": heading, "lang": lg, "url": url,
               "excerpt": _snippet(body, terms, 450, wants_duration)}
        upd = _page_updated(db, url)
        if upd:
            hit["last_updated"], hit["freshness"] = upd, freshness(upd)
        hits.append(hit)
        if len(hits) >= limit:
            break
    links = {}
    for h in hits[:3]:
        row = db.execute("SELECT links FROM pages WHERE url=?", (h["url"],)).fetchone()
        for line in (row[0] if row else "").splitlines():
            href, _, label = line.partition("\t")
            if authority(href)["level"] in ("federal", "cantonal", "semi-official") and href not in links:
                links[href] = label
    built = db.execute("SELECT value FROM meta WHERE key='built'").fetchone()
    return {
        "status": "ok" if hits else "not_found",
        "results": hits,
        "authority_links_on_these_pages": [{"url": u, "label": l} for u, l in list(links.items())[:10]],
        "notes": [f"ch.ch index built {built[0] if built else '?'}; ch.ch is the Confederation's citizen portal "
                  "(Federal Chancellery, with cantons). Cantonal/municipal specifics: follow the linked authority "
                  "pages with read_official_page."],
        "sources": [cite("ch.ch - Swiss authorities online", "https://www.ch.ch/", "Federal Chancellery", "federal")],
    }


MONTHS = {m: i + 1 for names in (
    "januar februar märz april mai juni juli august september oktober november dezember",
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "january february march april may june july august september october november december",
) for i, m in enumerate(names.split())}
DATE_LABELS = (r"(?:Stand|Letzte Änderung|Zuletzt aktualisiert|Aktualisiert am|mis à jour le|Mise à jour|"
               r"Dernière modification|Dernière mise à jour|aggiornato il|Ultimo aggiornamento|Ultima modifica|"
               r"Last updated|Last modified|actualisà)")
STALE_DAYS = 730


def last_updated(page: str) -> str | None:
    """Best-effort page modification date (ISO) from JSON-LD, meta tags or visible 'last updated' text."""
    m = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', page) or re.search(
        r'<meta[^>]+(?:article:modified_time|og:updated_time|dcterms\.modified|last-modified)[^>]+content="(\d{4}-\d{2}-\d{2})',
        page, re.I)
    if m:
        return m.group(1)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    m = re.search(DATE_LABELS + r"[:\s]*(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(DATE_LABELS + r"[:\s]*(\d{1,2})\.?\s+([A-Za-zäéèûàì]+)\s+(\d{4})", text)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(DATE_LABELS + r"[:\s]*(\d{4})-(\d{2})-(\d{2})", text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def freshness(updated: str | None) -> str:
    if not updated:
        return "unknown"
    try:
        age = (date.today() - date.fromisoformat(updated)).days
    except ValueError:
        return "unknown"
    return "stale" if age > STALE_DAYS else "current"


def _clean(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style|svg|nav|header|footer|form|noscript)[^>]*>.*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</tr>|</h\d>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def read_page(url: str, focus: str | None, max_chars: int) -> dict:
    auth = authority(url)
    if auth["level"] == "foreign":
        return {"status": "rejected", "authority": auth,
                "message": "Not a Swiss domain. This server only reads Swiss public sources."}
    page = fetch(url, as_json=False, ttl=86400)
    if page.lstrip().startswith("%PDF"):
        return {"status": "unsupported", "message": "PDF documents are not parsed; cite the PDF URL directly.",
                "authority": auth}
    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    title = _clean(title_m.group(1)) if title_m else url
    m = re.search(r"(?is)<main.*?</main>", page) or re.search(r"(?is)<article.*?</article>", page) \
        or re.search(r"(?is)<body.*?</body>", page)
    main = m.group(0) if m else page
    parts = re.split(r"(?is)<h[1-4][^>]*>(.*?)</h[1-4]>", main)
    sections = [("", _clean(parts[0]))] + [(_clean(parts[i]), _clean(parts[i + 1])) for i in range(1, len(parts) - 1, 2)]
    sections = [(h, b) for h, b in sections if b or h]

    if focus:
        terms = [w for w in re.findall(r"\w+", focus.lower()) if len(w) >= 3]
        scored = sorted(sections, key=lambda s: -sum((s[0] + " " + s[1]).lower().count(t) for t in terms))
        chosen = [s for s in scored if any(t in (s[0] + s[1]).lower() for t in terms)] or sections
    else:
        chosen = sections
    out, used = [], 0
    for h, b in chosen:
        if used >= max_chars:
            break
        chunk = b[: max_chars - used]
        used += len(chunk) + len(h)
        out.append({"heading": h, "text": chunk})

    links = []
    for href, label in re.findall(r'(?is)<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', main):
        if href.startswith("/"):
            p = urlparse(url)
            href = f"{p.scheme}://{p.netloc}{href}"
        if not href.startswith("http"):
            continue
        label = _clean(label)[:80]
        if focus and not any(t in (label + href).lower() for t in re.findall(r"\w{4,}", focus.lower())):
            continue
        links.append({"url": href, "label": label})
    uniq = list({l["url"]: l for l in links}.values())[:12]
    updated = last_updated(page)
    fresh = freshness(updated)
    result = {
        "status": "ok", "title": title, "url": url, "authority": auth,
        "last_updated": updated, "freshness": fresh,
        "sections": out, "relevant_links": uniq,
        "sources": [cite(title, url, auth["publisher"], auth["level"], last_updated=updated)],
    }
    if fresh == "stale":
        result["warning"] = (f"Page last updated {updated} (more than {STALE_DAYS // 365} years ago). Rules may have "
                             "changed; say so and look for a newer official source.")
    return result
