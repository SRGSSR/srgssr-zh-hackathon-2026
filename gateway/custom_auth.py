"""Static, DB-less binding of API keys to communes and their routing policy.

Loaded by the proxy via general_settings.custom_auth (same mechanism as the Utility's
charts/platform/charts/litellm/custom_auth.py). The policy lives only in communes.yaml,
server side, and reaches every router hook as metadata["user_api_key_metadata"].
Key values come from environment variables, never from the file.
Unknown keys are returned unchanged so LiteLLM's own auth handles them (master key).
"""

import hashlib
import os
from typing import Dict, Union

import yaml
from fastapi import Request

from litellm.proxy._types import UserAPIKeyAuth

_FILE = os.environ.get("COMMUNES_FILE", os.path.join(os.path.dirname(__file__), "communes.yaml"))


def _load() -> Dict[str, dict]:
    with open(_FILE) as f:
        spec = yaml.safe_load(f) or {}
    keys = {}
    for c in spec.get("communes", []):
        value = os.environ.get(c["key_env"], "")
        if value:
            keys[value] = c
    return keys


_KEYS = _load()


async def user_api_key_auth(request: Request, api_key: str) -> Union[UserAPIKeyAuth, str]:
    c = _KEYS.get(api_key)
    if c is None:
        return api_key
    metadata = {"commune": c.get("team_alias")}
    if c.get("routing_policy"):
        metadata["routing_policy"] = c["routing_policy"]
    return UserAPIKeyAuth(
        api_key=hashlib.sha256(api_key.encode()).hexdigest(),
        key_alias=c["key_alias"],
        team_id=c.get("team_id"),
        team_alias=c.get("team_alias"),
        models=c.get("models", []),
        allowed_routes=c.get("allowed_routes"),
        metadata=metadata,
        team_metadata={"commune": c.get("team_alias")},
    )
