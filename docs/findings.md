# Phase 0 findings: LiteLLM routing in the Public AI Utility

Status: 2026-09-24, about 20:00, corrected about 21:15 (version, see section 1). The research was cut short on purpose. Results come from experiments run in the exact image the Utility uses, plus reading its source. They have **not** been re-checked by independent verifiers yet. Evidence lives in `research/phase0-lab/`: `./run.sh <script>` runs a script inside `ghcr.io/forpublicai/litellm-database:v1.92.0` against mock endpoints that count every request they receive.

## TL;DR

1. **Version (corrected).** Prod and staging run `ghcr.io/forpublicai/litellm-database:v1.98.0`: `argo/environments/{prod,staging}/platform-values.yaml` override the chart default `v1.92.0` in `values.yaml`. Phase 0 first read only the chart default. Most experiments below ran on v1.92.0; the key ones were re-run on v1.98.0 and are marked. At v1.92.0 the fork is upstream (`b3086ccd`) plus a spend-logs fix and a CI workflow.
2. **The Utility's own config shows the problem.** `swiss-ai/apertus-v1.5-70b` is served by Infomaniak (CH) and Featherless (country not stated). Its fallbacks are `aisingapore/Qwen-SEA-LION-v4-32B-IT` (api.sea-lion.ai, SG) and `speakleash/Bielik-11B-v3.0-Instruct` (llmlab.plgrid.pl, PL). Every Apertus group can reach non-CH hosts and other model families through fallbacks.
3. **Tag routing cannot enforce "CH-only".** It is unsafe in five ways:
   - The router merges the tags of each deployment it tries into the request's tags, so retries and fallbacks use a wider tag set.
   - `litellm_metadata.tags` in the request body overrides the tags bound to the key.
   - `model=<deployment id>` skips the tag filter.
   - The sync `completion()` path and `usage-based-routing` v1 do not filter by tags at all.
   - Cooldown runs before the tag filter, so the error message is misleading.
4. **Security issue in v1.92.0, fixed by v1.98.0 (re-tested).** A client-supplied `fallbacks=[{"model": ..., "api_base": <attacker host>}]` makes the proxy send the citizen's prompt **and the deployment's upstream API key** to an arbitrary host. The injected `api_base` then **persists**: later requests from *other* keys were partly routed to it (11 of 20). Root-level `api_base` is rejected; the nested one inside `fallbacks` is not. **On v1.98.0 the nested `api_base` is rejected too (401) and nothing persists**, so the Utility's production is not exposed. Anyone still on v1.92.0 is. Before any public write-up, check whether an advisory already exists for the fix.
5. **The right hook.** `CustomLogger.async_filter_deployments` runs before **every** attempt: first try, each retry, each fallback group. It sees the proxy's key metadata. Deployments it drops receive **zero** requests. If it leaves nothing, the router raises `RouterRateLimitError: No deployments available`, which becomes an error response we can queue on.
6. **Final safety check.** `async_pre_call_deployment_hook` runs once per attempt, right before the send, with the final `api_base`. That is where we check the endpoint URL against the approved list, which catches injected `api_base`s.
7. **Callbacks.** In the Router SDK, per attempt: `async_filter_deployments` → `async_pre_call_check` → `async_pre_call_deployment_hook` → `log_pre_api_call` (sync only; the async version is never called) → send → `async_log_success_event` / `async_log_failure_event`. Custom `model_info` keys (`jurisdiction`, `country`, `provider`) arrive in callback kwargs unchanged.
8. **Three kinds of failure are distinguishable:**
   - Connection refused: the mock received 0 requests (`APIConnectionError`).
   - HTTP 5xx: the provider received the request and answered with an error.
   - Timeout: `litellm.Timeout` (408) after `log_pre_api_call`, and the mock counted the receipt. This is "data received, no response".
9. **Response headers** (the final deployment only): `x-litellm-model-id`, `x-litellm-model-api-base`, `x-litellm-model-group`, `x-litellm-attempted-retries`, `x-litellm-attempted-fallbacks`, `x-litellm-call-id`, `x-litellm-version`, cost/duration headers, and `llm_provider-*` pass-through. The per-attempt history is **not** in the headers, so the timeline has to come from our callback.
10. **Binding the policy to the key works without a DB.** `general_settings.custom_auth` (the same mechanism as the Utility's `custom_auth.py`) can return a `UserAPIKeyAuth` carrying metadata and team metadata. Every router hook sees it as `metadata.user_api_key_metadata` / `user_api_key_team_metadata`.

11. **Found while building (v1.98.0 proxy).**
    - `async_log_failure_event` fires only **once per proxy request**, not once per retry, because all attempts share one `litellm_call_id`. Per-attempt outcomes must be rebuilt from `metadata["previous_models"]`, the router's retry log (`gateway/policy.py`).
    - v1.98.0 still has no deployment `order`, so a deterministic "primary, then second approved" order has to come from the filter hook.
    - The Utility's ConfigMap template renders only the two cost keys of `model_info` and drops everything else, including `id`. Jurisdiction metadata needs the template change in `upstream/`.
    - The rendered costs such as `1e-07` are read as strings by PyYAML, 15 values in prod. This is pre-existing.
    - Tag pollution still leaks traffic to the wrong deployment on v1.98.0 (R1a/R1b). Per-group `model_info.enable_tag_filtering` is honored on v1.98.0 (R4 fixed).

## 1. Version and config assembly
- `charts/platform/charts/litellm/values.yaml` sets image `ghcr.io/forpublicai/litellm-database`, tag `v1.92.0`, but `argo/environments/prod/platform-values.yaml` and `.../staging/...` set `tag: v1.98.0`, and that is what Argo deploys (confirmed by rendering with helm: `upstream/test/render.sh`). `Chart.yaml` has `appVersion: "main-stable"`, which is only a label.
- `git diff b3086ccd 2bef541d` on the fork touches only `.github/workflows/sync_and_build.yml` and `proxy/spend_tracking/spend_management_endpoints.py` plus its test.
- `templates/configmap.yaml` works like this:
  - It globs `models/**/*.yaml` and filters by `environments`.
  - Each file's `fallbacks:` list becomes `router_settings.fallbacks`.
  - It enables `custom_auth: custom_auth.user_api_key_auth` and the Lago callback.
  - It sets `drop_params: true` and `ssl_verify: false`.
- LiteLLM itself keeps custom keys inside `model_info` and hands them to callbacks (experiment: `utility/exp_utility_proxy.py`, results in `utility/proxy/run-*/results.txt`). **The Utility's template does not**: it renders only the two cost keys and drops the rest. `upstream/` has the template change; it passes the other keys through and leaves the cost lines untouched, so their YAML types do not change (a first draft that used `toYaml` changed them).

## 2. The Utility's routing surface (prod)
The full table and graph are in `utility/rendered/fallback-graph-prod.txt` (staging has its own file).

| group | hosts (country as assessed) |
|---|---|
| swiss-ai/apertus-v1.5-70b, -70b-thinking | api.infomaniak.com (CH), api.featherless.ai (unknown) |
| swiss-ai/apertus-70b-instruct | api.infomaniak.com (CH) |
| swiss-ai/apertus-v1.5-8b, -8b-thinking, apertus-8b-instruct | api.featherless.ai (unknown) |
| aisingapore/*SEA-LION* | api.sea-lion.ai (SG) |
| speakleash/Bielik-11B | llmlab.plgrid.pl (PL) |
| BSC-LT/ALIA-40b | api.nextbit256.com (unknown) |
| Cohere embed/rerank | AWS Bedrock eu-central-1 |

- 24 direct fallback edges exist in prod.
- Every Apertus group falls back to SEA-LION (SG) and Bielik (PL), which are other model families in other countries.
- CSCS and Phoeniqs deployments of Apertus v1.5 70B exist in the YAML but are commented out.

## 3. Tag-based routing
Enabled with `router_settings.enable_tag_filtering`. Tags come from several places and are merged: request `tags`, `metadata.tags`, `litellm_metadata.tags`, header `x-litellm-tags`, key metadata and team metadata.

| test | result |
|---|---|
| key tags `[ch]`, client adds `us` via body, header or `metadata.tags` | 401 "Not allowed ... tags" (match-all mode) |
| client sends `litellm_metadata.tags=["us"]` | **routed to the `us` deployment, 10 of 10** |
| router fallback A→B where B has no `ch` deployment | blocked (401), good |
| **tag pollution**, SDK (`tags/repro_min_sdk.py` R1) | request tagged `[ch]`, A=(ch,shared) is down. Tags become `[ch, shared, us]` and **the US mock is called**. Cause: `Router._update_kwargs_with_deployment` merges the tried deployment's tags into the shared request metadata (router.py L2948-2955) |
| proxy, A=[a-ch, a-ch2] down → B=[b-us(us,shared)], key tags `[ch]` | **b-us served the request** |
| `model=<deployment id>` | tags bypassed (`a-us` served, 3 of 3) |
| sync `Router.completion`, `usage-based-routing` v1, per-group `model_info.enable_tag_filtering` | no tag filtering (7/13, 10/10, 10/10 split) |
| `reject_clientside_metadata_tags: true` | blocks `metadata.tags` and the header, but **not** root `tags` or `litellm_metadata.tags` |

**Does tag filtering hold across fallbacks?** Partly. It blocks when the fallback group has no matching tag. It fails once tag pollution or a client-side vector widens the tags. We should report upstream: the pollution bug, the `litellm_metadata.tags` bypass, the deployment-id bypass, and the sync-path gap.

## 4. The hook that runs before every send
Instrumented sequence (`hooks/exp1_router_sequence.py`, `callbacks/exp_router.py`) for every attempt, retries and fallbacks included:

`async_filter_deployments(model, healthy_deployments, messages, request_kwargs)` → `async_pre_call_check(deployment)` → `async_pre_call_deployment_hook(kwargs)` → `log_pre_api_call` → **send**.

- **S3.** Policy drops `a1`, 10 requests: `a1` gets 0 and `a2` gets 10.
- **S4.** Allowed deployments down and the disallowed group dropped: disallowed mocks get 0, error `RouterRateLimitError`.
- **S5.** Everything dropped: all mocks get 0.
- **S7.** Allowed fallback group: `a2` is retried, then `b1` serves the request.
- Blocking inside `async_pre_call_check` also leaves the blocked mock at 0 (`callbacks/out/router_h_*.json`).
- Hooks are registered via `litellm_settings.callbacks: ["policy.instance"]`.

**Paths that bypass the hook or the tags, and how to close them:**
- Client `fallbacks` with `api_base`: data and key sent to any host, and the injected base persists. Close by rejecting `fallbacks`, `context_window_fallbacks` and `content_policy_fallbacks` in the request body (pre-call hook), and by checking `api_base` against the approved list in `async_pre_call_deployment_hook`.
- `model=<deployment id>`: reject it. The key's `models` allowlist only lists groups.
- `litellm_metadata`, root `tags`: our filter ignores request tags entirely. The policy is read only from `user_api_key_metadata`.
- Sync endpoints and pass-through, `/responses`, `/embeddings`: restrict the key's `allowed_routes` to `/v1/chat/completions` (tested in `proxy/exp4_routes_tags_hardening.py`).
- `/health` probes call providers with a test prompt. No citizen data is involved, but we disable background health checks in the demo.

## 5. Callbacks per attempt
- Every attempt gets `log_pre_api_call` plus a success or failure event. The deployment is identified by `kwargs["litellm_params"]["model_info"]` (id and custom keys) and `metadata.api_base` / `model_group` / `attempted_retries`. `litellm_call_id` is per attempt; `litellm_trace_id` groups the attempts of one request.
- Fallbacks also fire `log_failure_fallback_event` / `log_success_fallback_event`.
- **Cooldown:**
  - A deployment in cooldown is skipped silently, with no callback. Scenario f: `ch-1` is cooled and `ch-2` serves.
  - The filter hook still sees `healthy_deployments` minus the cooled ones, so the timeline can log "skipped: cooldown" by comparing with the full list.
  - With the Utility's defaults (`allowed_fails` 3) a single 503 does not trigger cooldown. Our demo gateway disables cooldowns instead (`disable_cooldowns: true`); the policy hook skips deployments that already failed within the same request, and a restored endpoint is used again on the next request.

## 6. Response headers
Listed in TL;DR 9 (`proxy/exp1_headers.py`, `out_exp1.txt`). After a fallback they describe the final deployment (e.g. `x-litellm-model-id: sg-1`, `attempted-fallbacks: 1`). `async_post_call_response_headers_hook` can add our own headers, e.g. `x-policy-id`.

## 7. Binding the policy to the key
`proxy/custom_auth_commune.py` maps a static key to `metadata={policy_id: "CH-only", allowed_jurisdictions: ["CH"]}`, a team and a `models` allowlist. It needs no DB. The data appears server-side in `user_api_key_metadata`, and every hook sees it (`proxy/out_exp2.txt`). The client cannot overwrite those keys, because the proxy writes them after parsing the body.

## 8. Public AI API (documented)
- Base URL `https://api.publicai.co/v1`, OpenAI-compatible (`/v1/models`, `/v1/chat/completions`, `/v1/completions`).
- Headers: `Authorization: Bearer <key>` and a **required `User-Agent`**.
- Apertus ids: `swiss-ai/apertus-v1.5-70b`, `swiss-ai/apertus-v1.5-70b-thinking`, `swiss-ai/apertus-v1.5-8b`, `swiss-ai/apertus-v1.5-8b-thinking` (262K context), plus the older `apertus-70b-instruct` / `apertus-8b-instruct`.
- The docs say the gateway "routes requests to open-source models hosted by inference partners worldwide" and handles "failover". No response header reveals the serving partner.
- `response_format` / JSON-schema support for Apertus is **not confirmed**. We validate the JSON ourselves and retry once.
- Issues #33 ("which endpoint is serving the inference?") and #35 ("proofs that ... running inference within chosen jurisdictional bounds") are exactly our problem.

## 9. What this does and does not prove
- We observe what **our gateway** sends and to which endpoint. We do not observe where the provider processes the data.
- The real endpoint (`api.publicai.co`) routes internally, so choosing it does not guarantee CH processing. The UI and README must say so.
- The gateway and its logs sit in the data path too.

## 10. To report upstream
- **LiteLLM, api_base injection:** reproduced on v1.92.0, not reproducible on v1.98.0. Check for an existing advisory before writing about it publicly; if none exists, report privately. Repros stay out of git (`.gitignore`): `tags/proxy_fallback_injection.py`, `tags/proxy_fallback_api_base_persistence.py`, `hooks/exp2_router_bypasses.py` (B13).
- **LiteLLM, public:** the tag-pollution bug (router.py L2948, still present in v1.98.0), the `litellm_metadata.tags` bypass, the deployment-id bypass, no tag filtering on the sync path / usage-based v1 (still in v1.98.0), and the failure callback firing once per proxy request instead of once per attempt.
- **chat.publicai.co:** see `upstream/` (tested on their rendered prod config, 10/10). It adds `model_info` pass-through, jurisdiction metadata on the Apertus deployments, an opt-in per-key/team policy hook and attribution headers (#33, #35). It also notes the stale chart image tag and the cost values read as strings.

## 11. Waiting inside the gateway (deferred requests)

Added after Phase 0: `gateway/deferred.py` moves the queue out of the app and into the gateway, so no application has to implement waiting itself.

- **How it plugs in.** A LiteLLM callback module (`litellm_settings.callbacks`) is executed inside the proxy's startup. On import it adds routes to the proxy's FastAPI app (`/v1/deferred/...`) and starts a background worker on the running event loop. Tested on v1.98.0.
- **Every attempt still goes through the policy.** The worker calls `llm_router.acompletion` with the server-side key and team metadata captured at submit time. The filter and the last-check hooks therefore run on every attempt. The proxy-level request check (layer 1) runs at submit. The routes use LiteLLM's normal key authentication. A job is visible only to the key that submitted it (404 for anyone else, 401 without a key).
- **`allowed_routes` matches exact paths only.** Its matcher accepts exact strings or LiteLLM route-group names, so the deferred routes are fixed paths with the id in the query or body. A key with `allowed_routes` gets 403 on anything else (verified: `/v1/models`, `/v1/model/info`, `/key/info`).
- **LiteLLM re-executes callback modules.** `get_instance_fn` has no cache and executes the module every time it resolves it. In our setup the module ran once, but worker state is kept in one process-wide object anyway.
- **Timeline injection (found and fixed).** A client could file events under someone else's job id by putting it in the metadata of a request that is then rejected. LiteLLM's failure callback still sees that metadata. Job ids attached by the worker are now HMAC-signed with a per-process secret, and events are filed only under a verified id. `tests/test_deferred.py` covers it.
- **Data minimisation.** The request body is deleted as soon as a job ends (done, failed, cancelled, expired). The result and the timeline stay for the caller to fetch.
- **Names are not network destinations (found in our own demo, fixed).** LiteLLM caches DNS answers for 300 s (`AIOHTTP_TTL_DNS_CACHE`). We recreated the endpoint containers without restarting the gateway, and Docker gave them new IPs. For a few minutes the gateway's cached address for `ep-publicai` then belonged to `ep-us-1`. One demo letter reached the US mock, while every gateway event (and the policy's own checks) said "Public AI": the policy verifies endpoint *names* and `api_base` strings, not where packets go. The endpoints' own counters caught it. This also explains an earlier flaky test.
  - The fix for the demo: `AIOHTTP_TTL_DNS_CACHE=0` on the gateway. `tests/restart_check.sh` now recreates the endpoint containers and asserts that requests reach exactly the named endpoint.
  - The general lesson: name-level policy needs a binding between name and server. With real providers that binding is TLS certificate verification. The Utility's config sets `ssl_verify: false` globally, which removes it. Network egress controls (only the approved provider IPs are reachable) are the second barrier.
- **Restart.** `tests/restart_check.sh` restarts the gateway while a job waits. The job is still there after the restart and completes as soon as an approved endpoint returns, without any client action.

## 12. Open questions to verify

Grouped by what they would change. Nothing here is claimed as working in the README.

**Deferred requests (gateway queue)**
- [ ] **Official extension point.** Adding routes to the proxy app from a callback is not an official LiteLLM API. It can break on upgrade; the bench catches that. Check whether v1.98's new `RoutingPlugin` pipeline (`resolve_routing_plugins` in `proxy_server.py`) or another official mechanism could host the policy or the queue.
- [ ] **Spend and billing.** The worker calls the router directly, so the proxy's spend tracking (and Lago billing in the Utility) is skipped. Verify, then decide: replay through the proxy's own endpoint, or log spend explicitly.
- [ ] **Several replicas.** The Utility autoscales. One SQLite file per replica does not work there: this needs a shared store (for example their Postgres) and row locking (`SELECT ... FOR UPDATE SKIP LOCKED`) so two replicas never run the same job.
- [ ] **Data at rest in the gateway.** While a request waits, the letter sits in the gateway's volume. Open points: encryption at rest, the retention of results and timelines, and who operates the gateway. For a commune-run gateway this is the commune's authorized environment. For the Utility it would be Public AI's infrastructure, which is a different promise and must be declared.
- [ ] **Policy snapshot vs current policy.** The worker uses the policy captured at submit time. Should a key that is revoked, or whose policy changes, stop its waiting jobs?
- [ ] **Virtual keys.** Route permissions for LiteLLM DB-backed virtual keys calling the custom routes (the Utility's setup) are not tested. Our keys come from `custom_auth` with explicit `allowed_routes`.
- [ ] **Concurrency.** `Router.previous_models`, which we use to rebuild per-attempt outcomes, is router-global and capped at 4 entries. Under concurrent load some attempt details may be missing; the timeline then says "details not available". Test under load.
- [ ] **Not implemented.** Streaming for deferred requests, a completion webhook (callers poll today), and priorities between jobs.

**Routing and policy**
- [ ] **Binding names to servers.** Test that TLS verification is on for every real provider (the Utility sets `ssl_verify: false`), and design the egress allowlist that should back the policy at network level.
- [ ] **`RoutingPlugin`.** Evaluate v1.98's official routing-plugin API as the home of the policy filter (layer 2).
- [ ] **Streaming.** Hook behavior with streaming, `/v1/responses` and embeddings. Our keys are restricted to chat completions.
- [ ] **Independent re-runs** of the Phase 0 experiments by a second person.

**Public AI**
- [ ] JSON mode (`response_format`) on Apertus through the Public AI API.
- [ ] Real Apertus answers with a real `PUBLICAI_API_KEY`: quality of the explanation and of the German draft for the three sample letters.
- [ ] Whether an advisory already exists for the `api_base`-in-fallbacks issue fixed between v1.92.0 and v1.98.0. The injection is **not** tested against production and will not be.
