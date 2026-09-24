"""Build the full-text index of ch.ch, the Confederation's citizen portal (DE/FR/IT/RM/EN).

Crawls the URLs listed in https://www.ch.ch/sitemap.xml politely (robots.txt respected, rate limited),
splits each page into sections and stores them in an SQLite FTS5 index: data/chch_index.sqlite.

Usage:
    uv run python scripts/build_chch_index.py [--limit N] [--delay 0.3]
"""

from __future__ import annotations

import argparse
import html
import re
import sqlite3
import sys
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from swiss_grounding.core import CONFIG, client  # noqa: E402
from swiss_grounding.guidance import last_updated  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = "https://www.ch.ch/sitemap.xml"


def clean(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style|svg|button|nav)[^>]*>.*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def parse(url: str, page: str) -> tuple[str, list[tuple[str, str]], list[tuple[str, str]]]:
    title = clean(re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page).group(1)) if "<h1" in page else url
    m = re.search(r"(?is)<main.*?</main>", page)
    main = m.group(0) if m else page
    links = []
    for href, label in re.findall(r'(?is)<a[^>]+href="(https?://[^"#]+)"[^>]*>(.*?)</a>', main):
        if "ch.ch/" not in href and not re.search(r"(youtube|twitter|facebook|linkedin|instagram)\.", href):
            links.append((href, clean(label)[:80]))
    # Split on h2/h3 headings (accordion questions on ch.ch are h2/h3 too).
    parts = re.split(r"(?is)<h[23][^>]*>(.*?)</h[23]>", main)
    sections = []
    lead = clean(parts[0])
    if lead:
        sections.append((title, lead))
    for i in range(1, len(parts) - 1, 2):
        head, body = clean(parts[i]), clean(parts[i + 1])
        if body and len(body) > 40:
            sections.append((head, body))
    return title, sections, list(dict.fromkeys(links))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    c = client()
    urls = re.findall(r"<loc>([^<]+)</loc>", c.get(SITEMAP).text)
    urls = [u for u in urls if re.match(r"https://www\.ch\.ch/(de|fr|it|rm|en)/.+", u)]
    if args.limit:
        urls = urls[: args.limit]
    rp = urllib.robotparser.RobotFileParser()
    r = c.get("https://www.ch.ch/robots.txt")
    if "text/plain" in r.headers.get("content-type", ""):
        rp.parse(r.text.splitlines())
    else:
        rp.parse([])
    rp_ok = lambda u: not CONFIG.respect_robots or rp.can_fetch(CONFIG.user_agent, u)  # noqa: E731

    out = ROOT / "data" / "chch_index.sqlite"
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp, check_same_thread=False)
    db.executescript(
        """
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE pages(url TEXT PRIMARY KEY, lang TEXT, title TEXT, links TEXT, updated TEXT);
        CREATE VIRTUAL TABLE sections USING fts5(
            url UNINDEXED, lang UNINDEXED, title, heading, body, tokenize="unicode61 remove_diacritics 2");
        """
    )

    def work(u: str):
        if not rp_ok(u):
            return u, None
        time.sleep(args.delay)
        try:
            resp = c.get(u)
            if resp.status_code != 200:
                return u, None
            return u, (*parse(u, resp.text), last_updated(resp.text))
        except httpx.HTTPError:
            return u, None

    done = 0
    with ThreadPoolExecutor(args.workers) as ex:
        for u, res in ex.map(work, urls):
            done += 1
            if not res:
                continue
            title, sections, links, updated = res
            lang = u.split("/")[3]
            db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?)",
                       (u, lang, title, "\n".join(f"{h}\t{l}" for h, l in links[:40]), updated))
            db.executemany("INSERT INTO sections VALUES (?,?,?,?,?)",
                           [(u, lang, title, h, b[:4000]) for h, b in sections])
            if done % 100 == 0:
                print(done, "/", len(urls), flush=True)
                db.commit()
    db.executemany("INSERT INTO meta VALUES (?,?)", [("built", date.today().isoformat()), ("source", SITEMAP)])
    db.commit()
    n = db.execute("SELECT count(*) FROM pages").fetchone()[0]
    db.close()
    tmp.replace(out)
    print(out, n, "pages")


if __name__ == "__main__":
    main()
