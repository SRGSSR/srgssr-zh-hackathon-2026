"""Source registry (data/sources.yaml): trusted domains, cantons, municipalities, foreign places, topics."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from urllib.parse import urlparse

import yaml

from .core import CONFIG


def norm(s: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumerics (keeps '-' and '.' out)."""
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@lru_cache(maxsize=1)
def registry() -> dict:
    return yaml.safe_load((CONFIG.data_dir / "sources.yaml").read_text(encoding="utf-8"))


def cantons() -> dict[str, dict]:
    return registry()["cantons"]


def municipality(bfs: int) -> dict | None:
    return registry().get("municipalities", {}).get(int(bfs))


def topics() -> dict[str, dict]:
    return registry()["topics"]


def authority(url: str) -> dict:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    reg = registry()

    def under(d: str) -> bool:
        return host == d or host.endswith("." + d)

    if any(under(d) for d in reg["federal"]["domains"]):
        return {"level": "federal", "publisher": host}
    for code, c in reg["cantons"].items():
        if under(c["domain"]):
            return {"level": "cantonal", "publisher": f"Canton {c['name']}", "canton": code}
    for bfs, m in reg.get("municipalities", {}).items():
        if under(urlparse(m["website"]).netloc.removeprefix("www.")):
            return {"level": "municipal", "publisher": f"Municipality of {m['name']}", "bfs_nr": bfs}
    for d, name in reg["semi_official"].items():
        if under(d):
            return {"level": "semi-official", "publisher": name}
    if host.endswith((".ch", ".swiss")):
        return {"level": "unverified", "publisher": host,
                "note": "Swiss domain not in the authority registry (may be a municipality or private site)."}
    return {"level": "foreign", "publisher": host}
