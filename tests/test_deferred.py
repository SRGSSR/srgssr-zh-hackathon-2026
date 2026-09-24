"""The waiting logic lives in the gateway (gateway/deferred.py), not in each application.
These tests talk to the gateway's deferred API directly, without the citizen app."""

import time

import pytest

from conftest import APPROVED, FALLBACK_GROUP, GATEWAY_URL, KEY, NOPOLICY_KEY


def test_deferred_request_waits_in_gateway_and_completes_without_any_app(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    r = bench.deferred_submit({"metadata": {"caller": "any-app"}})
    assert r.status_code == 202, r.text
    job = r.json()["id"]
    j = bench.deferred_wait(job, {"waiting"})
    assert j["request_retained"] is True  # kept in the gateway's store while waiting
    assert "not sent anywhere else" in j["status_reason"]
    bench.assert_disallowed_untouched()
    bench.mode("mock-ch-2", "up")
    j = bench.deferred_wait(job, {"done"}, timeout=60)  # the gateway's own backoff picks it up
    assert j["served_by"] == "mock-ch-2"
    assert j["result"]["choices"][0]["message"]["content"]
    assert j["request_retained"] is False  # the request body is deleted once the job ends
    assert j["metadata"] == {"caller": "any-app"}
    types = [e["type"] for e in bench.deferred("GET", "events", params={"id": job}).json()["data"]]
    for t in ("job_created", "request_accepted", "routing_decision", "job_waiting", "job_resumed", "job_done"):
        assert t in types, (t, types)
    bench.assert_disallowed_untouched()


@pytest.mark.parametrize("extra", [
    {"fallbacks": [FALLBACK_GROUP]},
    {"tags": ["us"]},
    {"stream": True},
    {"api_base": "http://ep-us-1:8000/v1"},
    {"metadata": {"deferred_job_id": "def-x"}},
    {"model": "mock-us-1"},
])
def test_deferred_submit_rejects_routing_params(bench, extra):
    before = len(bench.deferred("GET", "jobs", params={"limit": 200}).json()["data"])
    r = bench.deferred_submit(extra)
    assert r.status_code in (400, 401), r.text  # 401: LiteLLM's own auth already refuses api_base
    assert len(bench.deferred("GET", "jobs", params={"limit": 200}).json()["data"]) == before  # nothing stored
    assert sum(bench.counts().values()) == 0


def test_deferred_submit_without_policy_fails_closed(bench):
    r = bench.deferred_submit(key=NOPOLICY_KEY)
    assert r.status_code == 400 and "no routing policy" in r.text
    assert sum(bench.counts().values()) == 0


def test_deferred_job_visible_only_to_its_key(bench):
    job = bench.deferred_submit().json()["id"]
    bench.deferred_wait(job, {"done"})
    assert bench.deferred_job(job, key=NOPOLICY_KEY).status_code == 404
    assert bench.http.get(f"{GATEWAY_URL}/v1/deferred/jobs", params={"id": job}).status_code == 401  # no key
    assert bench.deferred("GET", "events", key=NOPOLICY_KEY, params={"id": job}).status_code == 404


def test_commune_key_cannot_call_other_routes(bench):
    for path in ("/v1/models", "/v1/model/info", "/key/info"):
        r = bench.http.get(f"{GATEWAY_URL}{path}", headers={"Authorization": f"Bearer {KEY}"})
        assert r.status_code in (401, 403), path


def test_cancelled_waiting_job_is_never_sent(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    job = bench.deferred_submit().json()["id"]
    bench.deferred_wait(job, {"waiting"})
    bench.deferred("POST", "cancel", json={"id": job})
    before = bench.counts()
    for ep in APPROVED:
        bench.mode(ep, "up")
    time.sleep(6)  # longer than the next retry would have been
    j = bench.deferred_job(job).json()
    assert j["status"] == "cancelled" and j["request_retained"] is False
    assert bench.counts() == before


def test_sync_request_cannot_write_into_a_deferred_timeline(bench):
    job = bench.deferred_submit().json()["id"]
    bench.deferred_wait(job, {"done"})
    time.sleep(0.5)
    before = bench.deferred("GET", "events", params={"id": job}).json()["data"]
    r = bench.chat({"metadata": {"deferred_job_id": job}})
    assert r.status_code == 400
    time.sleep(1)
    assert bench.deferred("GET", "events", params={"id": job}).json()["data"] == before
