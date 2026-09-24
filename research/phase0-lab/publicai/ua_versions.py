"""Print the User-Agent strings the pinned image's HTTP clients would send (no network)."""
import httpx, openai
from openai import AsyncOpenAI
c = AsyncOpenAI(api_key="sk-dummy-not-a-real-key", base_url="http://127.0.0.1:9/v1")
print("openai", openai.__version__, "UA:", c.user_agent)
print("httpx", httpx.__version__, "UA:", httpx.Client().headers.get("user-agent"))
import litellm
from importlib.metadata import version
print("litellm", version("litellm"))
