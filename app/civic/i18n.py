"""The page in the resident's language: German, French, Italian, Romansh or English.

Strings live in locales/<code>.json; English is the source. A missing string falls back to
German for Romansh, then to English. The language of the explanation is chosen separately,
on the form. Placeholders are {name}; [[...]] marks the part a sentence underlines or bolds."""

import json
import re
from pathlib import Path
from typing import Optional

from markupsafe import Markup, escape

# In the order Swiss federal sites use.
UI_LANGUAGES = {"de": "Deutsch", "fr": "Français", "it": "Italiano", "rm": "Rumantsch", "en": "English"}
_FALLBACK = {"rm": ["de"]}
_DIR = Path(__file__).parent / "locales"
_RAW = {code: json.loads((_DIR / f"{code}.json").read_text(encoding="utf-8")) for code in UI_LANGUAGES}
_STRINGS = {}
for _code in UI_LANGUAGES:
    merged = dict(_RAW["en"])
    for fallback in _FALLBACK.get(_code, []):
        merged.update({k: v for k, v in _RAW[fallback].items() if v})
    merged.update({k: v for k, v in _RAW[_code].items() if v})
    _STRINGS[_code] = merged

_VAR = re.compile(r"\{(\w+)\}")
# Status reasons are stored in English (by the app and the gateway); shown in the page's language.
_REASONS = {v: k for k, v in _RAW["en"].items() if k.startswith("reason.")}


def strings(lang: str) -> dict:
    return _STRINGS.get(lang, _STRINGS["en"])


def t(lang: str, key: str, default: Optional[str] = None, **values) -> str:
    """The string for key in lang, with {placeholders} filled in. Unknown placeholders stay."""
    s = strings(lang).get(key)
    if s is None:
        s = key if default is None else default
    if values:
        s = _VAR.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), s)
    return s


def marked(text: str, tag: str = "strong", attrs: str = "") -> Markup:
    """'a [[b]] c' as HTML: 'a <tag>b</tag> c', everything else escaped."""
    before, found, rest = text.partition("[[")
    if not found:
        return escape(text)
    inner, _, after = rest.partition("]]")
    return Markup(f"{escape(before)}<{tag}{(' ' + attrs) if attrs else ''}>{escape(inner)}</{tag}>{escape(after)}")


def plain(text: str) -> str:
    return text.replace("[[", "").replace("]]", "")


def place(lang: str, code: Optional[str]) -> Optional[str]:
    """'in Switzerland' for CH, with the preposition the language needs; None if unknown."""
    return t(lang, f"place.{code}", default="") or None if code else None


def join(lang: str, items) -> str:
    items = [i for i in items if i]
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + t(lang, "common.and") + items[-1]


def reason(lang: str, text: Optional[str]) -> Optional[str]:
    key = _REASONS.get(text or "")
    return t(lang, key) if key else text


def pick(query: Optional[str], cookie: Optional[str], accept_language: str) -> str:
    """?lang= wins, then the remembered choice, then the browser's languages, then English."""
    for code in (query, cookie):
        if code in UI_LANGUAGES:
            return code
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        for code in (tag, tag.split("-")[0]):
            if code == "gsw":
                return "de"
            if code in UI_LANGUAGES:
                return code
    return "en"
