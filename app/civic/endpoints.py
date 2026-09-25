"""Endpoint registry for the UI, read from the gateway's own config (single source of truth),
plus the fault-injection control API of each endpoint."""

import asyncio
import os
from typing import Dict, List

import httpx
import yaml

GATEWAY_CONFIG = os.environ.get("GATEWAY_CONFIG", "/config/gateway.yaml")
# Display only. The gateway enforces the real rule from the key-bound policy.
DISPLAY_ALLOWED_JURISDICTIONS = os.environ.get("DISPLAY_ALLOWED_JURISDICTIONS", "CH").split(",")
REQUIRED = ("provider", "country", "jurisdiction")
PLACES = {"CH": "Switzerland", "EU": "the EU", "US": "the United States", "SG": "Singapore", "PL": "Poland", "DE": "Germany"}
GROUPS = {"swiss-ai/apertus-v1.5-70b": "Apertus", "aisingapore/Qwen-SEA-LION-v4-32B-IT": "SEA-LION, a different model"}


def place(code):
    """Human name of a jurisdiction code, or None if unknown."""
    return PLACES.get(code) if code else None


def load() -> List[Dict]:
    with open(GATEWAY_CONFIG) as f:
        cfg = yaml.safe_load(f)
    fallbacks = {}
    for entry in (cfg.get("router_settings") or {}).get("fallbacks") or []:
        fallbacks.update(entry)
    out = []
    for d in cfg.get("model_list", []):
        mi = d.get("model_info") or {}
        missing = [f for f in REQUIRED if not mi.get(f)]
        if missing:
            rule = f"excluded: missing {', '.join(missing)}"
        elif mi["jurisdiction"] in DISPLAY_ALLOWED_JURISDICTIONS:
            rule = "approved"
        else:
            rule = f"excluded: jurisdiction {mi['jurisdiction']}"
        j = mi.get("jurisdiction")
        if missing:
            why, reach = "Never used: its location is unknown", "never"
        elif j == "CH":
            why, reach = "In Switzerland: allowed by every rule", "all"
        elif j == "EU":
            why, reach = "In the EU: school and other offices only", "some"
        elif j == "US":
            why, reach = "In the United States: only if a resident agrees", "consent"
        else:
            why, reach = f"Never used: it is in {place(j) or j}", "never"
        out.append(
            {
                "why": why,
                "reach": reach,
                "id": mi.get("id"),
                "label": mi.get("label", mi.get("id")),
                "name": mi.get("display_name") or mi.get("id"),
                "place": place(mi.get("jurisdiction")),
                "model_group": d["model_name"],
                "provider": mi.get("provider"),
                "country": mi.get("country"),
                "jurisdiction": mi.get("jurisdiction"),
                "jurisdiction_basis": mi.get("jurisdiction_basis"),
                "kind": mi.get("endpoint_kind", "simulated"),
                "priority": mi.get("priority"),
                "control_url": mi.get("control_url"),
                "approved": rule == "approved",
                "rule": rule,
                "fallback_of": [k for k, v in fallbacks.items() if d["model_name"] in v],
            }
        )
    return out


def by_id() -> Dict[str, Dict]:
    return {e["id"]: e for e in load()}


async def status() -> List[Dict]:
    eps = load()

    async def one(client, e):
        try:
            r = await client.get(f"{e['control_url']}/control")
            e["state"] = r.json()
        except Exception as ex:
            e["state"] = {"mode": "unreachable", "received": None, "error": type(ex).__name__}
        return e

    async with httpx.AsyncClient(timeout=2) as client:
        return await asyncio.gather(*(one(client, e) for e in eps))


async def set_mode(endpoint_id: str, mode: str) -> None:
    e = by_id()[endpoint_id]
    async with httpx.AsyncClient(timeout=3) as client:
        await client.post(f"{e['control_url']}/control", json={"mode": mode})


async def set_mode_many(ids: List[str], mode: str) -> None:
    await asyncio.gather(*(set_mode(i, mode) for i in ids))


async def reset_all() -> None:
    async with httpx.AsyncClient(timeout=3) as client:
        await asyncio.gather(*(client.post(f"{e['control_url']}/control/reset") for e in load()))
