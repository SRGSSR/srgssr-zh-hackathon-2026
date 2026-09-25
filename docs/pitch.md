# Pitch preparation

Working document for the team. The opening story assumes we pick the social assistance letter as hero case (see [plan-example-app.md](plan-example-app.md)). If we keep the tax letter, swap the story; everything else stays.

## Formats and timing (check against the hacker guide)

| Slot | When | Format |
|---|---|---|
| Expert jury submission | Fri 12:00 | link to repo and demo |
| Expert pitch | Fri 14:00 to 16:00 | **1 min pitch + 3 min Q&A** |
| Shortlist | Fri 17:00 | |
| Main jury submission | Fri 17:30 | |
| Main stage | Fri 18:00 to 18:45 | **2 min pitch + 1 min Q&A** |

## The one sentence

> When the approved provider fails, a public AI service must still keep its promise about citizens' data. Ours does, on every retry and every fallback, and it proves it.

## Three messages (everything else supports these)

1. **The problem is real and it is in production config.** The Utility's own config falls back from Apertus to other model families in other countries (SEA-LION, Bielik) when a provider fails. We ran that config in the image production runs: with the Swiss host down, a normal request was answered by the Singapore mock.
2. **We keep the promise where it can be kept: in the gateway.** The commune's rule is bound to its API key and checked before every attempt, including retries and cross-model fallbacks. If no approved endpoint is up, the request waits in the gateway, in Switzerland, and completes later. No application has to implement that itself.
3. **We can prove what we claim, and we say what we cannot.** Each endpoint counts what it receives, and the tests assert zero requests to disallowed endpoints. We show which endpoints our gateway contacted; we do not claim to prove where a provider physically computes.

## 1-minute pitch (expert jury), about 140 words

> Ana gets a letter from the social services of her commune. It is in bureaucratic German. It asks for documents by the 15th, mentions her medical certificate, and warns that her support may be cut. She understands little of it.
>
> Our service explains it in her language, lists what she must do and by when, and drafts her reply in German. It runs on Apertus through Public AI.
>
> But this is some of the most protected data there is. And when a provider fails, the Utility's fallbacks today can move such a request to another model in another country.
>
> So the commune's rule, "CH-only", is enforced in the gateway on every retry and every fallback. If no Swiss endpoint is available, Ana's letter waits in Switzerland and is completed later.
>
> Break a provider yourselves: the timeline shows every endpoint contacted, and the disallowed ones stay at zero.

## 2-minute pitch (main stage), about 280 words

Structure: story (20 s), the gap (25 s), live demo (60 s), proof and upstream (15 s).

1. **Story (20 s).** Ana's letter, as above, in two sentences.
2. **The gap (25 s).** "Public AI routes through LiteLLM with automatic fallbacks. In the Utility's own configuration, Apertus falls back to other model families hosted in other countries. For a commune, that breaks the promise at exactly the moment something goes wrong."
3. **Live demo (60 s).** Follow the demo script below: normal run, break the primary, break all approved, restore.
4. **Proof and upstream (15 s).** "37 automated checks, including zero requests to disallowed endpoints. The same policy passes 10 out of 10 checks on the Utility's own production config. It's a PR-ready proposal for chat.publicai.co, and it's all Apache 2.0."
5. **Close (5 s).** "When the provider fails, the promise holds."

## Demo script (driver's view)

Before: `docker compose up -d`, open `http://localhost:8080`, "Reset counters", browser zoom 125 %, and **run `caffeinate -d` so the laptop does not sleep** (it did during the build).

| Step | Click | What the jury should see | Say |
|---|---|---|---|
| 1 | Sample "Sozialhilfe", language Italian, "Explain" | Result, timeline: rule "CH-only", **US and no-metadata endpoints blocked before send**, answered by Public AI | "The rule is applied before anything is sent." |
| 2 | Panel: **Break** `publicai-apertus`, submit again | Switches to `mock-ch-1`. Counters: US / SG / no-metadata **0** | "A retry, still within the rule." |
| 3 | **Break all approved**, submit | Status *waiting*: "stays in the gateway, not sent anywhere else". Timeline: LiteLLM tried the SEA-LION fallback, **blocked before send** | "This is where the Utility would have gone to Singapore." |
| 4 | **Restore** `mock-ch-2` | The job resumes by itself and completes; the timeline shows the whole outage | "The promise held, and nobody had to click retry." |
| (5) | Optional: **Hang** `mock-ch-1` | "data received, no response" | "We even tell you when a provider got the data but never answered." |

Fallback if the live demo fails: a pre-recorded 60-second video of the same steps (record it at 10:00).

Roles: **speaker** (tells the story, never touches the laptop), **driver** (clicks), **backup** (video ready, watches the time).

## Proof points (numbers we can stand behind)

- **Enforcement:** 0 requests reached disallowed endpoints in any test. The ground truth is each endpoint's own counter.
- **Our bench:** pytest checks for the 8 brief scenarios, the deferred queue and the override attempts, plus a gateway restart check. **Update the count after the final run.**
- **Upstream:** 10/10 checks on the Utility's own rendered prod config, in the prod image (v1.98.0).
- **Found along the way:**
  - The Utility's chart pins v1.92.0, but prod runs v1.98.0.
  - Its template drops every `model_info` field except costs, so jurisdiction metadata never reaches LiteLLM today.
  - 15 cost values are read as strings.
  - LiteLLM's tag routing widens tags on retries.
  - The failure callback fires once per request, not once per attempt.

## Q&A preparation

| Likely question | Short, honest answer |
|---|---|
| "Can you prove the data stayed in Switzerland?" | "No, and nobody can from outside. We prove which endpoints our gateway sent it to, with counters and tests. Proving physical location needs provider-side evidence, like contracts, audits or attestation. We say so in the README." |
| "The Public AI API routes internally. Isn't that the same problem?" | "Yes, one level down. That's why the proposal is for the Utility itself: jurisdiction metadata and the same policy inside their gateway. Our patch is tested on their production config." |
| "Why not LiteLLM's tag routing?" | "We tested it on their version. Retries and fallbacks widen the tags, and some request fields bypass them. A filter that runs before every attempt, reading only server-side key metadata, doesn't have those gaps." |
| "Isn't waiting bad for users?" | "For a letter with a deadline in days, ten minutes of waiting is fine; a leak can't be recalled. For urgent use cases, the commune can approve more Swiss endpoints. The rule decides, not the outage." |
| "What if DNS sends the request somewhere else?" | "It happened to us during the build: a stale DNS cache sent one demo letter to the wrong container while the gateway thought it went to the right one. Our counters caught it, we fixed it, and the bench now tests it. That's why the proposal to the Utility also says: turn TLS verification back on. It is off in their config." |
| "What if the gateway itself is compromised?" | "Out of scope, and said so: the gateway and its logs are in the data path. It runs in the commune's environment; network egress controls are the second barrier." |
| "Where does the waiting request live?" | "In the gateway's local store, a volume in the same authorized environment. The request body is deleted as soon as the job ends." |
| "Is the legal part right?" | "We use hedged wording and are not lawyers. The legal basis differs by canton; we name what we checked." (Only say what the team has verified.) |
| "Does it scale?" | "One replica today. For the Utility's autoscaling it needs a shared store and row locking: it's on our open-questions list." |
| "Why Apertus?" | "Open weights, trained with Swiss data governance, multilingual: it covers the languages of the people who most need this." |
| "What would you do next?" | "Merge the metadata and the policy upstream, add provider evidence to each deployment, and support a second rule per data class." |
| "Is the answer correct / legal advice?" | "It's an explanation, not legal advice. The UI says so, and the resident checks the draft." |

## Don'ts

- Don't claim physical-location proof, certification or legal compliance.
- Don't show exploit details of the LiteLLM v1.92.0 issue. Say only "fixed in the version production runs".
- Only fictional data on screen (Gemeinde Musterstadt, AHV 756.0000.0000.00).
- Don't read the slides; the demo is the slide.

## Checklist, 30 minutes before

- [ ] `docker compose up -d`; `make test` green (or at least the last full run green)
- [ ] Counters reset, all endpoints restored
- [ ] `PUBLICAI_API_KEY` set, or the SIMULATED label is visible and we say so
- [ ] `caffeinate -d` running, charger plugged in, notifications off
- [ ] Backup video on the desktop
- [ ] Timer: 60 s and 120 s versions rehearsed at least twice
