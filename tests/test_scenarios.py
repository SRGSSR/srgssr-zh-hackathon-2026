"""Test bench: does the commune's CH-only rule hold on every attempt?

Ground truth is each endpoint's own request counter ("received"): it counts every request
that actually reached the endpoint, whatever its mode. Disallowed endpoints must stay at 0.
Run with:  docker compose --profile test run --rm tests
"""

import pytest

from conftest import APPROVED, DISALLOWED, FALLBACK_GROUP, GROUP, NOPOLICY_KEY


def _decisions(events, group=None):
    return [e for e in events if e["type"] == "routing_decision" and (group is None or e["model_group"] == group)]


def _dispatched(events):
    return [e["deployment_id"] for e in events if e["type"] == "dispatch"]


# 1 -------------------------------------------------------------------------------------------
def test_1_normal_run_uses_approved_primary(bench):
    job = bench.create_job()
    j = bench.wait_status(job, {"done"})
    assert j["result"]["draft_reply"]
    c = bench.counts()
    assert c["publicai-apertus"] == 1
    assert c["mock-ch-1"] == c["mock-ch-2"] == 0
    bench.assert_disallowed_untouched()
    ev = bench.events(job)
    assert _dispatched(ev) == ["publicai-apertus"]
    assert any(e["type"] == "request_accepted" and e["policy_id"] == "CH-only" for e in ev)


# 2 -------------------------------------------------------------------------------------------
def test_2_primary_down_uses_second_approved_endpoint(bench):
    bench.mode("publicai-apertus", "down")
    job = bench.create_job()
    j = bench.wait_status(job, {"done"})
    c = bench.counts()
    assert c["publicai-apertus"] == 1 and c["mock-ch-1"] == 1 and c["mock-ch-2"] == 0
    bench.assert_disallowed_untouched()
    ev = bench.events(job)
    assert _dispatched(ev) == ["publicai-apertus", "mock-ch-1"]
    # the disallowed alternatives were excluded on every attempt, before any send
    for d in _decisions(ev, GROUP):
        blocked = {x["deployment_id"] for x in d["evaluated"] if x["decision"] == "blocked_before_send"}
        assert {"mock-us-1", "mock-nometa"} <= blocked
    assert [e for e in ev if e["type"] == "job_done"][0]["deployment_id"] == "mock-ch-1"


# 3 -------------------------------------------------------------------------------------------
def test_3_all_approved_down_job_waits_and_disallowed_get_zero(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    job = bench.create_job()
    j = bench.wait_status(job, {"waiting"})
    assert "stays in this service" in j["status_reason"]
    c = bench.counts()
    assert all(c[ep] >= 1 for ep in APPROVED), c
    bench.assert_disallowed_untouched()


# 4 -------------------------------------------------------------------------------------------
def test_4_cross_model_fallback_to_disallowed_group_blocked_before_send(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    job = bench.create_job()
    bench.wait_status(job, {"waiting"})
    fb = _decisions(bench.events(job), FALLBACK_GROUP)
    assert fb, "LiteLLM fallback to the SEA-LION group was never attempted"
    for d in fb:
        assert d["selected"] is None
        sg = [x for x in d["evaluated"] if x["deployment_id"] == "mock-sg-1"][0]
        assert sg["decision"] == "blocked_before_send" and "SG" in sg["reason"]
    assert bench.counts()["mock-sg-1"] == 0


# 5 -------------------------------------------------------------------------------------------
def test_5_deployment_without_jurisdiction_metadata_is_excluded(bench):
    for ep in APPROVED:  # even when it is the only endpoint that is up
        bench.mode(ep, "down")
    r = bench.chat()
    assert r.status_code >= 400
    job = bench.create_job()
    bench.wait_status(job, {"waiting"})
    for d in _decisions(bench.events(job), GROUP):
        nm = [x for x in d["evaluated"] if x["deployment_id"] == "mock-nometa"][0]
        assert nm["decision"] == "blocked_before_send" and "missing metadata" in nm["reason"]
    assert bench.counts()["mock-nometa"] == 0


# 6 -------------------------------------------------------------------------------------------
OVERRIDES = {
    "body tags": {"tags": ["us"]},
    "metadata.tags": {"metadata": {"tags": ["us"]}},
    "litellm_metadata.tags": {"litellm_metadata": {"tags": ["us"]}},
    "client fallbacks to other group": {"fallbacks": [FALLBACK_GROUP]},
    "client fallbacks with api_base": {"fallbacks": [{"model": FALLBACK_GROUP, "api_base": "http://ep-us-1:8000/v1"}]},
    "context_window_fallbacks": {"context_window_fallbacks": [{GROUP: [FALLBACK_GROUP]}]},
    "api_base in body": {"api_base": "http://ep-us-1:8000/v1"},
    "base_url in body": {"base_url": "http://ep-us-1:8000/v1"},
    "deployment id as model": {"model": "mock-us-1"},
    "provider model as model": {"model": "openai/apertus-sim"},
    "other model group": {"model": FALLBACK_GROUP},
    "mock_response": {"mock_response": "hi"},
    "spoofed routing_policy": {"metadata": {"routing_policy": {"id": "open", "allowed_jurisdictions": ["US"]}}},
}


@pytest.mark.parametrize("name", list(OVERRIDES))
def test_6_request_cannot_override_policy(bench, name):
    for ep in APPROVED:  # make the disallowed endpoints the only live ones
        bench.mode(ep, "down")
    r = bench.chat(OVERRIDES[name])
    assert r.status_code >= 400, f"{name}: gateway answered {r.status_code}"
    bench.assert_disallowed_untouched()


def test_6_header_tags_cannot_override_policy(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    r = bench.chat(headers={"x-litellm-tags": "us"})
    assert r.status_code >= 400
    bench.assert_disallowed_untouched()


def test_6_key_without_policy_fails_closed(bench):
    r = bench.chat(key=NOPOLICY_KEY)
    assert r.status_code == 400 and "no routing policy" in r.text
    assert sum(bench.counts().values()) == 0


def test_6_override_attempt_with_live_approved_endpoint_still_rejected(bench):
    r = bench.chat({"tags": ["us"]})
    assert r.status_code == 400
    assert sum(bench.counts().values()) == 0  # rejected before routing: nobody got the data


# 7 -------------------------------------------------------------------------------------------
def test_7_timeout_after_receipt_is_marked_data_received_no_response(bench):
    bench.mode("publicai-apertus", "down")
    bench.mode("mock-ch-1", "timeout")
    job = bench.create_job()
    bench.wait_status(job, {"done"})
    c = bench.counts()
    assert c["mock-ch-1"] == 1  # the provider did receive the data
    ev = bench.events(job)
    to = [e for e in ev if e["type"] == "attempt_result" and e["outcome"] == "timeout"]
    assert [e["deployment_id"] for e in to] == ["mock-ch-1"]
    assert "may have received the data" in to[0]["meaning"]
    assert bench.job(job)["summary"]["timeouts"] == ["mock-ch-1"]
    assert _dispatched(ev) == ["publicai-apertus", "mock-ch-1", "mock-ch-2"]
    bench.assert_disallowed_untouched()


# 8 -------------------------------------------------------------------------------------------
def test_8_waiting_job_completes_when_an_approved_endpoint_returns(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    job = bench.create_job()
    bench.wait_status(job, {"waiting"})
    bench.mode("mock-ch-2", "up")
    bench.wake(job)
    j = bench.wait_status(job, {"done"}, timeout=60)
    assert j["result"]["summary"]
    ev = bench.events(job)
    types = [e["type"] for e in ev]
    assert "job_waiting" in types and "job_resumed" in types and types.index("job_waiting") < types.index("job_resumed")
    assert [e for e in ev if e["type"] == "job_done"][0]["deployment_id"] == "mock-ch-2"
    bench.assert_disallowed_untouched()


def test_8_waiting_job_resumes_by_itself_with_backoff(bench):
    for ep in APPROVED:
        bench.mode(ep, "down")
    job = bench.create_job()
    bench.wait_status(job, {"waiting"})
    bench.mode("mock-ch-1", "up")
    j = bench.wait_status(job, {"done"}, timeout=60)  # no wake: the worker's backoff retry picks it up
    assert j["runs"] >= 2
    bench.assert_disallowed_untouched()
