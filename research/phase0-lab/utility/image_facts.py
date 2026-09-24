"""Facts about the exact Utility image: litellm version, enterprise package, key defaults."""
import sys, importlib.metadata as md
print("python", sys.version.split()[0])
for d in ("litellm", "litellm-enterprise", "litellm-proxy-extras"):
    try: print(d, md.version(d))
    except Exception as e: print(d, "NOT INSTALLED", e)
try:
    from litellm.proxy.auth.user_api_key_auth import enterprise_custom_auth
    print("enterprise_custom_auth loaded:", enterprise_custom_auth is not None)
except Exception as e:
    print("enterprise_custom_auth import error", e)
import litellm
from litellm.constants import DEFAULT_COOLDOWN_TIME_SECONDS
print("litellm.num_retries default:", litellm.num_retries, "allowed_fails default:", litellm.allowed_fails,
      "DEFAULT_COOLDOWN_TIME_SECONDS:", DEFAULT_COOLDOWN_TIME_SECONDS)
import litellm, os
print("litellm path", os.path.dirname(litellm.__file__))
