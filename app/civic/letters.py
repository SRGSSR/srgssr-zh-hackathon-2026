"""Things the app knows about letters: the samples, the languages, and a rough hint of what
kind of sensitive information a letter contains (shown to explain why the rule matters)."""

import re

# Language names in their own language, so people find theirs.
LANGUAGE_NAMES = {
    "it": "Italiano",
    "fr": "Français",
    "pt": "Português",
    "sq": "Shqip",
    "en": "English",
    "es": "Español",
    "tr": "Türkçe",
    "uk": "Українська",
    "de": "Deutsch, einfach",
}

# file -> (sender, subject, service whose rule applies)
SAMPLES = {
    "01-sozialhilfe-unterlagen.txt": ("Social services", "Documents needed for your support", "social"),
    "02-sozialhilfe-rueckerstattung.txt": ("Social services", "Asked to pay back CHF 1'240", "social"),
    "03-schule-klassenlager.txt": ("School", "Class camp: registration and costs", "school"),
    "04-zahlungserinnerung.txt": ("Finance office", "Second payment reminder", "info"),
}

# Which office wrote the letter decides which rule applies. Each service has its own API key,
# and the gateway binds the rule to that key (gateway/communes.yaml). The lists below are only
# for display; the gateway enforces the real rule.
SERVICES = {
    "social": {
        "office": "Social services",
        "owner": "the social services",
        "owner_s": "the social services'",
        "rule": "Switzerland only",
        "promise": "Only services in Switzerland read your letter. If none is available, it waits here, safely, until one is.",
        "promise_key": "Only services in Switzerland",
        "key_env": "GATEWAY_API_KEY",
        "allowed": ["CH"],
        "consent": [],
    },
    "school": {
        "office": "School",
        "owner": "the school",
        "owner_s": "the school's",
        "rule": "Switzerland first, then the EU",
        "promise": "Services in Switzerland read your letter first. If none can answer, services in the EU may. Never anywhere else.",
        "promise_key": "Services in Switzerland",
        "key_env": "GATEWAY_API_KEY_SCHOOL",
        "allowed": ["CH", "EU"],
        "consent": [],
    },
    "info": {
        "office": "Another office",
        "owner": "this office",
        "owner_s": "this office's",
        "rule": "Switzerland and the EU; elsewhere only if you agree",
        "promise": "Services in Switzerland and the EU read your letter. A service anywhere else only if you agree, for this letter only.",
        "promise_key": "Services in Switzerland and the EU",
        "key_env": "GATEWAY_API_KEY_INFO",
        "allowed": ["CH", "EU"],
        "consent": ["US"],
    },
}

_SENSITIVE = [
    ("social assistance", r"sozialhilfe|unterstützung|sozialdienst|soziale dienste|grundbedarf"),
    ("health", r"arztzeugnis|arbeitsunfähig|gesundheit|krankheit|spital|therapie"),
    ("children", r"\bkinder\b|\bkind\b|kinderzulage"),
    ("money and debts", r"steuer|mahnung|betreibung|rückforderung|chf"),
    ("your AHV number", r"756\.\d{4}\.\d{4}\.\d{2}"),
]


for _s in SERVICES.values():
    assert _s["promise"].startswith(_s["promise_key"])
    _s["promise_rest"] = _s["promise"][len(_s["promise_key"]):]


def sensitive_topics(letter: str) -> list:
    text = (letter or "").lower()
    return [name for name, pattern in _SENSITIVE if re.search(pattern, text)]


def is_social_assistance(letter: str) -> bool:
    return "social assistance" in sensitive_topics(letter)
