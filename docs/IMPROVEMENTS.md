# Improvements: v1 → v2

This is a record of everything that changed between the original project (v1, a set of flat scripts and a single
HTML file) and this version (v2), and **why**. Every claim about v1 refers to the original source as received.

---

## At a glance

| | v1 | v2 |
|---|---|---|
| Structure | 5 flat Python scripts + 1 HTML file | `iip/` package (26 modules), `web/` app (33 ES modules + 6 stylesheets), `tests/`, `scripts/`, `docs/` |
| Code style | several statements per line (`a; b; c`), ~700 dense lines | one statement per line, type hints, docstrings, ruff-clean |
| API operations | 13 | 21 (all v1 paths kept) |
| Risk signals | 8 | 11, each mapped to a MITRE ATT&CK technique |
| Impossible travel | "different city within 2 h" | geo-velocity: haversine distance ÷ time, > 900 km/h over ≥ 500 km, judged only on trustworthy events |
| Scenarios | 6 | 10 (adds business trip, card testing, recovery abuse, password spray) |
| Live updates | none (manual refresh) | Server-Sent Events + optional live-traffic generator |
| Observability | logging only | request IDs, response times, p50/p95/p99, throughput, per-route stats |
| Protection | API key | API key (constant-time) + token-bucket rate limiting + optional non-demo mode |
| Tests | 21 | 94 |
| Tooling | — | `pyproject.toml`, ruff, GitHub Actions CI (Python 3.10 – 3.13), Dockerfile with healthcheck |
| Frontend | 92-line HTML file, CSS bar charts, Unicode glyph icons | design system, anime.js motion, SVG/canvas charts, dotted world map, command palette, drawers, Risk Lab |
| Docs | README | README with screenshots + study roadmap + line-by-line walkthrough (83 files, 3,882 explanations) + technical reference + this file |

---

## 1. Repository hygiene and organization

* **Removed build artifacts that shipped in the zip** despite `.gitignore`: `app.db` (327 KB SQLite file),
  `__pycache__/` (5 `.pyc` files), `tests/__pycache__/`, `.pytest_cache/`. The database is now created and seeded
  in `data/` on first start, and `data/` is ignored.
* **Organized into a package** with one responsibility per module (`config`, `database`, `geo`, `rules`, `pipeline`,
  `correlation`, `queries`, `live`, `observability`, `analyst`, `seed`, `routes/*`) instead of `app.py` holding
  routes, schemas, auth, CORS, error handling and simulation logic together.
* **Frontend split by layer**: `core/` (DOM, API, bus, SSE, motion), `ui/`, `charts/`, `pages/`, `views/`, `css/`.
* **Single configuration module** (`iip/config.py`, a frozen dataclass). v1 called `os.getenv` in three modules and
  hid `load_dotenv()` as an import side effect inside `db.py`.
* **Entry point**: `python -m iip` with `--reset`, `--reload`, `--host`, `--port` (v1: `python app.py` only).
* **Dependencies split** into runtime (`requirements.txt`) and dev (`requirements-dev.txt`). `pytest` is no longer
  installed in production images.
* **Consistent line endings**: every text file uses Unix (LF) line endings, and both generators
  (`scripts/build_walkthrough.py`, `scripts/build_world_dots.py`) write LF explicitly, so a rebuild on Windows no
  longer flips files to CRLF and causes whole-file diffs.

## 2. Dead code removed

| Where (v1) | What | Notes |
|---|---|---|
| `seed.py:60` | `fresh = len(plan) and name in (...) and mix.count(name) and rnd.random() < 0` | Never true (`random() < 0`), never read, but it still consumed random numbers. |
| `app.py:12` | `WEIGHTS` imported, never used | |
| `ai.py:3,5` | two separate `from db import …` lines; `inc_id` imported, never used | |
| `static/index.html:72` | `usrRow(u).replace(/<td>\d+<td>\d+<td>[^<]*$/, "")` | A regex that deleted table cells from generated HTML to hide columns. Replaced by rendering only the needed columns. |
| `static/index.html:81` | `post("/events", {...SAMPLE, timestamp: undefined})` | A no-op spread (`SAMPLE` had no timestamp). |
| `seed.py:58` | `mix + ["account_takeover", "brute_force"]` | An ad-hoc tail appended to the scenario mix; replaced by explicit counts. |

## 3. Bugs and weaknesses fixed

1. **Impossible-travel false positives** (`engine.detect_signals`). Any change of city label within two hours scored
   +40, including Abu Dhabi → Dubai (~120 km). It also judged travel on failed logins and flagged IPs, whose
   geolocation is unreliable. v2 uses distance and speed with research-backed thresholds (§5).
2. **Crash in `/simulation/{scenario}`** (`app.py:201-202`). `dev.id` raised `AttributeError` (HTTP 500) if the
   randomly chosen user had no trusted device. v2 returns a clear 409.
3. **N+1 queries**. `users_overview()` ran 4 queries per user (≈100 for 25 users, on every dashboard load), and
   `inc_out()` ran 2 per incident (up to 400 for the incidents list). v2 batches: five queries for all users (with
   a window function) and two extra queries per incidents page.
4. **Dashboard loaded every event row into memory** to count the last seven days. v2 only reads two columns of the
   last week.
5. **Health endpoint always said `CONNECTED`**, even when the database check failed. v2 derives status from the
   check.
6. **Simulated attacks landed 30 minutes in the past** (`start = now - 30 min`), so they sank below newer events
   and never looked live. v2 shifts each scenario so its last event happens now.
7. **Half-built feature**: the `password_reset` event type was accepted by the API but never generated or scored.
   v2 adds the "Password reset after failures" signal and a recovery-abuse scenario.
8. **Misleading analyst answer**: asking about an ID that doesn't exist returned "No incidents recorded yet." v2
   says it couldn't find the record and shows the overall picture instead.
9. **Weak data integrity**: signals were JSON strings in `Text` columns, parsed on every read; no foreign keys; and
   SQLite doesn't enforce foreign keys unless asked. v2 uses JSON columns, declares FKs and turns on
   `PRAGMA foreign_keys` (which surfaced, and fixed, an insert-ordering issue in the seeder).
10. **Concurrency**: v1 used SQLite's default rollback journal; v2 enables WAL so the live generator and dashboards
    don't block each other.
11. **Tests wrote `tests/test.db` into the repo** and depended on shared state. v2 uses a temp directory, and
    detection tests reset and target a known customer so they can't be flaky.
12. **Frontend injection risk**: v1 built HTML with string concatenation and inline `onclick="openEvent('${id}')"`
    handlers (escaping was manual and easy to miss). v2's `html` tagged template escapes every value by default and
    uses delegated event listeners.
13. **README referenced a `docs/` screenshots folder that didn't exist.**

## 4. Backend architecture

* **One write path** for every source (`pipeline.process_event`): REST, simulator, live traffic and seeder.
* **Pure rulebook** (`rules.py`): no I/O, so every rule is unit-tested and reusable for what-if analysis.
  `rulebook()` exposes signals, levels and thresholds so the UI never hard-codes them.
* **Explanations stored with the event**: per-signal `contributions` (weight, human detail, MITRE technique) and
  enrichment `context` (travel distance/time/speed and verdict).
* **Incident titles** inferred from signal patterns ("Card testing", "Account takeover", "Password spray", …).
* **SQLAlchemy 2.0 typed models** (`Mapped[...]`), composite index for history lookups, IP index for spray detection.
* **Application factory** (`create_app`) with a lifespan that seeds, binds the live hub and stops background work.
* **Version-proof endpoint catalog** generated from the OpenAPI schema. FastAPI 0.142 wraps included routers
  lazily, so walking `app.routes` no longer works.

## 5. Risk engine improvements

* **Geo-velocity impossible travel**: a 21-city catalogue with coordinates, canonical labels (`"dubai"` →
  `"Dubai, UAE"`), haversine distance, implied speed. Impossible = > 900 km/h over ≥ 500 km; unknown cities fall back
  to the v1 two-hour heuristic.
* **Trusted travel baseline**: compare against the last *successful, clean-IP* event, and only judge successful,
  clean-IP events. Travel is still computed for every move, which feeds the map.
* **Three new signals**:
  * **Password spray** (+25): ≥ 5 distinct accounts failing from one IP in 30 min. This is cross-account
    correlation, not just per-user scoring.
  * **Rapid transactions** (+20): 3+ transactions in 10 min (card-testing velocity).
  * **Password reset after failures** (+15).
* **MITRE ATT&CK mapping** on every signal (T1078, T1090, T1110.001, T1110.003, T1657, T1098), surfaced as links in
  incident drawers, signal lists and the Risk Lab.
* **Deterministic, explainable output**: contributions sorted by weight with concrete details, e.g.
  "Abu Dhabi, UAE → Moscow, Russia: 3,739 km in 20 min ≈ 11,217 km/h".

## 6. New platform capabilities

* **Live streaming (SSE)** with thread-safe publishing, keep-alives, reconnect hints and slow-client back-pressure.
* **Live-traffic generator** (start/stop from the UI) for demos that feel alive, avoiding false rapid-transaction
  flags under time compression.
* **Observability**: `X-Request-ID` (propagated or generated) and `X-Response-Time` on every response, per-request
  log lines, p50/p95/p99 latency, error rate, per-route stats and ingest throughput at `/integration/metrics`.
* **Rate limiting**: token bucket per client IP on writes and the AI endpoint; 429 with `Retry-After`.
* **Demo mode switch**: `IIP_DEMO_MODE=false` stops embedding the API key in the page; the dashboard asks for it.
* **What-if scoring** (`POST /risk/evaluate`) and the **rulebook endpoint** (`GET /risk/rules`).
* **Scenario targeting** (`?user_id=`) and **demo reset** (`POST /simulation/reset`, `python -m iip --reset`).
* **Smarter analyst**: matches customers by surname, reports missing IDs, cites sources, works with any
  OpenAI-compatible endpoint (`OPENAI_BASE_URL`), and has a richer deterministic narrative.

## 7. Frontend redesign

The v1 dashboard was a standard dark-navy admin template: blue accent, rounded cards, Unicode glyph icons (▦ ≣ ⚠ ☰),
CSS bar charts, and no motion beyond a drawer slide. v2 is a new design system and application.

**Design language**
* Monochrome surfaces where **colour only means risk** (slate → amber → orange → red), plus one aqua accent for
  interactivity and "live".
* Severity badges pair colour with a 4-pip signal bar and text, for colour-blind safety.
* Geist + Geist Mono + Instrument Serif; hairline borders; crop-mark corners on hero panels; a faint dot-grid
  backdrop; a hand-drawn SVG icon set (Lucide style) and logo.

**New screens and interactions**
* **Command center**: KPI tickers with sparklines and deltas, a **dotted world threat map** (canvas + SVG) with
  travel arcs, comets on impossible routes, risk heat and live pings, a live feed, 24 h / 7 d volume, the score
  histogram, incidents, top signals with ATT&CK IDs, riskiest customers, and a travel-statistics strip.
* **Events**: search, segmented filters, paging, impossible-travel speed tags, a "new events · show" pill.
* **Incident board**: drag-and-drop triage with keyed FLIP; a border beam on the single most urgent card.
* **Customers**: a risk spectrum (every customer as a dot on 0–100) plus a filterable table.
* **Risk Lab** (new): toggle signals and presets, gauge, waterfall and formula, levels and thresholds.
* **Simulation**: scenario cards, target picker, an animated six-stage pipeline with typed step details,
  results with gauge/waterfall/timeline, a live-traffic switch, and a hold-to-confirm reset.
* **Integration**: connection hero, six live SLI tiles with sparklines, an API console (status, latency,
  request ID, highlighted JSON, copy-as-cURL), and an endpoint catalog.
* **AI Analyst**: chat with the engine decision shown separately, markdown answers, clickable source references,
  and a "thinking" shimmer.
* **Detail drawers** with history (incident → event → back): verdict gauge, score waterfall, travel check with a
  speed meter against the 900 km/h line, ATT&CK tags, correlated timeline, customer risk history, and "run a
  scenario on this customer".
* **Command palette** (`Ctrl/⌘+K`), `g`-key shortcuts, toasts for new HIGH/CRITICAL incidents, a once-per-session
  boot sequence, cursor-following spotlight borders, and a responsive layout down to 375 px with a bottom tab bar.

**Motion engineering (anime.js v4.5.0, vendored for offline demos)**
* All animation goes through one gateway (`core/motion.js`) that respects reduced motion, an in-app toggle and
  hidden tabs, and always reaches final states. Content is never hidden by CSS waiting for JS.
* While building this, a real robustness bug was caught: anime pauses in hidden documents, and ResizeObserver never
  fires there, so a dashboard opened in a background tab could freeze at invisible start states or never lay out
  its map. Both cases are handled.

## 8. Testing and delivery

* **21 → 94 tests**: pure engine tests, geo maths, API contract, every scenario end to end, analyst behaviour
  including a monkeypatched OpenAI outage and the signal-breakdown arithmetic, SSE hub, rate limiter and percentile
  maths. Stable across repeated runs, and isolated from a developer's local `.env`.
* **ruff** configuration, **GitHub Actions** (lint + tests on 3.10 – 3.13), **Dockerfile** with a healthcheck.

## 9. Bugs caught by the line-by-line review

Writing an explanation for every line of the codebase turned out to be the most thorough code review of the
project. Nine reviewers each had to justify every line they annotated, and anything that couldn't be justified was
fixed (every fix was re-verified in the running app or by a test):

| Found | Impact | Fix |
|---|---|---|
| Pages attached listeners to the shared `#view` element and the router never removed them | After revisiting a page, one click fired twice: a scenario ran twice, triage PATCHed twice, analyst questions were sent twice | The router swaps in a fresh outlet element on every navigation, so no page listener can outlive its page |
| The detail drawer re-bound its link listener on every view, only on the body | After *k* views one click pushed *k* copies onto the Back history; the incident chip in an event's header never worked | One delegated listener per drawer sheet (header + body), attached once per opening |
| The analyst's "which signals contributed" answer summed every signal seen across the incident | Its arithmetic didn't match the score in 11 of 27 seeded incidents | It now breaks down the riskiest event's own contributions (which sum to the score) and lists the rest for context; regression test added |
| "Ask analyst" while already on the Analyst page | The question was silently dropped by a cleanup hook | Removed the hook; the question is asked |
| Closing the command palette raced the API-key prompt | Outside demo mode, a fast 401 could make the key prompt vanish | A generation counter stops a stale close from hiding a re-opened palette |
| `conftest.py` deleted `OPENAI_API_KEY`, but `.env` loading filled it back in | A developer with a real key would have run the suite against the paid API (and failed tests) | The variable is set to an empty string, which `.env` loading never overrides; demo mode is pinned too |
| Simulation result timelines | Rows looked clickable but did nothing | They open the event drawer |
| Unjudged travel was labelled "flagged IP" | Failed sign-ins are unjudged too | The map, drawer and simulator now say "unverified origin" / "flagged IP or failed sign-in" |
| Two scenarios used a "flagged" documentation address with a clean reputation | Contradicted the documented IP convention | They use the clean range |
| `--line-ctl` claimed 3:1 contrast but measured 2.2:1 | Control borders were below WCAG 1.4.11 | `#666a72`: 3.6:1 on the page, ≥ 3:1 on every surface |
| Dead code: `on()` and `kbd()` helpers, `live.source`, an exported-but-internal `api()`, `.chip b` rules, three unused easing tokens, a sticky header that could never stick, a no-op responsive rule | Noise, and one layout gap: the drawer's two columns never stacked on phones | Removed; the drawer's columns now stack below 860 px |
| CI tested 3.11 – 3.13 while `pyproject.toml` allows 3.10 | The minimum version was never verified | 3.10 added to the matrix |
| Two entrance animations hit the Integration metric tiles in the same tick, and anime's `cleanInlineStyles()` restores the inline values captured when an animation starts | The six SLI tiles stayed invisible (opacity 0) on every visit | Entrances now remove exactly the inline styles they set when they finish; the redundant second entrance is gone |
| Static files were served without a caching header | After an update a normal refresh could keep running stale JavaScript (this is how the bug above first hid during verification) | Static responses send `Cache-Control: no-cache`, so browsers revalidate (an unchanged file is a cheap 304) |
| The sidebar highlight was measured only on navigation, and only vertically | A page loaded in a narrow window (where the rail becomes a bottom bar) kept the highlight parked over the "Monitor" label after widening, and in the bottom bar it stretched across every icon | The highlight covers the active link's whole box (position and size) in either layout, and a `ResizeObserver` re-places it whenever the nav changes size |

## 10. Documentation

* `README.md` rewritten: quick start, feature tour, architecture, API, configuration, docs index.
* `docs/ROADMAP.html`: a nine-stage study path with progress tracking, an animated architecture diagram, a
  request-lifecycle player, a repository map, a five-minute demo script and a glossary.
* `docs/CODE_WALKTHROUGH.html`: every line of 83 files explained beside the code, generated by
  `scripts/build_walkthrough.py`, which **refuses to build if any non-blank line is unexplained or an annotation is
  stale**.
* `docs/TECHNICAL_IMPLEMENTATION.md`: the deep technical reference.

---

## 11. Second review round

After v2 shipped, the AI analyst's answers were reported as inaccurate, and a chart tooltip stayed on screen after
switching pages. Fixing those started a second sweep: two read-only code reviews (backend and frontend), with every
finding checked against the code before it was fixed.

**AI analyst accuracy.** The old analyst recognised only `INC-n`, `USR-n` and surnames. Every other question got the
same "top incidents" list, and "Explain EVT-…" or "Summarize the last 24 hours" explained an unrelated incident. It
now parses each question into explicit search terms (record IDs in any form, customer names, signals and attack
patterns, cities and countries, risk levels, statuses, event types, outcomes, time windows) and answers from SQL
searches with exact counts, definitions that quote the rulebook's thresholds, the scoring model, or an overview. On a
probe of 20 realistic questions the old version answered 2 correctly and the new one all 20, with every count matching
a direct SQL count.

**Off-topic questions.** Asking about something unrelated ("Shawerma") still produced the incident queue, as if it
answered the question. A question with none of the platform's vocabulary is now recognized: the analyst says it isn't
related, names the odd word, and suggests what to ask, without retrieving records or calling the model, and greetings
and thanks get a short reply. A probe of 176 questions (44 unrelated, 30 small talk, 102 about the platform) is
classified without a miss.

| Problem | Effect | Fix |
|---|---|---|
| A chart tooltip was only hidden on `pointerleave` | Hovering the world map and switching pages left the tooltip on screen (closing a drawer with Escape, or scrolling, did the same) | The router hides it on every navigation, and the tooltip hides itself on scroll, clicks and key presses |
| A page's cleanup context accepted registrations after the page was left | Leaving a page during its first fetch leaked its listeners and timers; the Integration page's 4-second metrics poll then ran forever | The context knows it was disposed and tears late registrations down at once |
| World-map comet animations looped forever | Each resize or visit to the overview added three animations that never stopped | Comets are kept and cancelled on relayout and when the page is left |
| Live toasts only knew incidents that were open at start-up | A status change on an investigating incident was announced as a new incident and bumped the badge | Toasts are seeded with every incident; the badge is recounted from the API |
| The drawer's status control switched before saving | After a failed save it showed a status that was never saved and ignored a retry; the header badge never updated | It reverts on failure, so a retry works, and the header badge follows a successful save |
| Unrelated questions | "Shawerma" was answered with the incident queue, as if it matched | Questions with none of the platform's vocabulary are told they aren't related, with examples to try; greetings get a short reply; neither reaches the model |
| The analyst rejected two-letter messages | "hi" got a validation error instead of a greeting | Questions may be two characters long |
| Answers printed raw asterisks | The terms read back in italics (*Impossible travel · Lagos*) showed their asterisks | The answer renderer supports italics |
| Long source lists squeezed their links | "INC-0030" broke across two lines under an answer | The sources line wraps between links |
| Counts ignored the singular | Incident cards, drawers and analyst answers said "1 events" and "1 correlated events" | Every count agrees with its noun |
| The API console stretched after a response | Long JSON lines pushed the console over the endpoint catalog and could shift the page sideways | Its grid column is `minmax(0, 1fr)`, so long lines scroll inside the code block |
| The speed meter's airliner label | On very fast trips the label sat near the left end and was cut off | It starts at the marker instead of being centred on it |
| A map stat label was truncated | "Unverified origins" showed as "UNVERIFIED ORIGI…" on a laptop screen | Renamed "Unverified trips", next to "Plausible trips" |
| Walkthrough notes quoted stale line numbers | About 30 notes said "Line N closes…" with N a few lines off after earlier edits | They say "the last line closes…", which cannot drift |
| Events and Risk Lab rendered responses in arrival order | A slower, older response could show results for the wrong filter or selection | Requests are numbered; only the newest may render |
| The live stream gave up on error responses | A proxy 502 during a restart left the app offline until a reload, and missed messages were never refetched | It reconnects with growing delays, and `live:resync` makes pages refetch |
| Drawer and palette races | A drawer reopened during the close animation was wiped; a slow failed view overwrote a newer one; the palette dropped focus and could render over the API-key prompt | Close and render guards, focus restore, and Tab kept inside both modals |
| Keyboard gaps | Timeline rows could be focused but not opened; shortcuts acted on the page behind an open drawer; a cancelled drag left a stale card behind | Enter or Space opens rows, shortcuts pause behind the drawer, the dragged card is cleared |
| "Ask analyst" on the Analyst page | Asking from a drawer while on that page re-rendered it and wiped the conversation | The question is handed to the open page |
| Event timestamps had no range | A year-2099 event kept the customer's incident open to every later event; a year-1 date caused a 500 | Timestamps must be after 2000 and at most five minutes ahead |
| Correlation windows were bounded on one side only | A backfilled event could join, or pull in, activity that happened after it | Both windows are bounded on both sides |
| Stopping live traffic didn't wait for a running tick | A reset could race a tick still writing, and a start during the stop was orphaned | `stop()` clears its handle first and waits for the in-flight tick |
| The city fallback ignored the country | "London, Ontario" became London, UK, so a Londoner in Canada looked at home | A city name counts only when the country agrees (shared `COUNTRY_ALIASES`) |
| Metrics were keyed by raw path; rate-limit buckets were never pruned | Every probed URL and every client address added memory forever | Route templates, one `(unmatched)` entry, and pruning of idle buckets |
| Malformed IDs and request IDs | `INC-²`, a 20-digit id or a non-UTF-8 `X-Request-ID` caused 500s | 404s for bad IDs; unsafe request IDs are replaced |
| A whitespace-only location passed validation | It was stored empty and raised "Unusual location" | Text is stripped before the length check, so it is a 422 |
| Business trip with live traffic on | No customer was quiet, so the replayed trip was (rightly) flagged as impossible | It needs a quiet customer, or returns a 409 that says why |
| The dashboard summary loaded a week of events into Python every 30 s | Cost grew with every hour of live traffic | Day counts in SQL, only the last 24 hours loaded for the hourly chart |

**Dead code removed:** nine icons no screen used, a `panel()` option no page passed (it was also an unescaped `raw()`
sink), two spotlight targets doing work every frame with no visible effect, three CSS rules repeating the global
`[hidden]` rule, a never-generated CSS selector, two unused dashboard aggregates (one cost a query on every refresh),
a duplicate event list in the customer profile, and the old URL-rewriting regex in the metrics middleware.

**Tests:** 83 → 94: six analyst accuracy tests, an off-topic test, and four regression tests for the review fixes.

## Research notes

The internet and GitHub research behind these changes, and what was adopted:

**Impossible travel thresholds**
* **Panther** `Standard.ImpossibleTravel.Login`: > 900 km/h ("Boeing 747 cruising speed"); VPN / Private Relay
  logins are not used as the comparison baseline. → Adopted the 900 km/h threshold and the trusted-baseline idea.
* **Datadog Cloud SIEM**: > 1000 km/h *and* > 500 km. **Elastic** Entra ID rule: ≥ 800 km/h and ≥ 500 km.
  → Adopted the 500 km minimum distance.
* **Microsoft Defender for Cloud Apps / Entra**: no alert for failed or non-interactive logins; VPN and corporate
  IPs are suppressed. **Okta** behaviour detection uses 805 km/h (500 mph). → Travel is judged only on successful,
  clean-IP events.

**Detection ideas**
* Password spray as "many accounts failing from one IP" mirrors Entra ID Protection's password-spray detection,
  Auth0 Suspicious IP Throttling and Sigma `value_count` correlations (MITRE **T1110.003**).
* MITRE ATT&CK IDs verified on attack.mitre.org (v19): T1078 Valid Accounts, T1090 Proxy, T1110.001 Password
  Guessing, T1110.003 Password Spraying, T1657 Financial Theft, T1098 Account Manipulation.
* Ideas recorded for future work: Elastic entity risk scoring (diminishing returns instead of a clamp, risk inputs
  as explainability), Splunk RBA (escalate on tactic diversity), Sigma correlation rules as YAML, CrowdSec
  leaky-bucket decay.

**Design and motion** (from the bookmarked sites the owner shared)
* **Magic UI** (source read on GitHub): Animated Beam, Border Beam (ring mask + `offset-path`), Number Ticker,
  Magic Card spotlight, Dotted Map, Blur Fade. → Recreated in vanilla CSS/JS: pipeline packets, the urgent-card beam,
  KPI tickers, spotlight borders, the dotted world map, staggered blur-fade entrances.
* **KokonutUI**: Smooth Tab (spring-driven sliding pill), Hold Button, action search bar, shimmer text.
  → Segmented controls with a spring pill, hold-to-confirm reset, command palette, "thinking" shimmer.
* **Bklit UI** charts: monochrome palette, dashed hairline grids that fade at the edges, a clip-path reveal at
  1100 ms `cubic-bezier(.85,0,.15,1)`, snapping crosshair, haloed dots. → Adopted directly in the area chart.
* **60fps.design / Refero / Raylight / GetLayers**: graph draw-in, ticking numbers and blur-to-focus entrances as
  recurring patterns; "avoid centred hero + three cards + flat gradient".
* **anime.js v4** API verified against the 4.5.0 source (ESM/UMD paths, `spring()`, `createDrawable`,
  `createMotionPath`, `utils.cleanInlineStyles`, and the fact that v3-style ease names silently fall back to linear).
* **Accessibility**: WCAG 2.2.2 (a pause control for motion), 1.4.11 (3:1 non-text contrast), and colour-blind
  separation of the risk ramp (hence pips + text on every severity).
