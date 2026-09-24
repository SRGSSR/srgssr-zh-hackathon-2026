"""swiss_ground: deterministic jurisdiction / topic / authority router (no LLM inside).

Decides, before any answer is written, whether a question is answerable from authoritative Swiss sources:
out_of_scope | ambiguous | varies_by_canton | needs_jurisdiction | routed | unsupported.
"""

from __future__ import annotations

import re

from . import geo, guidance, registry, sources
from .registry import norm

STOPWORDS = {
    "de": "der die das und ich wie wann wird ist bei uns nach mein meine mit fur muss kann welche ein eine zu den dem nicht wo was".split(),
    "fr": "le la les et je comment quand est pour mon ma des une un dans du de puis combien quel quelle ou ai".split(),
    "it": "il lo gli e come quando qual quale per mio mia una di del della che sono anni ho posso dove".split(),
    "rm": "cura en las da tge co jau vus nus ina dal dals ils cun sco vacanzas scola atun per".split(),
    "en": "the and how when is what my i for do does which can of to in where".split(),
}
DEICTIC = ["bei uns", "bei mir", "hier bei", "wo ich wohne", "in meiner gemeinde", "chez nous", "chez moi", "ou j habite",
           "dans ma commune", "da noi", "dove abito", "nel mio comune", "tar nus", "nua che jau stun", "where i live",
           "near me", "in my municipality", "in my town"]
GENERALISE = ["uberall in der schweiz", "in der ganzen schweiz", "schweizweit", "in allen kantonen", "fur die ganze schweiz",
              "partout en suisse", "dans toute la suisse", "dans tous les cantons", "in tutta la svizzera",
              "in tutti i cantoni", "dapertut en svizra", "en tut la svizra", "everywhere in switzerland",
              "all over switzerland", "in all cantons", "whole of switzerland"]
LOCATIVE = r"(?:in|im|nach|zu|bei|a|au|aux|en|nel|nella|at|near|to)"  # on normalised text
PLACE_PREP = (r"\b(?:in|im|nach|von|bei|zu|für|a|à|au|de|da|di|per|at|near|for|to|from|domicilié à|domiciliée à|"
              r"domiciliato a|domiciliata a|wohnhaft in)\s+")
PLACE_TOKEN = r"(?:St\.|Ste?-|San |Sankt )?[A-ZÄÖÜÉÈÀ][\wäöüéèàç'’-]+"
QUESTIONS = {
    "municipal": {"de": "In welcher Gemeinde (oder PLZ) wohnen Sie?", "fr": "Dans quelle commune (ou NPA) habitez-vous ?",
                  "it": "In quale comune (o NPA) abita?", "rm": "En tge vischnanca abitais Vus?",
                  "en": "Which municipality (or postcode) do you live in?"},
    "cantonal": {"de": "In welchem Kanton (oder welcher Gemeinde) wohnen Sie?", "fr": "Dans quel canton (ou quelle commune) habitez-vous ?",
                 "it": "In quale cantone (o comune) abita?", "rm": "En tge chantun (u vischnanca) abitais Vus?",
                 "en": "Which canton (or municipality) do you live in?"},
}
GENERIC = set("""viel hoch kostet kosten gibt muss kann welche welcher wann where much cost costs combien coute cout quel
    quelle quanto costa quale quando what which does have need brauche braucht aktuell actuel attuale current""".split())
CHILD = r"\b(kind|kinder|kindes|enfant|enfants|bambino|bambina|bambini|figlio|figlia|child|children|uffant)\b"
PLACE_TOOLS = {"health_insurance_premiums", "school_holidays", "waste_collection", "municipality_population"}
DEDUCTIBLES = {0, 100, 200, 300, 400, 500, 600, 1000, 1500, 2000, 2500}


def detect_language(q: str) -> str:
    words = norm(q).split()
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    if re.search(r"\b(cura|tge|vischnanca|chantun|vacanzas|atun)\b", norm(q)):
        scores["rm"] += 3
    return max(scores, key=lambda k: (scores[k], k == "de"))


def classify(nq: str) -> tuple[str | None, float]:
    tokens = nq.split()
    best, best_score = None, 0
    for tid, t in registry.topics().items():
        score = 0
        for kw in t["keywords"]:
            k = norm(kw)
            if (" " in k and re.search(rf"\b{re.escape(k)}", nq)) or (" " not in k and any(tok.startswith(k) for tok in tokens)):
                score += len(k)
        if score > best_score:
            best, best_score = tid, score
    return best, min(1.0, best_score / 12)


def _foreign(nq: str) -> str | None:
    """Foreign place/country used as a location ("nach Konstanz", "en France"), not as an origin."""
    fp = registry.registry()["foreign_places"]
    for name in fp["places"] + fp["countries"]:
        if re.search(rf"\b{LOCATIVE}\s+(?:der |den |la |le |l )?{re.escape(norm(name))}\b", nq):
            return name
    return None


def _canton(nq: str) -> str | None:
    for code, c in registry.cantons().items():
        for n in c.get("names", []):
            if re.search(rf"\b{re.escape(norm(n))}\b", nq):
                return code
    return None


def _place_candidates(q: str) -> list[list[str]]:
    """Place mentions in order; each mention is a list of variants, longest first ("Wil SG", "Wil")."""
    groups = []
    for m in re.finditer(r"\b(?:PLZ|NPA|CAP)?\s*([1-9]\d{3})\b(?=\s+[A-ZÄÖÜ]|\s*$|[?.,])", q):
        num = m.group(1)
        if not re.fullmatch(r"(19|20)\d{2}", num) or re.search(rf"{num}\s+[A-ZÄÖÜ]", q):
            groups.append([num])
    for m in re.finditer(PLACE_PREP + rf"({PLACE_TOKEN}(?:\s+(?:am|an|im|bei|sur|di|de)\s+{PLACE_TOKEN}|\s+{PLACE_TOKEN}){{0,2}})", q):
        words = m.group(1).split()
        groups.append([" ".join(words[:n]).rstrip("?.,!") for n in range(len(words), 0, -1)])
    return groups


def _bare_candidates(q: str) -> list[list[str]]:
    """Capitalised words not introduced by a preposition ("combien d'habitants compte Lausanne").

    Used only when nothing else was found and the topic depends on the place; geo.locate accepts exact names only,
    so ordinary capitalised nouns do not resolve.
    """
    words = re.findall(rf"(?<![\w'’]){PLACE_TOKEN}", q)
    first = re.match(r"\s*([\wÀ-ÿ'’-]+)", q)
    skip = {first.group(1)} if first else set()
    return [[w.rstrip("?.,!")] for w in dict.fromkeys(words) if w not in skip and len(w) > 2]


def _resolve_places(q: str, place: str | None, bare: bool = False) -> tuple[list[dict], dict | None]:
    """All distinct Swiss municipalities mentioned (in order), or the first ambiguous mention."""
    found: dict[int, dict] = {}
    groups = [[place]] if place else _place_candidates(q)
    if not groups and bare:
        groups = _bare_candidates(q)
    for variants in groups:
        for cand in variants:
            r = geo.locate(cand)
            if r["status"] == "resolved":
                found.setdefault(r["bfs_nr"], r)
                break
            if r["status"] == "ambiguous":
                return list(found.values()), r
    return list(found.values()), None


def _jurisdiction(muni: dict | None, canton: str | None, t: dict) -> tuple[dict | None, list[dict]]:
    jurisdiction, chain = None, []
    if muni:
        jurisdiction = {k: muni.get(k) for k in ("municipality", "bfs_nr", "canton", "postcode") if muni.get(k)}
        if muni.get("municipality_website"):
            chain.append({"level": "municipal", "url": muni["municipality_website"]})
    elif canton:
        jurisdiction = {"canton": canton}
    if canton:
        chain.append({"level": "cantonal", "url": f"https://www.{registry.cantons()[canton]['domain']}"})
    for u in t.get("sources", []):
        chain.append({"level": registry.authority(u)["level"], "url": u})
    return jurisdiction, chain


def _premium_args(q: str, nq: str) -> tuple[dict, list[str]]:
    args, missing = {}, []
    age = re.search(r"\b(\d{1,3})\s*(?:-?\s*jahr|jahrig|j\b|ans\b|anni\b|onns\b|years?\b|-year)", nq) or \
        re.search(r"\b(?:age|alter|eta|age de|di)\s*(\d{1,3})\b", nq)
    if age:
        args["age"] = int(age.group(1))
    elif re.search(CHILD, nq):
        args["age"] = 10  # all ages 0-18 share one premium class (first child)
    else:
        missing.append("age")
    nums = [int(n.replace("'", "")) for n in re.findall(r"\b(\d{1,2}'?\d{3}|\d{1,3})\b", q)]
    deds = [n for n in nums if n in DEDUCTIBLES and n != args.get("age")]
    if deds:
        args["deductible"] = deds[0]
    else:
        missing.append("deductible")
    if re.search(r"ohne unfall|sans (?:la )?couverture accident|sans accident|senza (?:copertura )?infortun|without accident", nq):
        args["accident_cover"] = False
    elif re.search(r"mit unfall|avec (?:la )?couverture accident|avec accident|con (?:copertura )?infortun|with accident", nq):
        args["accident_cover"] = True
    return args, missing


def _transport_args(q: str) -> tuple[dict, list[str]]:
    tok = rf"({PLACE_TOKEN}(?:\s+{PLACE_TOKEN})?)"
    m = re.search(rf"\b(?:von|de|da|from|ab)\s+{tok}\s+(?:nach|à|a|to|pour|per|verso)\s+{tok}", q)
    if m:
        args = {"origin": m.group(1), "destination": m.group(2)}
    else:
        d = re.search(rf"\b(?:nach|à|a|to|pour|per|verso)\s+{tok}", q)
        args = {"destination": d.group(1)} if d else {}
    t = re.search(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b", q)
    if t:
        args["when"] = f"{int(t.group(1)):02d}:{t.group(2)}"
    return args, [k for k in ("origin", "destination") if k not in args]


def _search_query(q: str, t: dict, lang: str) -> str:
    """Question plus the topic's official wording in that language (users say 'patente', ch.ch says 'licenza')."""
    extra = (t.get("search_terms") or {}).get(lang)
    return f"{q} {extra}" if extra else q


def _date(q: str) -> str | None:
    """ISO date from '2026-11-29', '29.11.2026' or '29. November (2026)' (year defaults to the next occurrence)."""
    from datetime import date

    if m := re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", q):
        return m.group(0)
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", q):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if (m := re.search(r"\b(\d{1,2})\.?\s+([A-Za-zäéèûì]+)(?:\s+(20\d{2}))?", q)) and m.group(2).lower() in guidance.MONTHS:
        today = date.today()
        mon, day = guidance.MONTHS[m.group(2).lower()], int(m.group(1))
        year = int(m.group(3)) if m.group(3) else today.year + (1 if (mon, day) < (today.month, today.day) else 0)
        return f"{year}-{mon:02d}-{day:02d}"
    return None


def _coverage(hit: dict, terms: list[str], heading_only: bool = False) -> float:
    fields = ["title", "section", "url"] + ([] if heading_only else ["excerpt"])  # URL slug ~ page title
    text = norm(" ".join(hit.get(f, "") for f in fields))
    return sum(1 for t in terms if t in text) / max(1, len(terms))


def _next_call(topic: str, tool: str, q: str, nq: str, muni: dict | None, lang: str,
               canton: str | None = None) -> dict:
    place = None
    if muni:
        # keep a locality ("Wengen") so the data tool can say its figures are for the containing municipality
        place = muni.get("postcode") or (muni.get("locality") if muni.get("match_type") == "locality"
                                         else f"{muni['municipality']} {muni['canton']}")
    args: dict = {}
    missing: list[str] = []
    if tool == "health_insurance_premiums":
        args, missing = _premium_args(q, nq)
        args["place"] = place
    elif tool == "school_holidays":
        y = re.search(r"\b(20\d{2})\b", q)
        args = {"place": place, "language": lang, **({"year": int(y.group(1))} if y else {})}
    elif tool == "waste_collection":
        args = {"place": place, "material": sources.waste_material(q)}
    elif tool == "public_transport_connections":
        args, missing = _transport_args(q)
    elif tool == "federal_votes":
        args = {"language": lang, **({"vote_date": d} if (d := _date(q)) else {})}
    elif tool == "municipality_population":
        args = {"place": place} if place else {"canton": canton}
    elif tool == "reference_interest_rate":
        args = {"language": lang if lang in ("de", "fr", "it") else "de"}
    elif tool == "company_register_search":
        n = re.search(r"[«\"“']([^»\"”']{2,60})[»\"”']", q) or re.search(
            r"\b(?:Firma|Unternehmen|firm|company|entreprise|société|ditta|azienda|società)\s+([A-Z0-9][\w&.'-]*(?:\s+(?:AG|SA|GmbH|Sàrl|[A-Z][\w&.'-]*))*)", q)
        if n:
            args = {"name": n.group(1)}
        else:
            missing = ["name"]
    if tool in PLACE_TOOLS and not args.get("place") and not args.get("canton") and "place" not in missing:
        missing.append("place")
    return {"tool": tool, "args": {k: v for k, v in args.items() if v is not None}, "missing": missing}


def _multi(base: dict, q: str, nq: str, lang: str, topic: str | None, t: dict, munis: list[dict]) -> dict:
    """Several municipalities in one question: resolve each independently, never share procedures between them."""
    entries = []
    for m in munis:
        jur, chain = _jurisdiction(m, m["canton"], t)
        entry = {"jurisdiction": jur, "authority_chain": chain}
        if topic and t.get("tool"):
            entry["next_call"] = _next_call(topic, t["tool"], q, nq, m, lang, m["canton"])
        entries.append(entry)
    out = {**base, "decision": "routed", "support": "strong" if topic and t.get("tool") else "partial",
           "jurisdictions": entries,
           "instruction": ("The question covers several municipalities. Answer each one separately with its own "
                           "sources; never reuse one municipality's deadlines, fees or forms for another. "
                           + ("Call every next_call." if topic and t.get("tool") else
                              "Use the shared federal evidence only for what is common, and read each municipality's "
                              "page (authority_chain) with read_official_page for local procedures."))}
    if not (topic and t.get("tool")):
        ev = guidance.search(_search_query(q, t, lang), lang, 3)
        out["shared_evidence"], out["sources"] = ev.get("results", []), ev.get("sources", [])
    return out


def ground(question: str, place: str | None = None, language: str | None = None) -> dict:
    q = question.strip()
    nq = norm(q)
    lang = language or detect_language(q)
    topic, conf = classify(nq)
    t = registry.topics().get(topic, {}) if topic else {}
    level = t.get("level")
    base = {"language": lang, "topic": {"id": topic, "level": level, "confidence": round(conf, 2)} if topic else None}

    munis, ambiguous = _resolve_places(q, place, bare=bool(t.get("needs_place")))
    muni = munis[0] if munis else None
    foreign = None if (muni or place) else _foreign(nq)
    if foreign:
        return {**base, "decision": "out_of_scope", "support": "none",
                "reason": f"The question concerns '{foreign}', which is outside Switzerland. Swiss rules and sources "
                          "do not apply; this server only covers Switzerland.",
                "instruction": "Tell the user clearly that this is outside Switzerland and not covered. Do not answer "
                               "with Swiss information."}
    if ambiguous:
        return {**base, "decision": "ambiguous", "support": "none",
                "question_for_user": ambiguous["question_for_user"], "candidates": ambiguous["candidates"],
                "instruction": "Ask the user which place is meant; ask nothing else."}

    canton = muni["canton"] if muni else _canton(nq)
    if topic and level in ("cantonal", "municipal") and any(g in nq for g in GENERALISE):
        ev = guidance.search(_search_query(q, t, lang), lang, 3)
        return {**base, "decision": "varies_by_canton", "support": "partial",
                "reason": f"'{topic}' is regulated at {level} level; there is no single rule for all of Switzerland.",
                "evidence": ev.get("results", []), "sources": ev.get("sources", []),
                "instruction": "Explain that the answer differs by canton/municipality, give the federal framework from "
                               "the evidence, and offer to check a specific place. Do not present one canton's rule "
                               "as the Swiss rule."}

    # needs_place: municipal- and federal-level topics need the municipality (premium region, population, calendar);
    # canton-level topics are satisfied by the canton alone.
    needs_muni = (bool(t.get("needs_place")) and level in ("municipal", "federal")
                  and not (t.get("canton_ok") and canton))  # e.g. population: a canton figure answers it
    needs_canton = bool(t.get("needs_place")) and level == "cantonal"
    if topic and ((needs_muni and not muni) or (needs_canton and not muni and not canton)):
        kind = "municipal" if needs_muni else "cantonal"
        return {**base, "decision": "needs_jurisdiction", "support": "none",
                "missing": "municipality" if needs_muni else "canton",
                "question_for_user": QUESTIONS[kind].get(lang, QUESTIONS[kind]["en"]),
                "reason": f"The answer to a '{topic}' question depends on the {kind} jurisdiction.",
                "instruction": "Ask the user only this question, then call swiss_ground again (or next tool) with `place`."}

    if len(munis) > 1 and topic != "public_transport":
        return _multi(base, q, nq, lang, topic, t, munis)
    jurisdiction, chain = _jurisdiction(muni, canton, t)

    if topic and t.get("tool"):
        nc = _next_call(topic, t["tool"], q, nq, muni, lang, canton)
        return {**base, "decision": "routed", "support": "strong" if not nc["missing"] else "partial",
                "jurisdiction": jurisdiction, "authority_chain": chain, "next_call": nc,
                "instruction": ("Call next_call and answer from its result, citing its sources."
                                + (f" First ask the user only for: {', '.join(nc['missing'])}." if nc["missing"] else ""))}

    ev = guidance.search(_search_query(q, t, lang), lang, 3)
    hits = ev.get("results", [])
    if not topic:  # without a known topic, keep only evidence that covers most of the question's terms
        words = [norm(w) for w in re.findall(r"\w+", q) if len(w) >= 4 and norm(w) not in guidance.STOP | GENERIC]
        terms = [w[:5] for w in words]
        longest = max(words, key=len)[:5] if words else ""
        hits = [h for h in hits if longest and _coverage(h, [longest], heading_only=True) == 1 and _coverage(h, terms) >= 0.5]
    if not topic and not hits:
        out = {**base, "decision": "unsupported", "support": "none",
               "reason": "No authoritative Swiss source in this server's scope covers this question.",
               "instruction": "Say that you could not find authoritative Swiss information; do not guess."}
        if jurisdiction:
            out["jurisdiction"], out["authority_chain"] = jurisdiction, chain
            out["instruction"] += " Point the user to the responsible authority in authority_chain."
        return out
    return {**base, "decision": "routed", "support": "partial" if hits else "none",
            "jurisdiction": jurisdiction, "authority_chain": chain,
            "evidence": hits, "authority_links": ev.get("authority_links_on_these_pages", [])[:5],
            "sources": ev.get("sources", []),
            "instruction": ("Answer from the evidence and cite the URLs. For canton- or municipality-specific details, "
                            "read the cantonal/municipal page from authority_chain or authority_links with "
                            "read_official_page. If the evidence does not answer the question, say so.")}
