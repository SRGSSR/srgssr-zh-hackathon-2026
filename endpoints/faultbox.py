"""Fault-injecting OpenAI-compatible endpoint.

One image, several instances (see docker-compose.yml). Each instance is either:

* KIND=simulated - answers with a canned, clearly labelled response (no model behind it)
* KIND=relay     - forwards the request to a real OpenAI-compatible API (UPSTREAM_BASE)
                   with UPSTREAM_KEY; used for the real Public AI endpoint so the demo
                   can "break" it. If no key is configured and SIMULATE_WITHOUT_KEY=1,
                   it answers like a simulated endpoint and says so in the response.

Every request that reaches /v1/chat/completions is counted and logged, whatever the
mode. The count is the ground truth the test bench asserts on: it proves whether an
endpoint received citizen data.

Control API (used by the demo panel and pytest):
    GET  /control                -> {name, kind, mode, received, ...}
    POST /control  {"mode": "up"|"down"|"slow"|"timeout"}
    POST /control/reset          -> mode=up, counters and log cleared
    GET  /control/requests       -> last received requests (bodies truncated)

Modes:
    up       normal answer
    down     HTTP 503 (request was received, provider answered with an error)
    slow     sleeps SLOW_SECONDS, then answers
    timeout  receives the request, then never answers in time (sleeps HANG_SECONDS)
"""

import asyncio
import json
import logging
import os
import time
from collections import deque

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

NAME = os.environ.get("NAME", "mock")
KIND = os.environ.get("KIND", "simulated")
UPSTREAM_BASE = os.environ.get("UPSTREAM_BASE", "").rstrip("/")
UPSTREAM_KEY = os.environ.get("UPSTREAM_KEY", "")
UPSTREAM_MODEL = os.environ.get("UPSTREAM_MODEL", "")
USER_AGENT = os.environ.get("USER_AGENT", "commune-letter-helper/0.1 (hackathon prototype)")
SIMULATE_WITHOUT_KEY = os.environ.get("SIMULATE_WITHOUT_KEY", "1") == "1"
SLOW_SECONDS = float(os.environ.get("SLOW_SECONDS", "3"))
HANG_SECONDS = float(os.environ.get("HANG_SECONDS", "60"))
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "120"))

log = logging.getLogger("faultbox")
logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{NAME}] %(message)s")

app = FastAPI(title=f"faultbox {NAME}")
state = {"mode": os.environ.get("MODE", "up"), "received": 0, "answered": 0, "errors": 0,
         # relay only: answer like a simulated endpoint even if a key is set (the test bench uses this)
         "simulate": False}
recent = deque(maxlen=50)


def _simulated_content(body: dict, note: str) -> str:
    wants_json = "json" in json.dumps(body.get("messages", [])).lower() or body.get("response_format")
    if not wants_json:
        return f"Simulated answer from {NAME}. {note}"
    return json.dumps(
        {
            "summary": (
                f"This is a simulated answer from {NAME}, a demo service with no language model behind it. "
                f"{note} It only shows that your letter was routed here. A real service would explain your letter in this place."
            ),
            "actions": [{"action": "Nothing to do: this is a demo answer.", "deadline": None}],
            "draft_reply": f"(Simulierte Antwort von {NAME}. Hier würde ein echter Dienst Ihre Antwort auf Deutsch entwerfen.)",
            "output_language": "en",
        }
    )


def _completion(body: dict, content: str) -> dict:
    return {
        "id": f"chatcmpl-{NAME}-{state['received']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"{body.get('model', 'unknown')}@{NAME}",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": f"{NAME}-model", "object": "model", "owned_by": NAME}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    state["received"] += 1
    n = state["received"]
    mode = state["mode"]
    recent.appendleft(
        {
            "n": n,
            "t": time.time(),
            "mode": mode,
            "model": body.get("model"),
            "metadata_keys": sorted((body.get("metadata") or {}).keys()),
            "first_message": str((body.get("messages") or [{}])[-1].get("content", ""))[:200],
        }
    )
    log.info("received request #%s mode=%s model=%s", n, mode, body.get("model"))

    if mode == "down":
        state["errors"] += 1
        return JSONResponse({"error": {"message": f"{NAME} is down (fault injected)", "type": "server_error"}}, 503)
    if mode == "timeout":
        await asyncio.sleep(HANG_SECONDS)
    if mode == "slow":
        await asyncio.sleep(SLOW_SECONDS)

    if KIND == "relay":
        if UPSTREAM_KEY and not state["simulate"]:
            return await _relay(body)
        if not SIMULATE_WITHOUT_KEY:
            state["errors"] += 1
            return JSONResponse({"error": {"message": f"{NAME}: no upstream API key configured"}}, 503)
        content = _simulated_content(body, "The relay to the real service is switched to simulation (no API key, or test mode).")
    else:
        content = _simulated_content(body, "")
    state["answered"] += 1
    return _completion(body, content)


async def _relay(body: dict):
    payload = dict(body)
    payload.pop("metadata", None)  # never forward gateway metadata upstream
    if UPSTREAM_MODEL:
        payload["model"] = UPSTREAM_MODEL
    headers = {"Authorization": f"Bearer {UPSTREAM_KEY}", "User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as client:
            r = await client.post(f"{UPSTREAM_BASE}/chat/completions", json=payload, headers=headers)
    except httpx.HTTPError as e:
        state["errors"] += 1
        return JSONResponse({"error": {"message": f"{NAME}: upstream error {type(e).__name__}"}}, 502)
    if r.status_code >= 400:
        state["errors"] += 1
    else:
        state["answered"] += 1
    return JSONResponse(r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": {"message": r.text[:500]}}, r.status_code)


@app.get("/control")
async def get_control():
    return {
        "name": NAME,
        "kind": KIND,
        "has_upstream_key": bool(UPSTREAM_KEY) if KIND == "relay" else None,
        **state,
    }


@app.post("/control")
async def set_control(req: Request):
    body = await req.json()
    if "simulate" in body:
        state["simulate"] = bool(body["simulate"])
    mode = body.get("mode", state["mode"])
    if mode not in ("up", "down", "slow", "timeout"):
        return JSONResponse({"error": "mode must be up|down|slow|timeout"}, 400)
    state["mode"] = mode
    log.info("mode -> %s simulate -> %s", mode, state["simulate"])
    return await get_control()


@app.post("/control/reset")
async def reset():
    state.update({"mode": "up", "received": 0, "answered": 0, "errors": 0, "simulate": False})
    recent.clear()
    return await get_control()


@app.get("/control/requests")
async def requests_log():
    return list(recent)
