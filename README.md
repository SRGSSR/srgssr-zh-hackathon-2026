# Swiss Grounding MCP: "Where do you live?" first

An MCP server that grounds AI assistants in **authoritative Swiss public sources**. It works **jurisdiction-first**:
before any data is looked up, each question is checked against the place it concerns. Places are resolved to the
official municipality (BFS number) and canton through the federal gazetteer. The server then returns evidence from
the body responsible for that place, cites it with dates, and says so plainly when a question is outside
Switzerland, outside its scope, or cannot be verified right now.

Thirteen MCP tools, compact JSON, **no API keys**, runs locally with one command.

## The 1-minute pitch

> Ask an LLM "What's the cheapest basic health insurance in Lugano at CHF 2,500 deductible?" and you get a
> plausible, uncited number from an old year. Ask "Wann wird bei uns Karton abgeholt?" and it guesses a city. Ask
> about the radio fee after moving to Konstanz and it quotes the Swiss fee, even though Konstanz is in Germany.
>
> The core problem in Switzerland is **jurisdiction**. The right answer depends on the municipality, and there
> are more than 2,100 of them, 26 cantons and 4 languages. Our server fixes that before it fetches anything:
>
> 1. **Resolve the place.** Any municipality, postcode or street address goes through swisstopo's official
>    gazetteer to a BFS number and canton. Konstanz becomes "not Swiss, out of scope", Wil becomes "Wil ZH or
>    Wil SG?", and "bei uns" becomes a request for the municipality. The server asks back only when the answer
>    really depends on it. The 12-month deadline to exchange a foreign driving licence is federal, so it never
>    asks for a canton there.
> 2. **Answer from the owner of the data.** FOPH premium tables for every municipality, the housing office's
>    reference rate, FSO population figures and vote results, the official timetable, Zürich's collection calendar,
>    and ch.ch (the Confederation's portal, indexed in DE/FR/IT/**RM**/EN), which links onward to the right
>    cantonal and municipal offices.
> 3. **Cite, date and label authority.** Each answer carries the source URL, publisher, level (federal, cantonal,
>    municipal, semi-official, aggregator or unverified), the supporting passage and its date. Stale pages are
>    flagged. When a source is down, the server says so, or discloses that it is serving a cached copy.
>
> The front door is `swiss_ground(question)`, a keyless router. It decides one of: out of scope, ask for the
> municipality, ambiguous, varies by canton, unsupported, or routed to the right data tool with its arguments
> already filled in. An LLM usually needs one or two calls.
>
> **AI doesn't need more Swiss search results. It needs to know which Swiss source it is allowed to believe.**

## Declared scope

| Topic | Geography | Reference period | Source (authority) |
|---|---|---|---|
| Jurisdiction resolution (place, postcode or address → municipality, BFS no., canton) | All of Switzerland | Current boundaries | swisstopo swissBOUNDARIES3D / geo.admin.ch (federal) |
| Mandatory health insurance premiums (KVG/LAMal): cheapest, cheapest standard model, median, maximum | All municipalities and premium regions | Premium year **2026** (prebuilt index) | FOPH/BAG premium data on opendata.swiss, Priminfo premium regions, BAG insurer register (federal) |
| School holidays | All cantons, at municipality level where published | Any year in the dataset | OpenHolidays (**aggregator**, labelled as such), plus a link to the cantonal education department |
| Waste collection dates (cardboard, paper, household waste, organic waste, hazardous-waste mobile) | **City of Zürich**, per postcode. Other municipalities return `not_covered` plus their website | 2026 calendar (live) | Stadt Zürich open data, ERZ Entsorgung + Recycling (municipal) |
| Mortgage reference interest rate for rents: rate, valid since, next publication, exact supporting sentence | Switzerland | Live, published quarterly | Federal Office for Housing FOH/BWO (federal) |
| Permanent resident population: municipality, canton and Switzerland, change on previous year, share of foreign nationals | All municipalities (boundaries as of 06.04.2025) and cantons | 31.12.2025 (prebuilt; FSO database of June 2026) | FSO STATPOP, PxWeb table px-x-0102010000_101 (federal) |
| Public transport connections | Switzerland | Live timetable | opentransportdata.swiss via transport.opendata.ch (FOT mandate) |
| Federal votes: subjects and results | Switzerland | 2025 to Nov 2026 | Federal Statistical Office OGD feed, Federal Chancellery / Federal Council |
| Procedures and rights: moving and registration, permits, driving licence, AHV, unemployment, taxes, customs, radio/TV fee, renting, building … | Federal rules plus links to the responsible cantonal and municipal offices | ch.ch index of 2026-09-24; linked pages read live | ch.ch (Federal Chancellery and cantons), then `read_official_page` on the linked authority |
| Routing and jurisdiction decisions (`swiss_ground`) | All of Switzerland | n/a | Source registry `data/sources.yaml`: 18 topics, 26 cantons, 11 city websites, 58 foreign place names |
| Commercial register lookup | Switzerland | Live | Zefix (Federal Office of Justice). **Blocked by default**, because zefix.ch's robots.txt disallows bots |

**Out of scope (the server says so):** other countries, tax calculations, waste calendars outside the City of
Zürich, full law texts and legal advice, weather, statistics other than population, personal data. Foreign places are detected in the
question ("nach Konstanz", "in München", "en France"), or reported as `not_found` by the federal gazetteer. The
server then tells the assistant not to apply Swiss rules.

## Tools

| Tool | Purpose |
|---|---|
| `swiss_ground(question, place?, language?)` | **Start here.** Returns a `decision`: `out_of_scope`, `ambiguous`, `needs_jurisdiction` (with `question_for_user` in the user's language), `varies_by_canton`, `unsupported` or `routed`. A routed result includes an `authority_chain`, a prefilled `next_call` and/or ch.ch `evidence`. Questions naming several places return one entry per municipality in `jurisdictions[]`. |
| `resolve_swiss_location(place)` | Resolves a place to a municipality, BFS number and canton. Handles exonyms (Berne, Genf, Coire), bilingual names (Biel/Bienne) and villages inside a municipality (Wengen → Lauterbrunnen). Returns `ambiguous` with a question for the user, or `not_found` (not Swiss). |
| `health_insurance_premiums(place, age, deductible, accident_cover?, model?, limit)` | Official monthly premiums for the person's premium region. Resolves the place itself, so it takes one call. Respects insurer catchment areas. |
| `school_holidays(place, year?, language)` | Holiday periods for the municipality's subdivision. |
| `waste_collection(place, material?, from_date?)` | Next collection dates for the City of Zürich by postcode. Asks only for the postcode if it is missing. Other places return `not_covered`. |
| `reference_interest_rate(language)` | Current reference rate, effective date, last confirmation, next publication date, and the exact sentence from bwo.admin.ch. |
| `municipality_population(place? or canton?)` | Permanent resident population on 31 December (latest year), change on the previous year and share of foreign nationals, for the municipality, its canton and Switzerland. For a village it says the figure is for the containing municipality. For places whose status changed after the FSO boundary date (Villnachern, Moutier), it returns the former municipality's own row and says so. |
| `public_transport_connections(origin, destination, when?, arrive_by?, limit)` | Next connections, with lines and platforms. |
| `federal_votes(vote_date?, language)` | Next or given federal vote: subjects in DE/FR/IT/RM/EN, and results once counted. |
| `search_swiss_guidance(query, language?, limit)` | BM25 search over ch.ch sections in five languages. Each excerpt is centred on the sentence that best answers the question, with durations favoured for "how long" questions. Returns authority links. |
| `read_official_page(url, focus?, max_chars)` | Reads Swiss domains only. Returns the sections matching `focus`, links, an authority label and **freshness** (`last_updated`, `stale` if older than 2 years). |
| `company_register_search(name)` | Zefix lookup, subject to the robots.txt policy. |
| `server_coverage()` | Declared scope, data build dates, configuration and health metrics. |

**Result envelope.**
- **Status:** every result has a `status` (`ok`, `ambiguous`, `not_found`, `not_covered`, `needs_postcode`,
  `invalid_input`, `blocked`, `unavailable`, `not_published`) or, for `swiss_ground`, a `decision`.
- **Sources:** each result carries `sources[]` with `title`, `url`, `publisher`, `level`, `retrieved` (the actual
  fetch time), `valid_for` and `last_updated`.
- **Cache disclosure:** results served from cache carry `data_as_of`. If the live source was down, they also carry
  `served_from_cache`.
- **Grounding policy:** the server-level `instructions` tell the assistant to:
  - call `swiss_ground` when unsure,
  - ask only for missing context that changes the answer,
  - stay within Switzerland,
  - cite sources with their dates,
  - flag stale sources,
  - fail honestly,
  - answer in the user's language.

## Run it

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). No API keys or credentials are needed.

```sh
uv sync
uv run swiss-grounding-mcp                                   # stdio (Claude Desktop, Claude Code, Cursor, …)
uv run swiss-grounding-mcp --transport streamable-http --host 0.0.0.0 --port 8000   # http://host:8000/mcp
```

The HTTP mode is stateless and returns JSON responses, so it works behind a load balancer.

Client configuration (stdio):

```json
{ "mcpServers": { "swiss-grounding": {
    "command": "uv", "args": ["run", "--directory", "/path/to/swiss-grounding-mcp", "swiss-grounding-mcp"] } } }
```

Docker (streamable HTTP on port 8000; the image build has not been tested yet):

```sh
docker build -t swiss-grounding-mcp . && docker run -p 8000:8000 swiss-grounding-mcp
```

## Tests

All three suites talk to the server over real MCP stdio, as a client would:

```sh
uv run python tests/smoke_test.py     # 11 tool-level checks
uv run python tests/benchmark.py      # 59 adversarial cases → table + tests/benchmark_report.json
uv run python tests/fault_test.py     # simulated outages: stale cache disclosed, or honest "unavailable"
```

Status on 2026-09-24: smoke **11/11**, benchmark **59/59**, fault test **3/3**.

## Adversarial benchmark

`tests/benchmark.yaml` has 59 cases in DE/FR/IT/RM/EN, including the five published sample questions. Each case
checks the decision, jurisdiction, routing, evidence, response size and latency. For routed cases the runner also
executes `next_call`, to count the calls an agent needs end to end (1–2).

| Category | What it catches |
|---|---|
| foreign | Konstanz, München, Milano, France. "Moving *from* Germany to Zürich" must stay in scope. |
| ambiguous | Wil ZH vs Wil SG; "Biel" must resolve to Biel/Bienne, not Biel-Benken |
| needs_jurisdiction / missing_context | "bei uns", "chez nous"; a missing age or origin station |
| federal (asking back would be wrong) | votes, AHV, unemployment, customs, permits, radio/TV fee, the foreign-licence deadline |
| varies_by_canton | "überall in der Schweiz", "dans tous les cantons" |
| municipal | Zürich waste by postcode or address; Lausanne `not_covered`; Winterthur registration |
| multi_jurisdiction | "Lausanne? Et à Berne?", premiums in Zürich and Lugano |
| data: population | Scuol; "Combien d'habitants compte Lausanne?" (place without a preposition); canton Wallis; the former municipality Villnachern |
| freshness / operability | the current reference rate, a stale SEM page from 2011, Zefix robots.txt, non-Swiss URLs |
| unsupported | off-topic questions (capital of Australia, baking a Zopf, the World Cup) |

Current result: **59/59**, median response 1.3 KB, median latency 13 ms with a warm cache.
- **What it measures:** this server's own decisions, not an LLM baseline.
- **How the cases were written:**
  - 39 cases were written together with the router.
  - 5 come from a held-out check.
  - 6 come from the organisers' practice cases.
  - 3 check that the sample-question deadline (12 months) appears in the returned excerpt in DE/FR/IT.
  - 6 cover population and place-resolution edge cases.
- **Caveat:** expect lower accuracy on unseen phrasing (see Known limitations).

### Organisers' practice cases

The self-check pack in the challenge repository contains 8 practice cases and a review checklist. **Do not run its
launcher.** It executes code from git history, opens terminal windows, plays audio and prints instructions aimed at
AI agents. We decoded the practice cases as plain data and checked them against the server:

| Practice case | How the server handles it |
|---|---|
| "Wann wird bei uns Karton abgeholt?" | `needs_jurisdiction`: asks only for the municipality. In the City of Zürich it then asks only for the postcode. |
| Geneva school holidays 2026 | Routed straight to `school_holidays` for Genève, with no ask-back. Caveat: the dates come from an aggregator; the cantonal page is linked. |
| Rundfunkbeitrag Konstanz | `out_of_scope` (Germany) |
| Scuol, Romansh | Resolved to Scuol GR; 2026 calendar at municipality level |
| Current reference rate (IT) | `reference_interest_rate`: 1.25 %, valid since 2025-09-02, confirmed 2026-09-02, next publication 2026-12-01, with the exact sentence |
| "Lausanne? Et à Berne?" | `jurisdictions[]`: each municipality resolved separately, with its own authority chain |
| Citation support | Tools return the supporting passage (`evidence` excerpt, `sections`), not just a homepage |
| Source unavailable | Stale-if-error: a cached copy with `served_from_cache` and `data_as_of`. With nothing cached, `unavailable` is explicitly labelled a retrieval failure. |

## Resilience and provenance

- **Fetch log:** every upstream read is logged for the duration of a tool call.
- **Stale-if-error:** if a source fails with a network error, a 5xx or a 429 (rate limited), the last cached copy (at most
  `SGM_STALE_MAX_DAYS` old) is served. The result then carries `served_from_cache`, a note telling the assistant to
  disclose it, and `data_as_of`.
- **Other 4xx are never masked:** the resource really is gone.
- **Honest timestamps:** each citation's `retrieved` field is the actual fetch time, not the time it was served.
- **Tested:** `tests/fault_test.py` exercises this end to end with `SGM_FAULT_HOSTS`.

## Source registry

`data/sources.yaml` lists what the server trusts:
- federal domains, and semi-official bodies with a legal mandate;
- the 26 cantons: domain, languages, the names used to detect them in free text, education office;
- municipal websites, by BFS number;
- foreign place names;
- topics, each with:
  - multilingual keywords;
  - the deciding level (federal, cantonal or municipal);
  - `needs_place`: true only when the answer truly depends on the place;
  - the data tool to route to;
  - authoritative URLs;
  - optional `search_terms`: the portal's official wording per language. Users say "patente", ch.ch says
    "licenza di condurre".

Adding a municipality, topic or synonym is a YAML edit, with no code change.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SGM_RESPECT_ROBOTS` | `true` | Respect each source's robots.txt. Set to `false` to switch it off for testing (this enables Zefix, for example). |
| `SGM_CACHE` / `SGM_CACHE_DIR` | `true` / `.cache` | Two-level cache (memory and disk) with a TTL per source: 60 s for the timetable, 6 h for the reference rate, 1 day for pages and calendars, 30 days for boundaries. |
| `SGM_STALE_MAX_DAYS` | `30` | When a source is down, serve the last cached copy up to this age. It is always disclosed as `served_from_cache`. |
| `SGM_FAULT_HOSTS` | *(empty)* | Comma-separated hosts to treat as unreachable, for resilience tests and demos. |
| `SGM_TIMEOUT` | `15` | Upstream timeout in seconds. |
| `SGM_IPV4_ONLY` | `true` | Forces IPv4. Many networks (WSL, Docker, venue Wi-Fi) resolve IPv6 addresses but cannot route them. |
| `SGM_CA_BUNDLE` | OS trust store | Custom CA bundle, for corporate TLS proxies. |
| `SGM_USER_AGENT` | `Mozilla/5.0 (compatible; swiss-grounding-mcp/0.1; …)` | User agent sent upstream. |
| `SGM_ALLOWED_HOSTS` | *(empty)* | For HTTP mode: a comma-separated host list that enables DNS-rebinding protection. |
| `PORT` / `SGM_HOST` / `SGM_TRANSPORT` | `8000` / `127.0.0.1` / `stdio` | Server binding. |
| `SGM_LOG_LEVEL` | `INFO` | Logs one line per tool call, with its duration. |

## Prebuilt indexes and how to rebuild them

All three datasets ship in `data/` (21 MB, 15 MB and 157 KB), and all three build scripts are in this repository:

```sh
uv run --extra build python scripts/build_premiums.py --year 2026   # FOPH premiums → data/premiums_2026.sqlite
uv run python scripts/build_chch_index.py                           # ch.ch sitemap crawl → data/chch_index.sqlite
uv run python scripts/build_population.py                           # FSO STATPOP → data/population.json
```

Population is prebuilt rather than queried live: it changes once a year, and the FSO PxWeb API sometimes takes
more than 30 s to answer. The script reads the table's reference date, database state and boundary date, and the
tool reports them.

The ch.ch crawler respects robots.txt and rate-limits itself; it indexes 1,726 pages, with each page's modification
date. When the FOPH publishes the **2027 premiums** (end of September 2026), run the premium script with
`--year 2027`. The server loads the newest `premiums_*.sqlite` file.

## Project layout

```
src/swiss_grounding/
  server.py     MCP tools, grounding instructions, provenance and error envelope
  router.py     swiss_ground: language, topic, place, foreign detection → decision
  geo.py        federal gazetteer: place / postcode / address → municipality, canton
  premiums.py   FOPH premium index queries
  sources.py    connectors: transport, holidays, votes, Zefix, Zürich waste, reference rate, population
  guidance.py   ch.ch search, official page reader, freshness
  registry.py   loads data/sources.yaml (authority levels, topics, cantons, municipalities)
  core.py       config, cached HTTP, robots.txt, stale-if-error, citations, metrics
data/           prebuilt indexes + source registry
scripts/        index build scripts
tests/          smoke test, adversarial benchmark, fault test
```

## Design notes

- **Agent efficiency:** place resolution is built into the data tools, and `swiss_ground` prefills their arguments,
  so a typical answer takes one or two calls. Results are compact JSON (about 0.3 to 3.5 KB, with no indentation or
  duplicate structured copy). Excerpts and `focus` return only the relevant passage.
- **Ask-back discipline:** the server asks for a place only if the topic's answer depends on it (`needs_place`),
  and asks for exactly that item (municipality, canton, postcode or a missing argument). Federal rules are answered
  directly.
- **Honest failure:** upstream errors come back as `unavailable` or `blocked` with an explicit "do not guess",
  never as an exception or an empty answer.
- **Monitoring:** `server_coverage` reports calls per tool, errors, cache hits, stale-cache serves, upstream latency
  and data build dates.
- **Extensibility:** a new source is one function that returns `{status, …, sources:[cite(...)]}`, plus a `@tool`
  wrapper and a topic entry in `data/sources.yaml`.

## Known limitations

- **Keyword router:** `swiss_ground` classifies topics by keyword (no LLM), so phrasings it has never seen can be
  missed. For example, "vignetta autostradale" (IT) comes back `unsupported`, while the German "Autobahnvignette" is
  found. The router prefers `unsupported` over weak evidence, and the specialised tools can still be called directly.
- **Official wording is only mapped for driving licences:** `search_terms` exists only for that topic. The English
  licence question ranks the international-licence page first.
- **Multi-place procedures:** questions naming several places are split by municipality. For procedure topics, the
  evidence is the shared ch.ch federal page plus one link per municipality; municipal forms are not fetched
  automatically.
- **School holidays:** the data comes from an aggregator, not from each canton. The result says so and links to the
  canton's education department.
- **Population:** figures use the FSO's municipal boundaries as of 06.04.2025. Municipalities created or changed
  since then are reported through their former rows, with a caveat. Villages get their containing municipality's
  figure.
- **Premiums:** the premium tool covers people resident in Switzerland only (the EU/EFTA table is not loaded). It
  does not include premium reductions or subsidies.
- **Federal vote dates:** the list is limited to dates verified on 2026-09-24. Later dates need an update to
  `FEDERAL_VOTE_DATES` in `sources.py`.
- **Page extraction:** the ch.ch index is a snapshot. Cantonal pages are read live, and not all of them use `<main>`
  markup, so text extraction is best-effort. PDFs are not parsed.
- **Commercial register:** unavailable while robots.txt is respected, because zefix.ch disallows all bots.
- **Not tested yet:** the Docker image build and connection from a real LLM client (the tests use an MCP client
  without an LLM).
