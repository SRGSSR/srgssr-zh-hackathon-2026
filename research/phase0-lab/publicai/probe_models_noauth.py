"""Probe: is GET https://api.publicai.co/v1/models reachable WITHOUT an API key?

Safety: sends NO API key, NO body, NO personal data. One GET request plus one
GET with an obviously-invalid bearer token is NOT done (we never send keys).
Records status code, response headers and the first bytes of the body so we
can see which gateway (Zuplo / LiteLLM) answers and which headers it exposes.

Run on the host: python3 probe_models_noauth.py
"""
import json
import sys
import urllib.error
import urllib.request

URL = "https://api.publicai.co/v1/models"


def probe(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, hdrs, body = r.status, dict(r.headers.items()), r.read(4000)
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, dict(e.headers.items()), e.read(4000)
    return {
        "url": url,
        "request_headers": headers,
        "status": status,
        "response_headers": hdrs,
        "body_prefix": body.decode("utf-8", "replace"),
    }


if __name__ == "__main__":
    results = [
        probe(URL, {"User-Agent": "swiss-ai-weeks-hackathon-research/0.1"}),
        # Same path without User-Agent-ish custom value (docs say UA is required).
        probe(URL, {"User-Agent": "Python-urllib/3"}),
    ]
    out = json.dumps(results, indent=1)
    print(out)
    open(sys.argv[1] if len(sys.argv) > 1 else "probe_models_noauth.out.json", "w").write(out)
