"""Reproducible harness: mocks + real LiteLLM v1.92.0 proxy (no DB) inside the Utility image.

Run experiment scripts with:  cd lab && ./run.sh proxy/<exp>.py
Everything happens inside ONE container: mocks run in threads, proxy is a subprocess on :4000.
"""
import copy
import json
import os
import subprocess
import sys
import time

import httpx
import yaml

sys.path.insert(0, "/lab/proxy")
from mock_sse import start_mocks  # noqa: E402

HERE = "/lab/proxy"
OUT_DIR = f"{HERE}/out"
PROXY = "http://127.0.0.1:4000"
MASTER = "sk-master"

MOCK_PORTS = {"mock-ch-1": 9101, "mock-ch-2": 9102, "mock-sg-1": 9103, "mock-pl-1": 9104, "mock-nometa": 9105}


def dep(group, dep_id, port, provider=None, country=None, jurisdiction=None, extra_params=None):
    mi = {"id": dep_id}
    if provider:
        mi["provider"] = provider
    if country:
        mi["country"] = country
    if jurisdiction:
        mi["jurisdiction"] = jurisdiction
    lp = {"model": f"openai/{group}-upstream", "api_base": f"http://127.0.0.1:{port}/v1", "api_key": f"k-{dep_id}"}
    lp.update(extra_params or {})
    return {"model_name": group, "litellm_params": lp, "model_info": mi}


BASE_CONFIG = {
    "model_list": [
        dep("apertus-ch", "ch-1", 9101, "infomaniak", "CH", "CH"),
        dep("apertus-ch", "ch-2", 9102, "phoeniqs", "CH", "CH"),
        dep("sealion-sg", "sg-1", 9103, "sea-lion", "SG", "SG"),
        dep("bielik-pl", "pl-1", 9104, "plgrid", "PL", "EU"),
        dep("nometa", "nm-1", 9105),  # no provider/country/jurisdiction metadata
        # one model group mixing jurisdictions (for tag-routing / in-group filtering tests)
        dep("mixed", "mx-ch", 9101, "infomaniak", "CH", "CH", extra_params={"tags": ["ch"]}),
        dep("mixed", "mx-sg", 9103, "sea-lion", "SG", "SG", extra_params={"tags": ["sg"]}),
    ],
    "router_settings": {
        # cross-jurisdiction fallback, exactly the Utility pattern (apertus -> SEA-LION)
        "fallbacks": [{"apertus-ch": ["sealion-sg"]}],
        "num_retries": 1,
        "retry_after": 0,
        "disable_cooldowns": True,  # deterministic tests
        "routing_strategy": "simple-shuffle",
    },
    "litellm_settings": {
        "callbacks": ["probe.probe_instance"],
        "request_timeout": 3,
        "drop_params": True,
    },
    "general_settings": {
        "master_key": MASTER,
        "custom_auth": "custom_auth_commune.user_api_key_auth",
        "custom_auth_settings": {"mode": "auto"},  # same as Utility configmap.yaml
    },
}


class Proxy:
    def __init__(self, name, config=None, env=None, mocks=None):
        self.name = name
        self.config = copy.deepcopy(config or BASE_CONFIG)
        self.env = env or {}
        self.mocks = mocks
        self.proc = None
        os.makedirs(OUT_DIR, exist_ok=True)
        self.cfg_path = f"{HERE}/config_{name}.yaml"  # must live next to probe.py / custom_auth_commune.py
        self.probe_path = f"{OUT_DIR}/probe_{name}.jsonl"
        self.log_path = f"{OUT_DIR}/proxy_{name}.log"

    def __enter__(self):
        if self.mocks is None:
            self.mocks = start_mocks(MOCK_PORTS)
        with open(self.cfg_path, "w") as f:
            yaml.safe_dump(self.config, f, sort_keys=False)
        if os.path.exists(self.probe_path):
            os.remove(self.probe_path)
        env = {**os.environ, "PROBE_OUT": self.probe_path, **self.env}
        env.pop("DATABASE_URL", None)
        self.logf = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            ["litellm", "--config", self.cfg_path, "--port", "4000", "--num_workers", "1"],
            stdout=self.logf, stderr=subprocess.STDOUT, env=env)
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                r = httpx.get(f"{PROXY}/health/liveliness", timeout=1)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"proxy died, see {self.log_path}")
            time.sleep(0.5)
        else:
            raise RuntimeError("proxy did not start")
        return self

    def __exit__(self, *a):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
        self.logf.close()

    # ------------------------------------------------------------------
    def reset(self):
        for m in self.mocks.values():
            m.reset()
        open(self.probe_path, "w").close()

    def counts(self):
        """requests that reached each mock (chat + any other path)"""
        return {k: m.total for k, m in self.mocks.items() if m.total}

    def other_paths(self):
        return {k: [o["method"] + " " + o["path"] for o in m.other] for k, m in self.mocks.items() if m.other}

    def probe(self):
        time.sleep(0.4)  # async logging callbacks run after the response
        try:
            with open(self.probe_path) as f:
                return [json.loads(line) for line in f if line.strip()]
        except FileNotFoundError:
            return []

    def chat(self, key, body=None, headers=None, model="apertus-ch", stream=False, timeout=30):
        b = {"model": model, "messages": [{"role": "user", "content": "Bürgeranfrage: Steuererklärung"}]}
        if stream:
            b["stream"] = True
        b.update(body or {})
        h = {"Authorization": f"Bearer {key}"}
        h.update(headers or {})
        if stream:
            chunks = []
            with httpx.stream("POST", f"{PROXY}/v1/chat/completions", json=b, headers=h, timeout=timeout) as r:
                for line in r.iter_lines():
                    if line:
                        chunks.append(line)
                return Resp(r.status_code, dict(r.headers), None, chunks)
        r = httpx.post(f"{PROXY}/v1/chat/completions", json=b, headers=h, timeout=timeout)
        try:
            j = r.json()
        except Exception:
            j = {"_text": r.text[:500]}
        return Resp(r.status_code, dict(r.headers), j, None)


class Resp:
    def __init__(self, status, headers, body, chunks):
        self.status, self.headers, self.body, self.chunks = status, headers, body, chunks

    def litellm_headers(self):
        return {k: v for k, v in self.headers.items()
                if k.startswith("x-litellm") or k.startswith("llm_provider") or k.startswith("x-commune")
                or k.startswith("x-ratelimit") or k.startswith("x-mock")}

    def model(self):
        if self.body and isinstance(self.body, dict):
            return self.body.get("model")
        return None

    def content(self):
        if self.chunks is not None:
            out = []
            for c in self.chunks:
                if c.startswith("data: ") and c != "data: [DONE]":
                    try:
                        j = json.loads(c[6:])
                        out.append(((j.get("choices") or [{}])[0].get("delta") or {}).get("content") or "")
                        if "error" in j:
                            out.append(f"<ERROR {j['error']}>")
                    except Exception:
                        out.append(f"<unparsable {c[:80]}>")
            return "".join(out)
        try:
            return self.body["choices"][0]["message"]["content"]
        except Exception:
            return None

    def error(self):
        if self.body and isinstance(self.body, dict) and "error" in self.body:
            e = self.body["error"]
            return (str(e.get("message"))[:300], e.get("type"), e.get("code"))
        return None


def show(title, resp, proxy, extra=None):
    print(f"\n=== {title}")
    print("status:", resp.status, "| mock counts:", proxy.counts())
    if resp.body is not None:
        print("model:", resp.model(), "| content:", resp.content(), "| error:", resp.error())
    if resp.chunks is not None:
        print("stream chunks:", len(resp.chunks), "| content:", repr(resp.content()))
        print("first:", resp.chunks[0][:160] if resp.chunks else None)
        print("last:", resp.chunks[-2:] if resp.chunks else None)
    print("headers:", json.dumps(resp.litellm_headers(), indent=1, sort_keys=True))
    if extra:
        print(extra)
