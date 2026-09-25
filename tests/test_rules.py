"""Three offices, three rules, each bound to its own key (gateway/communes.yaml):
social services "CH-only", school "CH-then-EU", other offices "CH-EU-then-consent".
A wider rule never comes from the request: only from the key, or from a resident's recorded
consent for one waiting letter, and only if the key's rule allows that consent."""

import time

from conftest import APPROVED, KEY, KEY_INFO, KEY_SCHOOL

SWISS = APPROVED  # publicai-apertus, mock-ch-1, mock-ch-2
NEVER = ["mock-nometa", "mock-sg-1"]


def _consent(bench, job, key=KEY_INFO, places=("US",)):
    return bench.deferred("POST", "consent", key=key, json={"id": job, "jurisdictions": list(places), "statement": "test"})


def _events(bench, job, key):
    return bench.deferred("GET", "events", key=key, params={"id": job}).json()["data"]


def _assert_never(bench, *extra):
    c = bench.counts()
    assert all(c[i] == 0 for i in NEVER + list(extra)), c


# school: CH first, then EU, never further ----------------------------------------------------
def test_school_rule_prefers_switzerland(bench):
    job = bench.deferred_submit(key=KEY_SCHOOL).json()["id"]
    j = bench.deferred_wait(job, {"done"}, key=KEY_SCHOOL)
    assert j["served_by"] == "publicai-apertus"
    _assert_never(bench, "mock-eu-1", "mock-us-1")


def test_school_rule_uses_the_eu_when_switzerland_is_down(bench):
    for ep in SWISS:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_SCHOOL).json()["id"]
    j = bench.deferred_wait(job, {"done"}, key=KEY_SCHOOL)
    assert j["served_by"] == "mock-eu-1"
    _assert_never(bench, "mock-us-1")


def test_school_rule_never_goes_beyond_the_eu_even_with_consent(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_SCHOOL).json()["id"]
    j = bench.deferred_wait(job, {"waiting"}, key=KEY_SCHOOL)
    assert j["rule"]["can_ask_consent_for"] == []
    assert _consent(bench, job, key=KEY_SCHOOL).status_code == 400
    _assert_never(bench, "mock-us-1")


# other offices: CH + EU, the US only with the resident's consent, for that letter ----------
def test_info_rule_waits_and_offers_consent(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_INFO).json()["id"]
    j = bench.deferred_wait(job, {"waiting"}, key=KEY_INFO)
    assert j["rule"]["can_ask_consent_for"] == ["US"] and j["consent"] is None
    _assert_never(bench, "mock-us-1")


def test_consent_sends_that_letter_only_to_the_us(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    a = bench.deferred_submit(key=KEY_INFO).json()["id"]
    b = bench.deferred_submit(key=KEY_INFO).json()["id"]
    bench.deferred_wait(a, {"waiting"}, key=KEY_INFO)
    bench.deferred_wait(b, {"waiting"}, key=KEY_INFO)
    assert _consent(bench, a).status_code == 200
    j = bench.deferred_wait(a, {"done"}, key=KEY_INFO, timeout=60)
    assert j["served_by"] == "mock-us-1" and j["consent"]["jurisdictions"] == ["US"]
    types = [e["type"] for e in _events(bench, a, KEY_INFO)]
    assert types.index("consent_given") < len(types) - 1
    sent = [e["deployment_id"] for e in _events(bench, a, KEY_INFO) if e["type"] == "dispatch"]
    assert sent[-1] == "mock-us-1" and "mock-us-1" not in sent[:-1]  # the US only after consent, last
    time.sleep(6)  # the other letter keeps waiting: consent is per letter
    other = bench.deferred_job(b, key=KEY_INFO).json()
    assert other["status"] in ("waiting", "running") and other["served_by"] is None and other["consent"] is None
    assert bench.counts()["mock-us-1"] == 1
    _assert_never(bench)


def test_consent_still_prefers_switzerland_if_it_came_back(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_INFO).json()["id"]
    bench.deferred_wait(job, {"waiting"}, key=KEY_INFO)
    bench.mode("mock-ch-2", "up")
    assert _consent(bench, job).status_code == 200
    j = bench.deferred_wait(job, {"done"}, key=KEY_INFO, timeout=60)
    assert j["served_by"] == "mock-ch-2"  # consent widens the rule, it does not skip Switzerland
    assert bench.counts()["mock-us-1"] == 0


def test_social_services_rule_refuses_consent(bench):
    for ep in SWISS:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY).json()["id"]
    bench.deferred_wait(job, {"waiting"}, key=KEY)
    assert _consent(bench, job, key=KEY).status_code == 400
    _assert_never(bench, "mock-us-1", "mock-eu-1")


def test_consent_through_another_key_is_refused(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_INFO).json()["id"]
    bench.deferred_wait(job, {"waiting"}, key=KEY_INFO)
    assert _consent(bench, job, key=KEY_SCHOOL).status_code == 404
    assert bench.counts()["mock-us-1"] == 0


def test_consent_for_a_place_the_rule_does_not_list_is_refused(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.deferred_submit(key=KEY_INFO).json()["id"]
    bench.deferred_wait(job, {"waiting"}, key=KEY_INFO)
    assert _consent(bench, job, places=("SG",)).status_code == 400
    _assert_never(bench, "mock-us-1")


def test_sync_requests_never_reach_the_us(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    r = bench.chat(key=KEY_INFO)
    assert r.status_code >= 400
    _assert_never(bench, "mock-us-1")


def test_consent_through_the_citizen_app(bench):
    for ep in SWISS + ["mock-eu-1"]:
        bench.mode(ep, "down")
    job = bench.create_job(service="info")
    j = bench.wait_status(job, {"waiting"})
    assert j["consent_options"] == ["US"]
    r = bench.http.post(f"{bench_app()}/api/jobs/{job}/consent", json={"jurisdictions": ["US"], "statement": "app test"})
    assert r.status_code == 200, r.text
    j = bench.wait_status(job, {"done"}, timeout=60)
    assert j["served_by"] == "mock-us-1"
    assert any(e["type"] == "consent_given" for e in bench.events(job))


def bench_app():
    from conftest import APP_URL
    return APP_URL
