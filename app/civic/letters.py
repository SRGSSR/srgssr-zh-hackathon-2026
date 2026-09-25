"""Things the app knows about letters: the samples, the languages, and a rough hint of what
kind of sensitive information a letter contains (shown to explain why the rule matters)."""

import re

from .i18n import t

# Language names in their own language, so people find theirs.
LANGUAGE_NAMES = {
    "de": "Deutsch",
    "fr": "Français",
    "it": "Italiano",
    "rm": "Rumantsch",
    "gsw": "Schwiizerdütsch",
    "en": "English",
}

# file -> (sender, subject, service whose rule applies); sender and subject are string keys (locales/)
SAMPLES = {
    "01-sozialhilfe-unterlagen.txt": ("service.social.office", "sample.01", "social"),
    "02-sozialhilfe-rueckerstattung.txt": ("service.social.office", "sample.02", "social"),
    "03-schule-klassenlager.txt": ("service.school.office", "sample.03", "school"),
    "04-zahlungserinnerung.txt": ("sample.sender.finance", "sample.04", "info"),
}

# Which office wrote the letter decides which rule applies. Each service has its own API key,
# and the gateway binds the rule to that key (gateway/communes.yaml). The lists below are only
# for display; the gateway enforces the real rule. The texts are in locales/ (service.<key>.*).
SERVICES = {
    "social": {"key_env": "GATEWAY_API_KEY", "allowed": ["CH"], "consent": []},
    "school": {"key_env": "GATEWAY_API_KEY_SCHOOL", "allowed": ["CH", "EU"], "consent": []},
    "info": {"key_env": "GATEWAY_API_KEY_INFO", "allowed": ["CH", "EU"], "consent": ["US"]},
}

_SENSITIVE = [
    ("topic.social_assistance", r"sozialhilfe|unterstützung|sozialdienst|soziale dienste|grundbedarf"),
    ("topic.health", r"arztzeugnis|arbeitsunfähig|gesundheit|krankheit|spital|therapie"),
    ("topic.children", r"\bkinder\b|\bkind\b|kinderzulage"),
    ("topic.money", r"steuer|mahnung|betreibung|rückforderung|chf"),
    ("topic.ahv", r"756\.\d{4}\.\d{4}\.\d{2}"),
]


def service_view(key: str, lang: str) -> dict:
    """What the pages show about an office's rule, in the page's language."""
    key = key if key in SERVICES else "social"
    s = {name: t(lang, f"service.{key}.{name}") for name in ("office", "rule_line", "promise", "sign", "allows")}
    return {**SERVICES[key], **s, "key": key}


def sensitive_topics(letter: str) -> list:
    """String keys of the kinds of sensitive information the letter mentions."""
    text = (letter or "").lower()
    return [name for name, pattern in _SENSITIVE if re.search(pattern, text)]
