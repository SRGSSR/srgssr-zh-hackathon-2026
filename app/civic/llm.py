"""The civic task: explain an official letter, list actions and deadlines, draft a reply.

Apertus is called through the policy-enforcing gateway with the commune's API key.
The answer must be a JSON object; it is validated and the call is retried once if invalid."""

import json
import os
import re
from typing import List, Optional

import httpx
from pydantic import BaseModel, ValidationError

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:4000")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "swiss-ai/apertus-v1.5-70b")
GATEWAY_TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT", "400"))

LANGUAGES = {
    "it": "Italian",
    "fr": "French",
    "pt": "Portuguese",
    "sq": "Albanian",
    "en": "English",
    "es": "Spanish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "de": "German (plain language)",
}


class Action(BaseModel):
    action: str
    deadline: Optional[str] = None


class LetterResult(BaseModel):
    summary: str
    actions: List[Action]
    draft_reply: str
    output_language: str


class GatewayUnavailable(Exception):
    """No approved endpoint could answer now. The job waits and is retried."""


class GatewayRejected(Exception):
    """The gateway refused the request (policy or input). Retrying will not help."""


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
        '"deadline": the date by which it must be done as YYYY-MM-DD, or null if the letter gives none};\n'
        '  "draft_reply": a short, polite reply letter to the commune written in German (formal "Sie"), '
        "that the reader can adapt; use placeholders like [Name] and [Datum] instead of inventing personal data;\n"
        f'  "output_language": the ISO 639-1 code of the language of summary and actions ("{language}").\n'
        "Only use facts from the letter. If something is unclear, say so in the summary. Do not add markdown."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Official letter:\n\n" + letter},
    ]


def parse_result(content: str) -> LetterResult:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise InvalidOutput("no JSON object found in the answer")
    try:
        return LetterResult.model_validate(json.loads(text[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as e:
        raise InvalidOutput(str(e)[:400]) from e


async def _call(messages: list, job_id: str) -> dict:
    payload = {
        "model": GATEWAY_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1800,
        "metadata": {"job_id": job_id},
    }
    headers = {"Authorization": f"Bearer {GATEWAY_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
            r = await client.post(f"{GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise GatewayUnavailable(f"gateway not reachable: {type(e).__name__}") from e
    if r.status_code in (400, 401, 403, 404, 422):
        raise GatewayRejected(f"{r.status_code}: {r.text[:500]}")
    if r.status_code >= 400:
        raise GatewayUnavailable(f"{r.status_code}: {_error_message(r)}")
    return {
        "body": r.json(),
        "deployment_id": r.headers.get("x-litellm-model-id"),
        "attempted_retries": r.headers.get("x-litellm-attempted-retries"),
        "attempted_fallbacks": r.headers.get("x-litellm-attempted-fallbacks"),
    }


def _error_message(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:300]
    except Exception:
        return r.text[:300]


async def explain_letter(letter: str, language: str, job_id: str, on_event=None) -> dict:
    """Returns {"result": LetterResult dict, "deployment_id": ..., "calls": n}."""
    messages = build_messages(letter, language)
    reply = await _call(messages, job_id)
    content = reply["body"]["choices"][0]["message"].get("content") or ""
    try:
        result = parse_result(content)
        calls = 1
    except InvalidOutput as e:
        if on_event:
            on_event({"type": "output_invalid_retrying", "error": str(e), "deployment_id": reply["deployment_id"]})
        messages += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": f"Your answer was not a valid JSON object with the required keys ({e}). "
                "Answer again with only the JSON object.",
            },
        ]
        reply = await _call(messages, job_id)
        content = reply["body"]["choices"][0]["message"].get("content") or ""
        result = parse_result(content)  # raises InvalidOutput on second failure
        calls = 2
    return {"result": result.model_dump(), "deployment_id": reply["deployment_id"], "calls": calls}
