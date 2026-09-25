"""The civic task: explain an official letter, list actions and deadlines, draft a reply.

The answer must be a JSON object; it is validated here, and asked for once more if invalid.
Where the request goes, and how long it may wait, is the gateway's job, not the app's."""

import json
import re
from typing import List, Optional

from pydantic import BaseModel, ValidationError

LANGUAGES = {
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "rm": "Romansh (Rumantsch Grischun)",
    "gsw": "Swiss German (Schwiizerdütsch), written the way people speak it in Zurich",
    "en": "English",
}


class Action(BaseModel):
    action: str
    deadline: Optional[str] = None


class LetterResult(BaseModel):
    summary: str
    actions: List[Action]
    draft_reply: str
    output_language: str


class InvalidOutput(Exception):
    pass


def build_messages(letter: str, language: str) -> list:
    lang = LANGUAGES.get(language, language)
    system = (
        "You help residents of a Swiss commune understand official letters. "
        "You are not a lawyer and you do not give legal advice.\n"
        "Read the letter and answer with ONE JSON object and nothing else, with exactly these keys:\n"
        '  "summary": a short plain-language explanation of what the letter says and what it means for the reader, '
        f"written in {lang};\n"
        '  "actions": a list of objects {"action": what the reader has to do, written in ' + lang + ', '
        '"deadline": the date by which it must be done as YYYY-MM-DD, or null if the letter gives none}; '
        "include every document to send, every appointment (with its date) and anything the reader must report or pay;\n"
        '  "draft_reply": a short, polite reply letter to the commune written in German (formal "Sie"), '
        "that the reader can adapt; use placeholders like [Name] and [Datum] instead of inventing personal data;\n"
        f'  "output_language": the language code of summary and actions ("{language}").\n'
        "Only use facts from the letter. If something is unclear, say so in the summary. Do not add markdown.\n"
        "Write the summary and the actions in easy language, whatever the language: short sentences, everyday words, "
        "one idea per sentence, and explain any official term in brackets the first time you use it.\n"
        "Keep it short, so that people can read it quickly: the summary in at most 120 words, "
        "at most 6 actions of one sentence each, and a reply of at most 150 words."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Official letter:\n\n" + letter},
    ]


def correction_messages(letter: str, language: str, previous: str, error: str) -> list:
    return build_messages(letter, language) + [
        {"role": "assistant", "content": previous},
        {
            "role": "user",
            "content": f"Your answer was not a valid JSON object with the required keys ({error}). "
            "Answer again with only the JSON object.",
        },
    ]


def parse_result(content: str) -> LetterResult:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise InvalidOutput("no JSON object found in the answer")
    try:
        return LetterResult.model_validate(json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as e:
        raise InvalidOutput(str(e)[:400]) from e


def content_of(gateway_job: dict) -> str:
    try:
        return gateway_job["result"]["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""
