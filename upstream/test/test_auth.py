"""Test-only stand-in for the Utility's custom_auth.py (which needs their DB).
In production the routing_policy would live in the metadata of a virtual key or team,
e.g. POST /key/generate {"metadata": {"routing_policy": {...}}}."""
from fastapi import Request
from litellm.proxy._types import UserAPIKeyAuth

KEYS = {
    "sk-commune": {"key_alias": "commune-ch-only", "metadata": {"routing_policy": {"id": "CH-only", "allowed_jurisdictions": ["CH"]}}},
    "sk-regular": {"key_alias": "regular-user", "metadata": {}},
    # policy on the team (the institution); the key's own metadata tries to relax it and must not win
    "sk-team-member": {"key_alias": "commune-staff", "team_id": "gemeinde-musterstadt",
                       "team_metadata": {"routing_policy": {"id": "CH-only", "allowed_jurisdictions": ["CH"]}},
                       "metadata": {"routing_policy": {"id": "open", "allowed_jurisdictions": ["CH", "unknown", "SG", "PL"]}}},
}


async def user_api_key_auth(request: Request, api_key: str):
    spec = KEYS.get(api_key)
    if spec is None:
        return api_key
    return UserAPIKeyAuth(api_key=api_key, **spec)
