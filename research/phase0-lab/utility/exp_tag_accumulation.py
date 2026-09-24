"""Do deployment-level litellm_params.tags leak into request metadata.tags and ACCUMULATE across
retries / fallbacks? (router.py _update_kwargs_with_deployment merges deployment tags into kwargs metadata.)
Setup: group A = [a-unknown (down, tags jurisdiction:unknown)], fallback group B = [b-ch (up, tags jurisdiction:CH)].
Run: ./run.sh utility/exp_tag_accumulation.py
"""
import asyncio, json
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger
import litellm
from mock_openai import start_mocks

m = start_mocks({"a-unknown": 9311, "b-ch": 9312})
m["a-unknown"].mode = "down"
seen = []


class P(CustomLogger):
    async def async_log_pre_api_call(self, model, messages, kwargs):
        md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        seen.append({"hook": "pre", "api_base": (kwargs.get("litellm_params") or {}).get("api_base"),
                     "metadata.tags": md.get("tags"), "model_group": md.get("model_group")})

    def log_pre_api_call(self, model, messages, kwargs):
        md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        seen.append({"hook": "pre(sync)", "api_base": (kwargs.get("litellm_params") or {}).get("api_base"),
                     "metadata.tags": md.get("tags"), "model_group": md.get("model_group")})


litellm.callbacks = [P()]
r = Router(
    model_list=[
        {"model_name": "A", "litellm_params": {"model": "openai/x", "api_base": "http://127.0.0.1:9311/v1", "api_key": "k",
                                               "tags": ["jurisdiction:unknown"]}, "model_info": {"id": "a-unknown"}},
        {"model_name": "B", "litellm_params": {"model": "openai/x", "api_base": "http://127.0.0.1:9312/v1", "api_key": "k",
                                               "tags": ["jurisdiction:CH"]}, "model_info": {"id": "b-ch"}},
    ],
    fallbacks=[{"A": ["B"]}], num_retries=2,
)
user_md = {"tags": ["request-tag"]}
resp = asyncio.run(r.acompletion(model="A", messages=[{"role": "user", "content": "hi"}], metadata=user_md))
import time; time.sleep(0.5)
print("served by:", resp._hidden_params.get("model_id"), "counts:", {k: v.count for k, v in m.items()})
for s in seen:
    print(json.dumps(s))
print("caller's metadata dict after call (mutated in place?):", user_md)
