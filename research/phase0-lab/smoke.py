import asyncio, litellm
from litellm import Router
from mock_openai import start_mocks
m = start_mocks({"mock-ch-1": 9101})
r = Router(model_list=[{"model_name": "apertus", "litellm_params": {"model": "openai/x", "api_base": "http://127.0.0.1:9101/v1", "api_key": "k"}, "model_info": {"id": "mock-ch-1"}}])
resp = asyncio.run(r.acompletion(model="apertus", messages=[{"role": "user", "content": "hi"}]))
print(resp.choices[0].message.content, m["mock-ch-1"].count, resp._hidden_params.get("model_id"))
