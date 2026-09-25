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

SAMPLES = {
    "01-sozialhilfe-unterlagen.txt": ("Social services", "Documents needed for your support"),
    "02-sozialhilfe-rueckerstattung.txt": ("Social services", "Asked to pay back CHF 1'240"),
    "03-steuerveranlagung.txt": ("Tax office", "Your tax assessment 2025"),
    "04-zahlungserinnerung.txt": ("Finance office", "Second payment reminder"),
}

_SENSITIVE = [
    ("social assistance", r"sozialhilfe|unterstützung|sozialdienst|soziale dienste|grundbedarf"),
    ("health", r"arztzeugnis|arbeitsunfähig|gesundheit|krankheit|spital|therapie"),
    ("children", r"\bkinder\b|\bkind\b|kinderzulage"),
    ("money and debts", r"steuer|mahnung|betreibung|rückforderung|chf"),
    ("your AHV number", r"756\.\d{4}\.\d{4}\.\d{2}"),
]


def sensitive_topics(letter: str) -> list:
    text = (letter or "").lower()
    return [name for name, pattern in _SENSITIVE if re.search(pattern, text)]


def is_social_assistance(letter: str) -> bool:
    return "social assistance" in sensitive_topics(letter)
