"""custom_auth for tag experiments: binds tags to the API key / team (server-side), like a commune key would."""
from fastapi import Request
from litellm.proxy._types import UserAPIKeyAuth, LitellmUserRoles

KEYS = {
    # commune key: tags bound on the key metadata
    "sk-commune": dict(api_key="sk-commune", key_alias="commune", metadata={"tags": ["ch"]}, models=["A", "B", "C", "D"]),
    # commune key: tags bound on the team metadata
    "sk-team": dict(api_key="sk-team", key_alias="team-key", team_id="t-commune", team_metadata={"tags": ["ch"]}, models=["A", "B", "C", "D"]),
    # key with no tags
    "sk-open": dict(api_key="sk-open", key_alias="open", models=["A", "B", "C", "D"]),
}


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    k = KEYS.get(api_key)
    if k is None:
        raise Exception("invalid key")
    return UserAPIKeyAuth(**k)
