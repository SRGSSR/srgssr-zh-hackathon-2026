"""Lab-only custom_auth: maps fixed bearer tokens to identities (no DB in the lab).

sk-commune-x -> key alias commune-x, team commune-x, key+team metadata routing_policy=CH-only
sk-open      -> key alias open, no policy
anything else -> 401
"""
from fastapi import Request
from litellm.proxy._types import UserAPIKeyAuth


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    if api_key == "sk-commune-x":
        return UserAPIKeyAuth(api_key="hashed-commune-x", key_alias="commune-x", team_id="commune-x",
                              metadata={"routing_policy": "CH-only"}, team_metadata={"routing_policy": "CH-only"})
    if api_key == "sk-open":
        return UserAPIKeyAuth(api_key="hashed-open", key_alias="open", team_id="open-team")
    raise Exception("invalid key")
