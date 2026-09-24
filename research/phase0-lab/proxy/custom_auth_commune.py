"""Static, DB-less key -> policy binding via general_settings.custom_auth.

Mirrors the shape of the Utility's custom_auth.py (charts/platform/charts/litellm/custom_auth.py):
unknown keys are returned as a str so LiteLLM's own auth handles them (master key only without DB).

The policy lives ONLY here (server side): key metadata + team metadata + models allowlist.
Nothing in the request can change it.
"""
import os
from typing import Union

from fastapi import Request

from litellm.proxy._types import UserAPIKeyAuth

# In real life: load from a mounted file / secret, never from the request.
COMMUNE_KEYS = {
    # commune A: key-level models allowlist + policy metadata
    "sk-commune-a": dict(
        key_alias="commune-a",
        team_id="team-commune-a",
        team_alias="Gemeinde A",
        models=["apertus-ch"],
        metadata={"policy_id": "CH-only", "allowed_jurisdictions": ["CH"], "tags": ["commune-a"]},
        team_metadata={"policy_id": "CH-only", "commune": "Gemeinde A"},
    ),
    # commune B: NO models allowlist, policy only in metadata (enforced by our hook, if enabled)
    "sk-commune-b": dict(
        key_alias="commune-b",
        team_id="team-commune-b",
        team_alias="Gemeinde B",
        models=[],
        metadata={"policy_id": "CH-only", "allowed_jurisdictions": ["CH"]},
        team_metadata={"policy_id": "CH-only", "commune": "Gemeinde B"},
    ),
    # tag-routing experiment: server-side key tag "ch", no allowed_jurisdictions (probe does not enforce)
    "sk-commune-t": dict(
        key_alias="commune-t",
        team_id="team-commune-t",
        models=[],
        metadata={"tags": ["ch"]},
        team_metadata={},
    ),
    # route-restriction experiment: key-level allowed_routes
    "sk-commune-r": dict(
        key_alias="commune-r",
        team_id="team-commune-r",
        models=["apertus-ch"],
        allowed_routes=["/chat/completions", "/v1/chat/completions"],
        metadata={"policy_id": "CH-only", "allowed_jurisdictions": ["CH"]},
        team_metadata={},
    ),
}

EXTRA =os.environ.get("AUTH_EXTRA", "")  # e.g. "disable_fallbacks" to test key-level controls


async def user_api_key_auth(request: Request, api_key: str) -> Union[UserAPIKeyAuth, str]:
    spec = COMMUNE_KEYS.get(api_key)
    if spec is None:
        return api_key  # let LiteLLM handle it (master key)
    spec = {**spec, "metadata": dict(spec["metadata"])}
    if EXTRA == "disable_fallbacks":
        spec["metadata"]["disable_fallbacks"] = True
    return UserAPIKeyAuth(api_key=api_key, **spec)
