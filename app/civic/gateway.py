"""Client for the gateway's deferred API. The gateway keeps the request while no approved
endpoint is available and completes it later; the app only submits and reads."""

import os
from typing import List, Optional

import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:4000")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "swiss-ai/apertus-v1.5-70b")


class GatewayUnreachable(Exception):
    """The gateway itself did not answer. The app keeps the letter and hands it over later."""


class GatewayRejected(Exception):
    """The gateway refused the request (policy or input). Retrying will not help."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {GATEWAY_API_KEY}"}


async def _request(method: str, path: str, **kw) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{GATEWAY_URL}{path}", headers=_headers(), **kw)
    except httpx.HTTPError as e:
        raise GatewayUnreachable(type(e).__name__) from e
    if r.status_code in (400, 401, 403, 404, 422):
        raise GatewayRejected(f"{r.status_code}: {r.text[:500]}")
    if r.status_code >= 400:
        raise GatewayUnreachable(f"{r.status_code}: {r.text[:200]}")
    return r.json()


async def submit(messages: list, metadata: Optional[dict] = None) -> dict:
    body = {"model": GATEWAY_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 1800,
            "metadata": metadata or {}}
    return await _request("POST", "/v1/deferred/chat/completions", json=body)


async def job(job_id: str) -> dict:
    return await _request("GET", "/v1/deferred/jobs", params={"id": job_id})


async def events(job_id: str) -> List[dict]:
    return (await _request("GET", "/v1/deferred/events", params={"id": job_id}))["data"]


async def retry(job_id: str) -> dict:
    return await _request("POST", "/v1/deferred/retry", json={"id": job_id})


async def cancel(job_id: str) -> dict:
    return await _request("POST", "/v1/deferred/cancel", json={"id": job_id})
