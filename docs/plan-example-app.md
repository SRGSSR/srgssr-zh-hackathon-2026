# Plan: a stronger example for data sovereignty

Status: proposal for the team, 25 Sep 2026, about 01:00. Decisions needed are listed at the end.

## What makes an example "strong" for this pitch

The jury should understand in five seconds why it matters where the data goes. A good example:

1. **Legally sensitive data.** Special categories of personal data, or data under official secrecy, not just "personal data".
2. **A real need.** The residents who need the service most read German poorly and must meet deadlines.
3. **The commune is the competent authority**, so a commune-run service is plausible.
4. **Waiting is acceptable.** The task is asynchronous: a letter can wait ten minutes, a leak cannot be recalled.
5. **Demo-able with fictional data**, in under a minute.

## Candidates

Legal references are **to be verified**. We are not lawyers; see the notes below.

| | Case | Sensitivity | Need | Commune's role | Waiting OK | Demo | Verdict |
|---|---|---|---|---|---|---|---|
| **A** | **Social assistance letter** (Sozialhilfe: documents to submit, duty to report changes, possible cut or repayment, right to be heard) | Very high. Social assistance data is a special category in data protection law. Letters often mention health (medical certificates) and children. | Very high. Many recipients are not native German speakers; a missed deadline can cut benefits, and fear about residence permits is real. | Direct: in many cantons social assistance is run by the communes. | Yes (deadlines in days) | Easy | **Recommended hero case** |
| B | Debt enforcement "Zahlungsbefehl" (10 days to object) | High (financial distress) | Very high (hard 10-day deadline) | Weak: it comes from the district debt enforcement office, not the commune | Yes | Easy | Strong second, but it weakens the "commune" story |
| C | Tax assessment (current sample) | Medium to high (tax secrecy on the authority's side) | Medium | Direct | Yes | Already built | Keep as an "ordinary" sample |
| D | Child and adult protection (KESB) | Maximal | High | Indirect | Yes | Too heavy for a demo | No |
| E | **Staff at the counter**: a social services caseworker explains a decision to a resident in their language | Very high; staff are bound by official secrecy | High: today staff cannot legally paste case data into public chatbots | Direct | Yes | Same app, "counter mode" | Framing to combine with A |
| F | Health insurance premium reduction (IPV) | Medium | Medium | Mostly cantonal | Yes | Easy | No |

**Recommendation: A, told through E.** The hero is a social assistance letter that a resident brings to the commune, or reads at home.

- **The one-sentence "why".** Social assistance data is among the most protected personal data. The public servant who helps the resident is bound by official secrecy. When a provider fails, the Utility's own fallbacks today can send such a letter to another model in another country.
- **Our story.** The rule holds on every attempt. If no Swiss endpoint is up, the letter waits in Switzerland.

Notes to verify before we say them on stage:
- Federal law (nDSG Art. 5 lit. c) lists data on social assistance measures and health data as sensitive personal data. Communes are bound by **cantonal** data protection law, which has similar categories (for example Zurich IDG § 3). **Check the canton we name.**
- Official secrecy: StGB Art. 320. Tax secrecy: DBG Art. 110.
- The Swiss data protection authorities' conference (privatim) has published a resolution on cloud use by public bodies. **Check the wording and date before quoting it.**

## Improvements to the app, by value per hour

| Prio | Change | Why it helps the pitch | Effort |
|---|---|---|---|
| P1 | **Two fictional social assistance letters**. One asks for documents, mentions a medical certificate and states the duty to report changes, with a deadline and the risk of a cut. One asks to repay CHF 1'240 and gives a deadline for the right to be heard. Mark them "sensitive: social assistance + health". | The hero case | 30 min |
| P1 | **Minimise before sending.** The app removes AHV numbers, IBANs, phone numbers and e-mail addresses before the letter leaves it; the model does not need them. The timeline shows "removed before sending: AHV number, IBAN". A test asserts that no endpoint ever received "756." | A second, independent promise: even approved endpoints get less. Testable with the mocks' request logs | 45 min |
| P1 | **"What happened to your data" receipt** on the result page. It says: stored in the commune's service in CH; sent only to [endpoints, declared jurisdiction]; excluded before any send: [list]; request deleted from the gateway at [time]. With a **"Delete my letter now"** button. | Turns the timeline into something a resident understands; shows the right to erasure | 60 min |
| P1 | **"Why this rule" box**: two sentences on the legal reason (hedged wording, see notes) and who set the rule (the commune, bound to its key) | The jury sees sovereignty as a legal need, not a feeling | 15 min |
| P1 | **Real Apertus run** with the Public AI key on the three samples; check the quality of the Italian, Portuguese and Albanian explanations and of the German draft; fix the prompt | Credibility of the civic value | 45 min |
| P2 | **Two rules, two keys.** A "general information" key (no personal data, e.g. "what documents do I need for social assistance?") may use EU or CH endpoints; the "my letter" key is CH-only. The same question goes out on two different routes. | Shows that sovereignty is per data class and bound to keys | 60 min |
| P2 | **Counter mode**: large type, explanation in the resident's language and in German side by side, printable | Supports the staff story (E) | 45 min |
| P3 | Deadlines as a calendar file (.ics) | Nice UX, low risk | 20 min |
| P3 | More languages (Tigrinya, Arabic, Ukrainian, Tamil), if Apertus handles them well in our test | Reach | 15 min + testing |

## Proposed schedule until submission (Fri 12:00)

| When | What | Who |
|---|---|---|
| now to 01:30 | Commit the gateway queue, pitch doc draft, this plan | Claude |
| 08:00 to 08:15 | Team decision on the questions below | all |
| 08:15 to 10:00 | P1 items in parallel. Samples and "why this rule": DE speaker, who writes the letters in convincing bureaucratic German. Minimisation and test: 1 person. Receipt and delete: 1 person. Real Apertus run and prompt: IT and FR speakers check the explanations in their languages. | 5 people |
| 10:00 to 10:45 | Full test bench, fix, freeze the code, record a backup demo video | 2 people |
| 10:45 to 11:40 | Pitch rehearsal (1 min and 2 min versions), Q&A drill | all |
| 11:40 to 12:00 | Submission | 1 person |

## Decisions needed

1. **Hero case**: social assistance (A), with the counter framing (E)? Or keep the tax letter?
2. **Minimise before sending**: yes? It adds a claim we can test, "no endpoint ever received the AHV number".
3. **Receipt and "Delete my letter now"**: yes?
4. **Two keys** (P2): worth an hour, or is one policy enough (the brief says one policy)?
5. **Which canton do we name** for the legal basis, if any? (Keep it generic if nobody can check.)
