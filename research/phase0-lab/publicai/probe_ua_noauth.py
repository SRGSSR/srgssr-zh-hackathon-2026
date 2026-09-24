"""Probe: which User-Agent values get past Cloudflare in front of api.publicai.co?

Safety: NO API key, NO body, NO personal data. Only unauthenticated GET /v1/models.
Expected outcomes: 401 problem+json from Zuplo (UA accepted, auth missing) vs
403 'error code: 1010' from Cloudflare (UA / browser-signature blocked).

The UA values are the ones the pinned LiteLLM image's clients send by default
(see ua_versions.py): openai SDK 2.33.0 and httpx 0.28.1.
"""
import json
import sys
import urllib.error
import urllib.request

URL = "https://api.publicai.co/v1/models"
UAS = [
    "AsyncOpenAI/Python 2.33.0",   # openai SDK used by litellm openai/ provider
    "OpenAI/Python 2.33.0",
    "python-httpx/0.28.1",         # raw httpx default
    "litellm/1.92.0",
    None,                          # no User-Agent header at all
]


def probe(ua):
    headers = {} if ua is None else {"User-Agent": ua}
    req = urllib.request.Request(URL, headers=headers, method="GET")
    if ua is None:
        # urllib always adds its own UA unless we override; set empty to suppress
        req.add_header("User-Agent", "")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            st, h, b = r.status, dict(r.headers.items()), r.read(600)
    except urllib.error.HTTPError as e:
        st, h, b = e.code, dict(e.headers.items()), e.read(600)
    return {
        "ua": ua,
        "status": st,
        "zuplo_rid": h.get("zp-rid"),
        "content_type": h.get("Content-Type"),
        "cf_ray": h.get("CF-RAY"),
        "body_prefix": b.decode("utf-8", "replace")[:200],
    }


if __name__ == "__main__":
    res = [probe(u) for u in UAS]
    out = json.dumps(res, indent=1)
    print(out)
    open(sys.argv[1] if len(sys.argv) > 1 else "probe_ua_noauth.out.json", "w").write(out)
