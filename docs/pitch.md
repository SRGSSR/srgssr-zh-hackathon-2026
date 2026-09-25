# Pitch preparation

Working document for the team. The examples in the app are two letters from the social services (Ana), the school's class camp letter (the Keller family) and a second payment reminder (Marco).

## Formats and timing (check against the hacker guide)

| Slot | When | Format |
|---|---|---|
| Expert jury submission | Fri 12:00 | link to repo and demo |
| Expert pitch | Fri 14:00 to 16:00 | **1 min pitch + 3 min Q&A** |
| Shortlist | Fri 17:00 | |
| Main jury submission | Fri 17:30 | |
| Main stage | Fri 18:00 to 18:45 | **2 min pitch + 1 min Q&A** |

## The one sentence

> When the approved provider fails, a public AI service must still keep its promise about citizens' data. Ours does, on every retry and every fallback, and you can check it.

## Closing line (chosen)

> "With Apertus and our sovereignty layer, a commune can check, request by request, where citizen data goes."

## Three people, three rules (the frame of the demo)

| Person | Office | Rule | What the jury sees |
|---|---|---|---|
| Ana, a letter from the **social services** (the strict compliance case) | Social services | Switzerland only | Every Swiss service broken: the letter waits. No way out, not even with consent. |
| The Keller family, a letter from the **school** (privacy-conscious) | School | Switzerland first, then the EU | Swiss services broken: the EU host answers. The US and Singapore stay at 0. |
| Marco, a **payment reminder** (pragmatic) | Other offices | CH and EU; the US only with his consent | Swiss and EU broken: a clear dialog. He agrees, the US counter goes to 1, and the agreement is in the journey. |

Say it plainly: the rule belongs to the office and is bound to its key. The request never decides, and consent is possible only where the office allows it.

## Three messages (everything else supports these)

1. **The problem is real, and it is in the production config.** The Utility's own config falls back from Apertus to other model families in other countries (SEA-LION, Bielik) when a provider fails. We ran that config in the image production runs: with the Swiss host down, a normal request was answered by the Singapore mock.
2. **We keep the promise where it can be kept: in the gateway.** Each office sets its own rule, bound to its API key, and the gateway checks it before every attempt, including retries and cross-model fallbacks:
   - social services: Switzerland only;
   - school: Switzerland, then the EU;
   - other offices: the US too, but only if the resident agrees, for that one letter.

   If no allowed service is up, the request waits in the gateway, in Switzerland, and completes later. No application has to implement that itself.
3. **We can prove what we claim, and we say what we cannot.** Each endpoint counts what it receives, and the tests assert zero requests to the endpoints each rule excludes. We show which endpoints our gateway contacted; we do not claim to prove where a provider physically computes.

## 1-minute pitch (expert jury), about 150 words

> Ana gets a letter from her commune's social services, in bureaucratic German: documents due by 15 October, her medical certificate, a warning that her support may be cut.
>
> Our service explains it in her language with Apertus, lists what to do by when, and drafts her German reply.
>
> This is among the most protected data there is. Yet when a provider fails, the Utility's fallbacks today can send such a request to another model, in another country.
>
> So each office sets its own rule, and our gateway enforces it on every retry and every fallback. Social services: Switzerland only. If no Swiss service is up, Ana's letter waits in Switzerland. The school also allows the EU. Other offices can offer the US, but only if the resident agrees, for that one letter.
>
> With Apertus and our sovereignty layer, a commune can check, request by request, where citizen data goes.

## 2-minute pitch (main stage)

Structure: story (15 s), the problem (20 s), live demo (60 s), proof and upstream (20 s), close (5 s). Total: 120 s.

1. **Story (15 s).** Ana's letter, in two sentences (see the 1-minute pitch).
2. **The problem (20 s).** "Public AI routes through LiteLLM with automatic fallbacks. In the Utility's own configuration, Apertus falls back to other model families hosted in other countries. For a commune, that breaks the promise at exactly the moment something goes wrong."
3. **Live demo (60 s).** The four prepared tabs below.
4. **Proof and upstream (20 s).** "48 automated checks, including zero requests to the endpoints each rule excludes. The same policy passes 10 out of 10 checks on the Utility's own production config. It's a PR-ready proposal for chat.publicai.co, and it's all Apache 2.0."
5. **Close (5 s).** "With Apertus and our sovereignty layer, a commune can check, request by request, where citizen data goes."

### Prepare the demo before going on stage

Each switch to "waiting" takes about 20 s, and a real Apertus answer takes 10 to 60 s. So prepare four tabs in advance:

1. **Tab 1:** Ana's letter, already explained ("Documents needed for your support", Italiano).
2. **Break every Swiss service.** **Tab 2:** the same letter, "Explain it again". Wait until it says "waiting".
3. **Tab 3:** the example "Class camp". The EU host answers.
4. **Break Swiss and EU services.** **Tab 4:** the example "Second payment reminder". Wait until the consent offer appears.

### On stage

1. **Tab 1:** the answer, and the services struck through before anything was sent.
2. **Tab 2:** the letter waiting, with Singapore blocked.
3. **Tab 3:** the answer from the EU host.
4. **Tab 4:** Marco agrees. With the demo controls open, the US counter goes to 1.
5. Set Swiss host 1 to **Working**, then **Try again now** in Tab 2. Ana's letter completes. The answer is simulated and labelled as such; with Public AI it would be real, but slow.

## Live demo, step by step (for the expert jury or a longer slot)

Before: `docker compose up -d`, open `http://localhost:8080`, press **Repair all and reset counters**, set the browser zoom to 125 %, and **run `caffeinate -d` so the laptop does not sleep** (it did during the build).

| Step | Click | What the jury should see | Say |
|---|---|---|---|
| 1 | Ana: example "Documents needed for your support", Italiano, "Explain my letter" | Explanation in Italian with the deadlines highlighted. The journey shows the rule applied, **the US host, the EU host and the unknown-origin host struck through**, and the answer from Public AI | "Ana's letter is about her support and her health. Switzerland only, checked before anything is sent. For Ana, not even the EU." |
| 2 | Demo controls: **Break every Swiss service**, "Explain it again" | "Your letter is waiting, safely." Journey: **the backup plan wanted SEA-LION in Singapore, nothing was sent** | "This is where the Utility would have gone to Singapore. For Ana, nothing leaves Switzerland, not even with consent." |
| 3 | New letter: example "Class camp" (school), explain | The **EU host** answers; US and Singapore stay 0 | "The school chose Switzerland first, then the EU." |
| 4 | **Break Swiss and EU services**; new letter: "Second payment reminder" (other office), explain | Waiting, then the offer: "Send it to the United States instead…". Open the dialog, tick "I understand", **Send it to the United States** | "Marco can choose not to wait. The dialog says exactly what that means." |
| 5 | Watch the journey and the counters | "You agreed to send this letter to a service in the United States", sent to the US host, **US counter 1** | "His choice, for this letter only, recorded. Ana's letter still waits in Switzerland." |
| 6 | **Repair all** | Ana's waiting letter completes by itself | "When the Swiss service is back, the promise is kept." |

**Fill the silence.** Each switch to "waiting" takes about 20 s. The speaker keeps talking meanwhile, for example: "Right now the gateway is trying every Swiss service, one after the other. Watch the journey: every attempt appears, and nothing goes anywhere else."

Fallback if the live demo fails: a pre-recorded 60-second video of the same steps (record it at 10:00).

The real Public AI API can be slow under load (once a 504 after 60 s during testing). Run one real request a few minutes before the pitch. If it is slow on stage, say so: "the real service is slow right now, so the gateway will move on to a Swiss host, and you can watch it do that."

Roles: **speaker** (tells the story, never touches the laptop), **driver** (clicks), **backup** (video ready, watches the time).

## Proof points (numbers we can stand behind)

- **Enforcement:** 0 requests reached an endpoint that a rule excludes, in any test. The ground truth is each endpoint's own counter.
- **Our bench:** 48 pytest checks (11 of them on the rules and consent), plus the gateway restart check and the recreated-containers check.
- **Upstream:** 10/10 checks on the Utility's own rendered prod config, in the prod image (v1.98.0).
- **Found along the way:**
  - The Utility's chart pins v1.92.0, but prod runs v1.98.0.
  - Its template drops every `model_info` field except costs, so jurisdiction metadata never reaches LiteLLM today.
  - Its config sets `ssl_verify: false`, so nothing binds a provider name to the real server.
  - The DNS case: during the build, one letter reached the wrong container while every log named the right one. Only the endpoints' counters caught it.
  - 15 cost values are read as strings.
  - LiteLLM's tag routing widens tags on retries.
  - The failure callback fires once per request, not once per attempt.

## Q&A preparation

| Likely question | Short, honest answer |
|---|---|
| "Can you prove the data stayed in Switzerland?" | "No, and nobody can from outside. We prove which endpoints our gateway sent it to, with counters and tests. Proving physical location needs provider-side evidence, like contracts, audits or attestation. We say so in the README." |
| "The Public AI API routes internally. Isn't that the same problem?" | "Yes, one level down. That's why the proposal is for the Utility itself: jurisdiction metadata and the same policy inside their gateway. Our patch is tested on their production config." |
| "Why not LiteLLM's tag routing?" | "We tested it on their version. Retries and fallbacks widen the tags, and some request fields bypass them. A filter that runs before every attempt, reading only server-side key metadata, doesn't have those gaps." |
| "Isn't waiting bad for users?" | "For a letter with a deadline in days, ten minutes of waiting is fine; a leak can't be recalled. For urgent use cases, the commune can approve more Swiss endpoints. And where the office allows it, the resident can choose not to wait, with explicit consent: that's Marco's case. The rule decides, not the outage." |
| "Isn't consent a loophole?" | "Only where the office allows it: the social services' rule refuses it, and the test bench proves that. Consent never comes from a request parameter. It is given in a dialog, recorded, valid for one letter, and Swiss and EU services are still tried first. Whether consent is enough legally for a given office is a question for that office's lawyers, not for the gateway." |
| "What if DNS sends the request somewhere else?" | "It happened to us during the build: a stale DNS cache sent one demo letter to the wrong container while the gateway thought it went to the right one. Our counters caught it, we fixed it, and the bench now tests it. That's why the proposal to the Utility also says: turn TLS verification back on. It is off in their config." |
| "What if the gateway itself is compromised?" | "Out of scope, and said so: the gateway and its logs are in the data path. It runs in the commune's environment; network egress controls are the second barrier." |
| "Where does the waiting request live?" | "In the gateway's local store, a volume in the same authorized environment. The request body is deleted as soon as the job ends." |
| "Is the legal part right?" | "We use hedged wording and are not lawyers. The legal basis differs by canton; we name what we checked." (Only say what the team has verified.) |
| "Does it scale?" | "One replica today. For the Utility's autoscaling it needs a shared store and row locking: it's on our open-questions list." |
| "Why Apertus?" | "Open weights, trained with Swiss data governance, and truly multilingual: our service explains letters in simple words in German, French, Italian, Romansh, Swiss German and English, and Apertus writes all of them." (Show a Romansh or Swiss German answer if there is time; a native speaker should still check the wording.) |
| "Does this only work with Apertus?" | "No, the layer is model-agnostic. Apertus makes the whole chain open: open model, public API, open gateway." |
| "What would you do next?" | "Upstream the metadata and the policy, add evidence for each provider, turn TLS verification on, and move the queue to a shared store so it works with autoscaling." |
| "Is the answer correct / legal advice?" | "It's an explanation, not legal advice. The UI says so, and the resident checks the draft." |

## Don'ts

- Don't claim physical-location proof, certification or legal compliance.
- Don't show exploit details of the LiteLLM v1.92.0 issue. Say only "fixed in the version production runs".
- Only fictional data on screen (Gemeinde Musterstadt, AHV 756.0000.0000.00).
- Don't read the slides; the demo is the slide.

## Checklist, 30 minutes before

- [ ] `docker compose up -d`; `make test` green (or at least the last full run green)
- [ ] Press **Repair all and reset counters** once, **before** preparing the tabs. It also sets every service back to Working (`/control/reset` sets `mode=up`). Pressed in the middle of the demo, it would unblock the waiting letters.
- [ ] The four tabs prepared (see "Prepare the demo before going on stage")
- [ ] `PUBLICAI_API_KEY` set, or the SIMULATED label is visible and we say so
- [ ] `caffeinate -d` running, charger plugged in, notifications off
- [ ] Backup video on the desktop
- [ ] Timer: 60 s and 120 s versions rehearsed at least twice
