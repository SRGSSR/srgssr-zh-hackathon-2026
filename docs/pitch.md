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

1. **The problem is real, and it is in the production config.** The Utility's own config falls back from Apertus to other model families in other countries (SEA-LION, Bielik) when a provider fails. We ran that config against test hosts: with both Apertus hosts down (the Swiss one and one with no stated country), a normal request was answered by the Singapore mock.
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

## 2-minute pitch (main stage), version 2

Slides: [`docs/slides/main-stage-v2.html`](slides/main-stage-v2.html) (arrow keys; the Q&A tabs follow the last slide).

### What the expert jury asked

The jury took the letter app for the product. They asked:

| Question | Answer (and where it is now) |
|---|---|
| "Did you build something?" | "Yes: a plugin for LiteLLM, about a thousand lines of Python, running at promisekept.ch, with 48 tests and a ready pull request for the Public AI Utility. The letter service is the example that uses it." Slide 4; Q&A tab "What's in the repo". |
| "Did you use Apertus?" | "Yes. Every real answer comes from Apertus 1.5 through the Public AI API. The simulated hosts exist so we can break things on purpose, and the page labels them." Said in the demo; Q&A tab "Apertus". |
| "Can it process images?" | "Apertus 1.5 can: it takes images, audio and text. Our prototype sends only text so far, and the photo upload is a mock. And the layer doesn't care: a photo of the letter holds the same data, so it gets the same rule." Q&A tab "Images". |

### What changed from version 1, and why

- **Ana opens and closes.** Slides 1 to 3 are version 1's, for empathy. The last slide comes back to her: she got her answer, and her data never left Switzerland.
- **The layer is named as what we built** (slide 4), right after her problem. The app appears only as the example, in the demo.
- **Few words on the slides.** The slides support the speaker; the speaker tells the story.
- **Apertus is named** in the demo, on a real answer.
- **One demo path, three moments:** Ana waits, Marco chooses, Ana's letter completes.
- **One number to remember:** zero, on the counters in the demo controls.
- **The problem sentence is exact:** Singapore when the Apertus *hosts* are down (both), not "the Swiss host".
- **The repair uses Swiss host 1,** which answers in seconds; Public AI would take up to a minute on stage.

### Script (rehearse against a timer)

| Time | Screen | Speaker says |
|---|---|---|
| 0:00 | Slide 1: This is Ana | "This is Ana." |
| 0:03 | Slide 2: her letter | "A letter from her social services: her bank statements, her medical certificate, her children, a deadline. In bureaucratic German. Ana speaks Italian." |
| 0:13 | Slide 3: her doubt | "An AI could explain it. But where does her letter go? Public AI's gateway falls back on its own: if the Apertus hosts are down, it goes to another model, in Singapore. It's in their configuration today. We ran it." |
| 0:30 | Slide 4: what we built | "So we built a sovereignty layer, in the gateway: a plugin for LiteLLM, the gateway Public AI runs. Ana's office sets the rule: Switzerland only. It's checked on every retry and every fallback. And if no Swiss service is up, her letter waits." |
| 0:47 | Tab 1 | "Here it is, with Apertus. Ana's letter, explained in Italian. Only Switzerland: three services ruled out before anything was sent." |
| 0:58 | Tab 2 | "Every Swiss service broken: the backup plan wants Singapore. Blocked. The letter waits." |
| 1:06 | Tab 3, demo controls open | "Marco's office allows the US, but only if he agrees. He agrees, for this letter only: the US counter goes to one." |
| 1:18 | Tab 2 | "A Swiss service is back: Ana's letter completes by itself." |
| 1:24 | Tab 2, demo controls open: the excluded services show 0 | "Every service counts what it receives. In 48 tests, zero requests reached a place a rule excludes." |
| 1:33 | Slide 5: Promise kept, to the end | "Any LiteLLM gateway can switch it on, and a pull request is ready for the Public AI Utility. With Apertus and our sovereignty layer, a commune can check, request by request, where citizen data goes." |
| 1:48 | Slide 5 | "And Ana? She got her answer, in Italian. Her data never left Switzerland, even when a provider failed. Promise kept." |

If a rehearsal runs over 2:00, cut the Tab 1 sentence about the ruled-out services first. Keep the last sentence, whatever happens.

### Prepare the demo before going on stage

Use the local stack with the latest code (`git pull`, then `docker compose up -d --build`), not the venue's Wi-Fi. A real Apertus answer takes 10 to 60 s and each switch to "waiting" about 20 s, so prepare three tabs:

1. Press **Repair all and reset counters** once, before anything else.
2. **Tab 1:** Ana's letter ("Documents needed for your support"), Italiano, explained by the real Public AI API.
3. **Break every Swiss service.** **Tab 2:** the same letter, "Explain it again". Wait until it says "waiting".
4. **Break Swiss and EU services.** **Tab 3:** the example "Second payment reminder". Wait until the consent offer appears, then open **Demo controls** in this tab.

### On stage (driver)

1. **Tab 1:** scroll so the answer and the struck-through services are visible.
2. **Tab 2:** the letter waiting, with Singapore blocked.
3. **Tab 3:** "Send it to the United States instead…", tick "I understand", **Send it to the United States**. The US counter goes to 1.
4. In the demo controls, set **Swiss host 1** to **Working**, then **Try again now** in Tab 2. Ana's letter completes. The answer comes from a simulated Swiss host and says so.

If the demo breaks, play the teaser (`docs/video/teaser.mp4`, 25 s) and continue with the proof slide.

### Q&A on the main stage (1 minute: one sentence, then stop)

| Question | Answer |
|---|---|
| "Can you prove the data stays in Switzerland?" | "We prove where our gateway sends it, with each service's own counter. Where a provider physically computes needs contracts or audits, and we say so." |
| "Who can use this?" | "Any LiteLLM gateway: it's a plugin, one line of config. For the Public AI Utility there's a ready pull request." |
| "Isn't waiting bad for users?" | "A letter with a deadline in days can wait minutes; a leak can't be undone. Where the office allows it, the resident can choose not to wait." |
| "Why Apertus?" | "It's open, it's Swiss, and it explains these letters in all our languages, Romansh and Swiss German included." |
| "What's next?" | "Get the pull request merged, add evidence for each provider, and turn TLS verification back on in the Utility." |
| "Did you build something?" | "Yes: a plugin for LiteLLM, running at promisekept.ch. The letter service is only the example." |
| "Can it process images?" | "Apertus 1.5 reads images; our prototype sends text so far. A photo of the letter would get the same rule." |

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
| "Is this a pull request for LiteLLM?" | "No. It is a plugin that the standard LiteLLM loads, with no fork. The pull request is for the Public AI Utility's deployment: it adds the metadata and switches the plugin on." |
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
- [ ] `git pull` and `docker compose up -d --build`: the app changed (languages, upload)
- [ ] The three tabs prepared (see "Prepare the demo before going on stage")
- [ ] `PUBLICAI_API_KEY` set, or the SIMULATED label is visible and we say so
- [ ] `caffeinate -d` running, charger plugged in, notifications off
- [ ] Backup video on the desktop
- [ ] Timer: 60 s and 120 s versions rehearsed at least twice
