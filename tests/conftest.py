import os
import time

import httpx
import pytest
import yaml

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
APP_URL = os.environ.get("APP_URL", "http://localhost:8080")
KEY = os.environ.get("MUSTERSTADT_API_KEY", "sk-musterstadt-demo")  # social services: CH-only
KEY_SCHOOL = os.environ.get("MUSTERSTADT_SCHOOL_API_KEY", "sk-musterstadt-school-demo")  # CH, then EU
KEY_INFO = os.environ.get("MUSTERSTADT_INFO_API_KEY", "sk-musterstadt-info-demo")  # CH + EU, US only with consent
ALL_KEYS = (KEY, KEY_SCHOOL, KEY_INFO)
NOPOLICY_KEY = os.environ.get("NOPOLICY_API_KEY", "sk-nopolicy-test")
GATEWAY_CONFIG = os.environ.get("GATEWAY_CONFIG", os.path.join(os.path.dirname(__file__), "..", "gateway", "config.yaml"))
GROUP = "swiss-ai/apertus-v1.5-70b"
FALLBACK_GROUP = "aisingapore/Qwen-SEA-LION-v4-32B-IT"

APPROVED = ["publicai-apertus", "mock-ch-1", "mock-ch-2"]
DISALLOWED = ["mock-us-1", "mock-nometa", "mock-sg-1", "mock-eu-1"]  # under the CH-only rule

LETTER = (
    "Gemeinde Musterstadt, Finanzverwaltung\n"
    "Herr Luca Esempio, Beispielgasse 3, 9999 Musterstadt, AHV-Nr. 756.0000.0000.00\n"
    "2. Mahnung: Bitte bezahlen Sie CHF 326.40 bis spätestens 2. Oktober 2026."
)


def _control_urls():
    with open(GATEWAY_CONFIG) as f:
        cfg = yaml.safe_load(f)
    return {d["model_info"]["id"]: d["model_info"]["control_url"] for d in cfg["model_list"]}


CONTROL = _control_urls()


class Bench:
    def __init__(self):
        self.http = httpx.Client(timeout=200)

    # --- endpoints
    def mode(self, endpoint_id: str, mode: str):
        self.http.post(f"{CONTROL[endpoint_id]}/control", json={"mode": mode}).raise_for_status()

    def reset(self, simulate=True):
        """All endpoints up, counters at zero. The relay to the real Public AI API is switched to
        simulation, so the bench never calls the real service and stays deterministic."""
        for url in CONTROL.values():
            self.http.post(f"{url}/control/reset").raise_for_status()
        if simulate:
            self.http.post(f"{CONTROL['publicai-apertus']}/control", json={"simulate": True}).raise_for_status()

    def counts(self) -> dict:
        return {i: self.http.get(f"{u}/control").json()["received"] for i, u in CONTROL.items()}

    def assert_disallowed_untouched(self):
        c = self.counts()
        assert {i: c[i] for i in DISALLOWED} == {i: 0 for i in DISALLOWED}, f"disallowed endpoint received data: {c}"

    # --- gateway (direct)
    def chat(self, body_extra=None, key=KEY, headers=None, model=GROUP):
        body = {"model": model, "messages": [{"role": "user", "content": LETTER}]}
        body.update(body_extra or {})
        return self.http.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {key}", **(headers or {})},
        )

    # --- app
    def create_job(self, letter=LETTER, language="it", service="social") -> str:
        r = self.http.post(f"{APP_URL}/api/jobs", json={"letter": letter, "language": language, "service": service})
        r.raise_for_status()
        return r.json()["id"]

    def job(self, job_id):
        return self.http.get(f"{APP_URL}/api/jobs/{job_id}").json()

    def events(self, job_id):
        return self.http.get(f"{APP_URL}/api/jobs/{job_id}/events").json()

    def wait_status(self, job_id, statuses, timeout=90):
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = self.job(job_id)
            if j["status"] in statuses:
                time.sleep(0.5)  # let the last gateway events arrive
                return j
            time.sleep(0.5)
        raise AssertionError(f"job {job_id} did not reach {statuses}, last: {self.job(job_id)['status']}")

    # --- gateway deferred API (the queue lives in the gateway)
    def deferred(self, method, path, key=KEY, **kw):
        return self.http.request(method, f"{GATEWAY_URL}/v1/deferred/{path}", headers={"Authorization": f"Bearer {key}"}, **kw)

    def deferred_submit(self, body_extra=None, key=KEY):
        body = {"model": GROUP, "messages": [{"role": "user", "content": LETTER}]}
        body.update(body_extra or {})
        return self.deferred("POST", "chat/completions", key=key, json=body)

    def deferred_job(self, job_id, key=KEY):
        return self.deferred("GET", "jobs", key=key, params={"id": job_id})

    def deferred_wait(self, job_id, statuses, timeout=90, key=KEY):
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = self.deferred_job(job_id, key=key).json()
            if j["status"] in statuses:
                return j
            time.sleep(0.5)
        raise AssertionError(f"deferred job {job_id} did not reach {statuses}")

    def cancel_pending(self):
        """Cancel every unfinished deferred job of the commune key and wait until none is in flight,
        so a job from one test never reaches an endpoint during the next test."""
        pending = "queued,running,waiting"
        for key in ALL_KEYS:
            for j in self.deferred("GET", "jobs", key=key, params={"status": pending, "limit": 200}).json()["data"]:
                self.deferred("POST", "cancel", key=key, json={"id": j["id"]})
        deadline = time.time() + 45
        while time.time() < deadline:
            recent = [j for key in ALL_KEYS for j in self.deferred("GET", "jobs", key=key, params={"limit": 200}).json()["data"]]
            if not any(j["inflight"] for j in recent):
                return
            time.sleep(0.5)

    def wake(self, job_id):
        self.http.post(f"{APP_URL}/api/jobs/{job_id}/wake").raise_for_status()


@pytest.fixture
def bench():
    b = Bench()
    b.cancel_pending()
    b.reset()
    yield b
    b.cancel_pending()
    b.reset(simulate=False)  # leave the real relay on for the demo
