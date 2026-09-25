"""Client for the gateway's deferred API. The gateway keeps the request while no approved
endpoint is available and completes it later; the app only submits and reads."""

import os
from typing import List, Optional

import httpx

from .letters import SERVICES

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:4000")
GATEWAY_MODEL = os.environ.get("GATEWAY_MODEL", "swiss-ai/apertus-v1.5-70b")


def key_for(service: str) -> str:
    """Each office of the commune has its own key; the gateway binds the rule to it."""
    spec = SERVICES.get(service) or SERVICES["social"]
    return os.environ.get(spec["key_env"], "")


class GatewayUnreachable(Exception):
    """The gateway itself did not answer. The app keeps the letter and hands it over later."""


class GatewayRejected(Exception):
    """The gateway refused the request (policy or input). Retrying will not help."""


async def _request(method: str, path: str, service: str, **kw) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{GATEWAY_URL}{path}", headers={"Authorization": f"Bearer {key_for(service)}"}, **kw)
    except httpx.HTTPError as e:
        raise GatewayUnreachable(type(e).__name__) from e
    if r.status_code in (400, 401, 403, 404, 422):
        raise GatewayRejected(f"{r.status_code}: {r.text[:500]}")
    if r.status_code >= 400:
        raise GatewayUnreachable(f"{r.status_code}: {r.text[:200]}")
    return r.json()


async def submit(service: str, messages: list, metadata: Optional[dict] = None) -> dict:
    body = {"model": GATEWAY_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 1200,
            "metadata": metadata or {}}
    return await _request("POST", "/v1/deferred/chat/completions", service, json=body)


async def job(service: str, job_id: str) -> dict:
    return await _request("GET", "/v1/deferred/jobs", service, params={"id": job_id})


async def events(service: str, job_id: str) -> List[dict]:
    return (await _request("GET", "/v1/deferred/events", service, params={"id": job_id}))["data"]


async def retry(service: str, job_id: str) -> dict:
    return await _request("POST", "/v1/deferred/retry", service, json={"id": job_id})


async def cancel(service: str, job_id: str) -> dict:
    return await _request("POST", "/v1/deferred/cancel", service, json={"id": job_id})


async def consent(service: str, job_id: str, jurisdictions: List[str], statement: str) -> dict:
    return await _request("POST", "/v1/deferred/consent", service,
                          json={"id": job_id, "jurisdictions": jurisdictions, "statement": statement})
