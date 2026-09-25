# Proposal for chat.publicai.co: jurisdiction metadata and a per-key routing policy

A PR-ready change for [forpublicai/chat.publicai.co](https://github.com/forpublicai/chat.publicai.co), against commit `6abd68dd` (see `patches/BASE_COMMIT`). It addresses [#33](https://github.com/forpublicai/chat.publicai.co/issues/33) ("which endpoint is serving the inference?") and part of [#35](https://github.com/forpublicai/chat.publicai.co/issues/35) (jurisdictional bounds).

## The problem, in the Utility's own config

`swiss-ai/apertus-v1.5-70b` is served by Infomaniak (CH) and Featherless (country not stated). Its fallbacks are `aisingapore/Qwen-SEA-LION-v4-32B-IT` (api.sea-lion.ai) and `speakleash/Bielik-11B-v3.0-Instruct` (llmlab.plgrid.pl). Every Apertus group can therefore end up on a different model family, in a different country, when a provider fails.

We ran that config offline, in the image prod runs (`litellm-database:v1.98.0`), with the Infomaniak host down. A normal request was answered by the SEA-LION mock (`regular key, CH host down` in the test output below).

An institution that has to keep data in Switzerland cannot rely on this today. The routing metadata it would need is also not in the config at all: the ConfigMap template only renders `input_cost_per_token` and `output_cost_per_token` from `model_info`, and silently drops every other key, including `id`.

## What the patch changes

`patches/0001-jurisdiction-metadata-and-policy-hook.patch` touches 9 files and adds 2.

1. **`templates/configmap.yaml`**
   - Passes every other `model_info` key through unchanged (`id`, `provider`, `country`, `jurisdiction`, `jurisdiction_basis`). The two cost lines stay exactly as they are; the test proves the rendered `litellm_params` and costs are identical to today's.
   - Registers the policy callback when enabled.
2. **`models/swiss-ai/*.yaml`**: jurisdiction metadata on every Apertus deployment.
   - Infomaniak: `CH`, with a `TODO(Public AI)` for the contract or DPA that states Swiss processing. We do not have that evidence, so the patch does not claim it.
   - Featherless: `unknown`.
   - Other model files are untouched. Without metadata they are excluded for keys under a policy (fail closed) and unchanged for everyone else.
3. **`jurisdiction_policy.py`**: a LiteLLM `CustomLogger`. It is the same module as `gateway/policy.py` in this repository, running with `POLICY_REQUIRED=0`.
   - **Opt-in per key or team.** It applies only when the key's or team's metadata contains a policy, for example `{"routing_policy": {"id": "CH-only", "allowed_jurisdictions": ["CH"]}}`. The team's policy wins, so a key cannot relax its institution's rule. Keys without a policy keep today's behavior.
   - **Before every attempt** (`async_filter_deployments`, which runs for the first try, retries and fallbacks), it keeps only deployments whose metadata is complete and whose jurisdiction is allowed.
   - **Right before each send** (`async_pre_call_deployment_hook`), it re-checks the deployment and the `api_base` actually used.
   - **Once per request** (`async_pre_call_hook`), for keys under a policy, it rejects request fields that steer routing: client `fallbacks`, `tags`, `litellm_metadata`, `api_base`, a deployment id used as `model`, and so on.
   - **Attribution headers** name the deployment that really answered: `x-served-by-deployment`, `x-served-by-provider`, `x-served-by-jurisdiction`, `x-routing-policy`. This replaces the random sponsor attribution for #33.
4. **`templates/jurisdiction-policy-configmap.yaml`, `deployment.yaml`, `values.yaml`**: mount the module the same way `custom_lago_callback.py` is mounted. Behind `jurisdictionPolicy.enabled`, which is **off by default**.

## Why not LiteLLM tag routing?

We tested it. The details are in `docs/findings.md` in this repository.

On both v1.92.0 and v1.98.0, the router merges the tags of each deployment it tries into the request's tags (`Router._update_kwargs_with_deployment`). A retry or fallback therefore runs with a wider tag set and can reach a deployment the original tags excluded (`tags/repro_min_sdk.py`, R1). The sync `completion()` path and `usage-based-routing` v1 do not filter by tags at all.

A filter that runs on every attempt and reads only server-side key or team metadata avoids all of this.

## How it was tested

```bash
upstream/test/render.sh /path/to/chat.publicai.co prod   # applies the patch, renders the prod config with helm
upstream/test/run.sh                                     # runs that config in litellm-database:v1.98.0 with mock providers
```

`run.sh` loads the Utility's own rendered config. It replaces each provider host with a local mock that counts the requests it receives, and removes only what cannot run offline (DB, Redis, cache, Lago, Slack, Prometheus). It uses a test auth stub with three keys: a CH-only key, a normal key, and a team member whose key tries to relax the team's policy.

Output:

```
PASS patch leaves litellm_params and cost fields exactly as before
INFO pre-existing, not caused by this patch: 15 cost values like 1e-07 are loaded as strings by PyYAML (YAML 1.1)
PASS rendered config carries jurisdiction metadata for Apertus 70B
PASS policy callback registered
PASS regular key: unchanged behaviour, both Apertus hosts in rotation
PASS CH-only key: 20/20 served by the CH deployment only
PASS CH-only key: attribution headers name the serving deployment
PASS CH-only key, CH host down: fails closed, no fallback host receives data
PASS regular key, CH host down: still served (today's fallbacks unchanged)
PASS team policy wins over a key trying to relax it: no non-CH host receives data
PASS CH-only key: client-side fallbacks rejected
10/10 checks passed
```

The civic prototype in this repository runs the same module in fail-closed mode and has a 24-test bench (`make test`).

## Next step, not in this patch: waiting in the gateway

In our prototype the same gateway also keeps requests that cannot be served within the rule right now, and completes them later (`gateway/deferred.py`: `/v1/deferred/chat/completions`, a worker, a local store). This means no application has to implement waiting.

It is deliberately **not** part of this patch, because for the Utility it raises questions we have not answered yet:
- it relies on adding routes to LiteLLM's FastAPI app from a callback (not an official API);
- the worker's calls skip spend tracking and Lago;
- autoscaled replicas need a shared store with row locking;
- waiting requests would be stored at Public AI, which is a promise to declare.

See `docs/findings.md`, section 12.

## Rollout suggestion

1. Merge with `jurisdictionPolicy.enabled: false`. The only visible change is that `model_info` keys now reach LiteLLM.
2. Enable it in staging. Create a team with a `routing_policy` in its metadata and keep all other keys as they are.
3. Replace the `TODO` in `jurisdiction_basis` with real evidence for each provider before any institution relies on it.

## Limits (please read)

- The metadata is **declarative**. The policy guarantees which endpoints the gateway sends data to, not where a provider physically processes it. That needs provider-side evidence (contracts, audits, attestation) and is out of scope.
- The gateway and its logs are part of the data path.
- For a key under a policy, a request fails when no allowed deployment is up. That is intended (fail closed). The caller decides whether to wait. Our prototype keeps the job and retries.
- Not tested: streaming responses, `/v1/responses`, embeddings and rerank. For keys under a policy, restrict `allowed_routes` to chat completions.
- LiteLLM's failure callback fires only once per proxy request, not once per retry, so per-attempt outcomes are rebuilt from the router's retry log. That is fine for a timeline, but not an audit record.

## Also noticed while testing (unrelated to the patch)

- **TLS verification is off.** The config sets `ssl_verify: false`. A jurisdiction policy decides on provider *names*, and only certificate verification ties a name to the real provider's server. We saw what happens without that binding in our own demo: a stale DNS cache sent a request to a different container than the one named. We suggest turning verification on (and pinning a CA bundle where needed, e.g. for CSCS) before relying on any routing policy.

- **Stale image tag in the chart.** `values.yaml` pins `litellm-database:v1.92.0`, while `argo/environments/{prod,staging}` deploy `v1.98.0`.
- **Cost values read as strings.** The rendered costs such as `1e-07` (no decimal point) are read as **strings** by PyYAML, 15 values in prod. It is worth checking that cost tracking and Lago billing still work for those models. Writing them as `1.0e-07` would make them floats.
