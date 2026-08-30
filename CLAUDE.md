# Compass Dashboard — CLAUDE.md

## What this is

A Python script (`scripts/compass-dashboard.py`) that reads all compass loop namespaces
from `~/.claude/loop/` and generates a self-contained static HTML dashboard by injecting
data into `scripts/template.html`.

**Regenerate:**
```bash
python3 scripts/compass-dashboard.py
# Output: ~/Downloads/compass-dashboard.html — open directly in a browser, no server needed
```

---

## Architecture

```
scripts/
├── compass-dashboard.py   — data layer + generate() + main()   (~1,830 lines)
│   ├── load_namespace()    — reads state.json, *.md, *.jsonl, history/*.md
│   ├── _js_data()          — serialises NS array as JSON embedded in HTML
│   └── generate()          — reads template.html, injects [[PLACEHOLDER]] markers
└── template.html           — HTML + <style> + <script>          (~5,020 lines)
    └── JS                  — all interactivity; operates on const NS = [...]
```

(Line counts drift fast — treat these as ballpark, not authoritative; `wc -l` the files
directly rather than trusting a figure here if it matters for your task.)

All data is baked into `const NS = [...]` at generation time. There is no runtime backend
and there never will be — static HTML only.

---

## Critical gotcha — single quotes inside JS string literals with inline `onclick`

~~JS-in-Python double-backslash escaping is no longer needed — the JS lives in `template.html`, a real HTML file. Write `\n`, `\s`, `—` etc. directly.~~

**Trap — single quotes inside JS string literals with inline `onclick`:**

If you build an HTML string using JS single-quoted string literals and embed an `onclick`
that calls a function with a string argument, the inner `'...'` breaks the outer string:

```js
// BROKEN — 'sessions' terminates the outer string literal
container.innerHTML = '<button onclick="switchHeatmap('sessions')">…</button>';
```

Fix: use a **template literal** (backtick string) for `container.innerHTML` whenever the
HTML content contains single quotes. Template literals are already used throughout the
codebase and are safe inside the Python triple-quoted string (Python does not interpret
`` ` `` or `${…}` in non-f-strings).

```js
// CORRECT
container.innerHTML = `<button onclick="switchHeatmap('sessions')">…</button>`;
```

This is a **parse-breaking** error — the entire `<script>` block fails silently and all
JS functions become undefined. If you see `ReferenceError: switchView is not defined`,
look for a broken string literal earlier in the script.

**Third trap — non-breaking spaces (`\xa0`) in JS template literals:**

Some JS template literals in this file use `\xa0` (Unicode non-breaking space) instead
of a regular space — visible only in a hex editor or when `repr()` is called. The Edit
tool's string matching is byte-exact, so searching for a regular space will silently fail
to find the line. If an Edit replacement reports "string not found" on a line you can
clearly see, check for `\xa0` characters with:

```python
python3 -c "lines = open('scripts/template.html').readlines(); [print(repr(l)) for l in lines[N-1:N+2]]"
```

Fix: use a Python script (`str.replace()`) to do the replacement, passing the `\xa0`
character explicitly in the old string.

**Fourth trap — the `<script>` block is wrapped in an IIFE:**

The whole script is `(function() { ... })();` — this keeps the ~60+ top-level functions
out of global scope so they can't silently shadow each other. But HTML strings built with
inline `onclick`/`oninput`/`onkeydown` attributes (e.g. `onclick="switchView('overview')"`)
are invoked by the browser as global lookups, bypassing the IIFE's closure entirely.

Any function called this way **must** be added to the `Object.assign(window, {...})` list
near the end of the script (just before `})();`), or clicking it throws
`ReferenceError: switchView is not defined` — the same symptom as the single-quote trap
above, but a different cause. Check both when that error shows up.

`decSort`/`decExpand` are the one exception: they self-assign to `window` at their own
definition site inside `renderDecisionsView()` (closures over local render state), so they
are deliberately *not* in the `Object.assign` list — don't add them there, it would
reference an out-of-scope identifier and throw.

**Fifth trap — plain `grep` can silently miss real matches in this file; use `grep -a`.**
Discovered 2026-08-30 auditing zone/decision CSS: `grep -n 'decision-item' scripts/template.html`
returned **zero** hits even though the class is used extensively (confirmed by opening the
file), while `grep -a -n 'decision-item' scripts/template.html` found every occurrence
immediately. Some byte sequence earlier in the file (candidates: the emoji/Unicode arrows
used throughout, or the `\xa0` bytes from the third trap above) makes `grep` treat it as a
binary file, and binary-mode `grep` without `-a`/`--text` reports matches inconsistently
rather than erroring — so a "no matches" result here is not trustworthy proof of absence.
**Always pass `-a` (or `--text`) when grepping this file**, and don't conclude a string is
missing from `template.html` based on a plain `grep` alone.

---

## Template substitution

`template.html` uses `[[PLACEHOLDER]]` markers replaced by `generate()`:

| Marker | Replaced with |
|--------|---------------|
| `[[NS_DATA]]` | JSON-serialised namespace array |
| `[[COMMUNITY_DATA]]` | JSON-serialised community federation data |
| `[[BLOCKING_EDGES]]` | JSON array of cross-namespace blocking edges (E24a) |
| `[[CARDS]]` | namespace card HTML |
| `[[GENERATED_AT]]` | generation timestamp |
| `[[N_NS]]`, `[[N_OPEN]]`, `[[N_LEARNINGS]]`, `[[N_SESSIONS]]` | header stats |

---

## Tab system (two tiers — don't confuse them)

**Top-level view tabs** (`.view-tab`, `switchView(v)`) — full-page views. `switchView()`'s
own `forEach` array is the authoritative list — this table just names what each one is for:
- `overview` — card grid + namespace detail panel
- `priorities` — cross-namespace priority signals
- `scorecard` — namespace fitness across 5 axes (parallel coordinates + ranked table)
- `dag` — force-directed dependency graph
- `heatmap` — session activity heatmap (with sub-selectors: activity, goal completion, velocity, goal types, planning, session timeline)
- `timeline` — cumulative learnings-by-tag line chart (Learning Timeline)
- `decisions` — global decisions registry across all namespaces
- `artefacts` — cross-namespace artefact browser
- `mindmap` — radial tree view of a namespace's learnings/decisions/goals/reality
- `community` — cross-namespace federation feed health + trust registry + adoption Sankey
- `compare` — cross-namespace radar comparison: overlaid polygons on 6 fixed macro axes
  (Maturity, Learnings, Decisions, Signals, Long-run discipline, Centrality), namespace
  on/off toggle recalibrates min-max normalisation live; distinct from the per-namespace
  `radar` sub-tab's toggleable micro axes

Each view has `id="view-<name>"` and `id="vtab-<name>"`. Adding a new view tab requires:
1. Button in the `<nav>` HTML
2. `<div id="view-<name>">` in the HTML
3. Name added to the `forEach` array in `switchView()`
4. `if (v === '<name>') render<Name>();` in `switchView()`
5. A `render<Name>()` function

**Namespace detail sub-tabs** (`.tab-btn`, `switchTab(t)`) — panels within a selected namespace:
`state`, `learnings`, `decisions`, `history`, `tasks`, `radar` (added 2026-08-14; `signals` also
exists conditionally when `externalSignals` is non-empty — `renderDetail()`'s `tabs` array in
`template.html` is the authoritative list)

---

## Tasks sub-tab — Backlog "Tactical"/"Strategic" bullets (2026-08-21)

`deriveTasks(ns)` (`template.html`) is a pure JS function — no compass source changes needed —
that scans `ns.reality` (raw markdown) client-side for task candidates: `## What is next`
bullets, inline `Next session: ...` lines, `plannedActions`, `deferred` opportunities, and
recent `history[].incomplete` bullets. It did **not** previously read reality.md's `## Backlog`
section at all, so namespaces that started organising their backlog under `### Tactical` /
`### Strategic` H3 subheaders (a convention some namespaces' reality.md now use, independent
of any compass-core change) had those items invisible in the dashboard's Tasks tab.

Fixed by tracking an `inBacklogSection` + `backlogBucket` state through the same single-pass
`realityLines.forEach()` that already tracks `inNextSection` — a `## Backlog` heading enters
the section, `### Tactical`/`### Strategic` select the bucket, and any other heading (matched
by the existing `/^#{1,4}\s/` exit check) clears both. Bullets found under Tactical get
`src: 'backlog-tactical'` (score `N+3`, just under `next`), Strategic get `src:
'backlog-strategic'` (score `N+1`, just above `deferred`) — tactical (near-term, actionable)
outranks strategic (longer-range) by design. Italic placeholder lines like `*(empty — ...)*`
are correctly skipped since they don't match the `- `/`* ` bullet regex.

New badges `.task-src-tactical` (blue, reusing `--blue-bg`) and `.task-src-strategic` (a
one-off `#a371f7` purple — no `--purple` CSS variable exists in this file's `:root`, unlike
`--blue`/`--green`/`--amber`/`--red` which do) were added alongside the existing
incomplete/next/planned/deferred badges in `renderTasks()`.

Covered by two new cases in `tests/js/dashboard_helpers.test.mjs` (`deriveTasks` added to
`PURE_HELPERS`) — bucket attribution + score ordering, and that a later heading (even a plain
`##` one, not just `## Backlog` again) correctly stops attributing bullets to the prior bucket.

---

## Data model — key fields in each NS object

| Field | Source | Notes |
|-------|--------|-------|
| `history[]` | last 5 session files | parsed content (planned/completed/incomplete) |
| `sessionDates[]` | all session filenames | full history as `YYYY-MM-DD` strings — use this for time-series viz |
| `sessionCount` | count of all history files | total, not capped |
| `learnings[]` | learnings.jsonl | sorted by weight descending; **active only** (superseded_by=null) |
| `decisions[]` | decisions.jsonl | reverse-chronological |
| `reality` | reality.md | raw markdown string |
| `deferred[]` | state.json `deferred_opportunities` | expanded from dict to array with `key` field |
| `goalByMonth` | state.json `goal_completions` | `{YYYY-MM: avg_rate}` — pre-aggregated by `_goal_by_month()` |
| `explorationRatio` | state.json `goal_completions` | `{ratio, sessionsWithTypes, explore, total, low}` — computed by `_compute_exploration_ratio()`; `null` if fewer than 2 typed sessions |
| `goalTypeBySession` | state.json `goal_completions` | `[{date, exploit, explore}]` chronological — computed by `_goal_type_by_session()`; pre-P23 sessions have `explore:0` |
| `carryForwardTrend` | all history/*.md files | `[{date, carryForward, goalsCompleted}]` — uncapped, chronological; carry-forward = count of `## Incomplete` bullets |
| `lastRealityScore` | state.json `last_reality_score` | previous session's reality completeness %; subtract from current to get delta |
| `zoneDistribution` | active `learnings[]`, computed by `_zone_distribution()` | `{golden, warning, preference, unclassified}` counts — P56; top-level sibling to `corpusHealth`, not nested (meaningful even below `corpusHealth`'s 3-learning gate) |
| `contracts[]` / `contractCoverage` / `criteriaHitRate` | state.json `goal_contracts`, computed by `_parse_goal_contracts()`/`_contract_coverage()` | P55 — see "Verification Contracts" section below |
| `decisionGuidance[]` | `decision_guidance.jsonl` | P65 — see "Contrastive Decision-Guidance Mining" section below; empty in every namespace as of 2026-08-30 (feature shipped compass-core-side very recently, no adoption yet) |

`history` is capped at 5 for rendering (planned/completed detail). `sessionDates` is the
full set and must be used for any time-based visualisation.

**`goal_completions` schema:** values are structs `{hit_rate, total_goals, statuses, ...}`, not arrays. Read `entry["hit_rate"]` directly — do not iterate the dict as if it were a list of status strings.

**Learning object fields (P31+):** each learning in `learnings[]` now carries:
- `learning_id` — stable uuid4 (present on all learnings written after P31 shipped; may be absent on older entries)
- `tags` — normalised to canonical forms via taxonomy.json (P34); use these for tag counting and display
- `superseded_by` — text of the anchor learning if this entry was merged via dream pass; excluded from `learnings[]` by `load_namespace()`
- `superseded_by_id` — `learning_id` of the anchor (parallel to `superseded_by`; present only when anchor had a `learning_id`)

**`active_learnings` filter — P33/P44 status exclusion (fixed 2026-07-22):** `load_namespace()` now filters via `not l.get("superseded_by") and l.get("status") not in ("archived", "superseded")` — the P33 forward-compat gap noted here previously was live: P44 (episodic learning auto-decay) ships in compass's `_monolith.py` and sets `status: "archived"` on stale episodic learnings, and the old filter only excluded `superseded_by`. Lines 370 and 405 in this file already handled both statuses correctly — only the `load_namespace()` filter (formerly ~line 500) was behind.

**Constants sync:** `_COMPLETION_MARKERS`, `_BACKLOG_HEADERS`, `_NON_ACHIEVEMENT_HEADERS`, and
now also `_contract_coverage()` (P55) are local copies/mirrors of compass core logic in
`scripts/compass/reality.py`/`state.py`. They cannot be imported (stdlib-only constraint). If
the compass-core originals change, update this script's copies to match. (`_NON_ACHIEVEMENT_HEADERS`
was dashboard-local-only until 2026-07-18, when the same fix was ported upstream to
`reality.py` — both copies are now in sync, not diverging.)

**2026-08-30 audit found `_COMPLETION_MARKERS`/`_NON_ACHIEVEMENT_HEADERS` had drifted from
real usage, not just from compass core.** `_COMPLETION_MARKERS` only had `✓` (U+2713); every
real reality.md file uses `✅` (U+2705) exclusively, which nearly halved reported completeness
scores in namespaces that only use the emoji (verified: `agentic-loopkit` 25.0% → 53.9% after
the fix). `_NON_ACHIEVEMENT_HEADERS` was also missing three real headers (`blocked`, `known
limitations`, `known doc staleness`) that were wrongly counted toward the denominator. Both
fixed here — **compass core's own `reality.py` has the identical `✓`-only gap** (confirmed by
reading its source), so it likely under-reports completeness for its own dream/review cadence
gating too; that's a compass-core bug, out of scope for this repo, flagged for separate fixing.

**Computed-at-read-time vs persisted fields:** before wiring a new compass field into `load_namespace()`, check whether `compass.py`/`_monolith.py` actually *persists* it in `state.json` or only *computes it fresh when compass's own `read()` runs*. Several fields have turned out to be the latter — `dream_due`, `exploration_ratio` (always stored as `None`), `quality_plateau`/`cadence_pull_forward`, and the `skill_opt` friction-gate annotation. For these, this script must replicate compass's own derivation logic rather than reading a value that "should" be there — grep the compass source for how the field is produced before assuming a plain `state.get("field")` will work.

**The inverse trap — a backlog doc's implementation guess can also be wrong.** The 2026-07-18 data-model-gaps backlog assumed `dream_defer_count` would mirror `code_review_defer_count`/`research_defer_count` as a `*_deferrals.jsonl` file count. It doesn't — `compass/dream.py`'s `cmd_defer_dream` stores it as a plain `state.json` scalar (confirmed 2026-07-26). Backlog write-ups are a starting hypothesis, not a verified spec — grep the actual compass source before implementing an item, even when the doc says "confirm exact filename before wiring."

**Cross-namespace jsonl files drift too, not just per-namespace `state.json`.** `_community/feed.jsonl` changed shape upstream on 2026-07-29 (P40 Phase 2): dedup key moved from `learning_id` alone to `(learning_id, event_type)`, so a `community.learning_retracted` tombstone now survives as its own row alongside the original publish record instead of being dropped as a duplicate. `load_community()` filters retracted rows out of `feed` for exactly this reason — every consumer (Overview "N shared" chips, Learnings tab badges, Community tab health bar/feed list, search index, heatmap diamonds) treats a feed row as "currently shared," and an un-filtered feed would double-count a retracted learning and keep it showing as shared. The lesson generalises: this script watches per-namespace `state.json` shape drift closely (see above) but a shared cross-namespace file like `_community/*.jsonl` can drift the same way and is easy to miss since no single namespace's `read()` output flags it.

---

## Stateful view tabs

View tabs that maintain interactive state (e.g. force simulations, dragged node positions)
must guard full DOM rebuilds with a `rendered` flag on the JS state object:

```js
// On re-activation: resume from current state, don't rebuild
if (_dag.rendered) { /* resume sim */ return; }
// ... full build ...
_dag.rendered = true;
```

Controls that change the underlying data set (toggle, reset) must clear the flag first to
force a rebuild. Calling `innerHTML = ...` on re-activation resets all user adjustments.

---

## DAG force-simulation tuning (2026-07-27)

`dagInitPositions()`/`dagSimStep()` (template.html, `_dag` state object) previously keyed
spring lengths/strengths off an edge type `'depends'` that never occurred — the real type
emitted by `computeAllEdges()`/`EDGE_META` is `'dep'`. This meant the topological layer
seeding and tight dependency springs silently never fired; only the rare `'conflict'` type
got that treatment, which is most of why the graph used to render as one undifferentiated
mesh. Fixed by matching `'dep'` — check both places (init and sim) if retuning again.

Node radius (`n.r`, 18-40px) and opacity (`n.fade`, 1/0.55/0.3) are now computed once per
render in `dagComputeVisualEncoding()` — radius from a min-max-normalised importance score
(weighted degree + capped session count + open bonus), fade from days-since-last-session.
Anything that touches node geometry must read `n.r`, not a hardcoded `28`: the goal-rate dot
offset, session-count text `y`, edge start/end trim in `dagUpdatePositions()`, and the drag
clamp margins in both `dagSimStep()` and `startDagDrag()`'s `onMove` all derive from it now.

**Trap — strengthening `'shared'` (tag-overlap) springs without scaling repulsion collapses
the whole graph into one blob.** In this dataset most namespaces share a "gps" tag, so
`'shared'` edges are near-complete — tightening that spring's `SPRING_K`/`SPRING_LEN` pulls
essentially every node toward every other node. Verified by screenshot: an initial attempt
(`shared` at `k=0.026, len=130`) collapsed ~12 nodes into a ~200x300px clump inside a
900-1800px canvas. Because `REPEL` (repulsion) falls off as `1/d²` while an unclamped spring
force grows linearly with distance, long-distance spring pairs dominate once the canvas is
larger than the constant was tuned for. Fixed with three changes, all needed together:
`shared` de-tuned to a milder `k=0.020, len=150`; spring force clamped to `±MAX_SPRING_F`
(40) so no single edge can pull harder than repulsion can resist at any distance; and
`REPEL` scaled by `(svgW*svgH)/(900*530)` so it keeps pace with the now-dynamic canvas size
(`900+n*40` wide, `530+n*28` tall, clamped `[900,1800]x[530,1200]`). If you change canvas
scaling again, re-verify visually — a graph that looks fine at the default node count can
still collapse when `showSystem` roughly doubles node count.

---

## Mind Map view (2026-07-27 — rotation + overlay detail panel)

The radial layout (`mmLayout`/`mmDraw`) seeds every top-level branch starting at angle 0
(12 o'clock) and lays siblings out clockwise. Branches that land near the bottom of the
circle (SW/SE) get their radial labels rotated to near-vertical — readable only by tilting
your head. `_mm.rotation` (degrees, in the `_mm` state object) is a global offset added to
every node's angle in `rx()`/`ry()` and to the label's `rotate()` transform, so the whole
compass can be spun until the awkward branch lands somewhere closer to horizontal (E/W).
Wired to `⟲`/`⟳` toolbar buttons (`mmRotate(deg)`, ±30° per click) and reset by
`mmResetView()` alongside pan/zoom. Unlike `_mm.pan`, rotation is **not** reset by
`mmSelectNs()` (namespace switch) — it's a viewing preference, not per-namespace state.

**`mm-detail` is an absolutely-positioned overlay on top of `mm-svg`, not a flex sibling.**
It used to be a normal document-flow element above the SVG in a flex column; its content
grows from a one-line tooltip (`min-height: 1.8rem`) to a scrollable 220px list the moment
a group node (e.g. "Decisions (13)") is clicked. Because `mm-svg` was `flex: 1` in the same
column, that growth shrank the SVG's own box on every click — a visible resize/jump — even
though `mmShowNodeDetail()` never touches the SVG or its baked-in pan/zoom `transform`. Fixed
by wrapping both in a `.mm-canvas-wrap` (`position: relative; flex: 1`) with `mm-detail`
absolutely positioned inside it (`top/left/right: 0`, `z-index: 2`, `:empty { display: none }`)
and `mm-svg` at a fixed `width/height: 100%`. The SVG's box is now constant regardless of
detail-panel content — verified via `getBoundingClientRect()` before/during/after opening the
list (564.6px high throughout). Trade-off: the panel now floats over the top rows of the
graph when open, intercepting clicks there — acceptable since it already reads as a readout
docked to the SVG, not a separate panel.

**Don't forget the IIFE export list when adding a new inline-`onclick` handler here** — see
the fourth trap above. `mmRotate` shipped once already forgetting this: clicking the button
did nothing (no console error visible via screenshot, silently swallowed) until
`javascript_tool` was used to call it directly and surface `mmRotate is not defined`. If a
new Mind Map control silently no-ops, check `Object.assign(window, {...})` first.

**Label rotation, per-node (distinct from `_mm.rotation` above).** Drawing radial-tree
labels flat-horizontal at a fixed `(x,y)` causes collisions for depth-2+ siblings clustered
near the top/bottom of the layout, since their `x,y` positions converge even though their
angles differ. `mmDraw()` (`template.html:~3833`) rotates each label by its own node angle
(`angleDeg`), flips it `+180°` and swaps the text anchor in the left hemisphere to keep it
upright, fanning every label along its own radial spoke with no spacing/layout changes
needed. `_mm.rotation` above spins the *whole compass*; this rotates each *label*
independently — the two compose (`angleDeg` already includes `rotOffset`).

**`_mindmap_data(n)` is computed fresh inside `_js_data()`, not cached on the namespace
dict from `load_namespace()`.** Any Python-side annotation of the mind-map tree (e.g.
cross-namespace bridge info, a new node type) must hook into the JS-serialisation step in
`_js_data()`, not the `namespaces` list built earlier in `generate()` — annotating the
latter is silently discarded when `_js_data()` rebuilds the tree from scratch.

---

## Per-namespace Radar chart (2026-08-14)

New `radar` sub-tab in the namespace detail panel (`renderRadar(ns)`, `template.html`) shows
one namespace's health as a configurable radar/spider chart — distinct from the existing
cross-namespace Scorecard tab (parallel coordinates across all namespaces), which is
untouched by this feature.

Ten toggleable axes (`RADAR_AXIS_DEFS`): Scorecard's original 5 (recency, discipline,
maturity, learning, focus — on by default) plus 5 richer per-namespace health signals
(corpus health, exploration ratio, quality trend, cadence pressure, retrieval freshness).
Each axis is normalised to 0–100 independently per namespace via `radarAxisValue(ns, key)` —
unlike Scorecard, there's no cross-namespace min-max normalisation here, since only one
polygon is ever drawn. Axis selection is global (not per-namespace), persisted to
`localStorage['compass-radar-axes']`, enforced at a minimum of 3 active axes.

Null/insufficient-data axes (corpus health needs ≥3 learnings, exploration ratio needs ≥2
typed sessions, quality trend needs ≥1 classified session) render as a dashed/hollow point at
the neutral midpoint (50) rather than being dropped — keeps the polygon shape stable across
namespace switches, with a tooltip explaining why.

`healthColor()` was hoisted out of `renderScorecard()`'s closure to module scope so both
Scorecard and the radar chart can share the same ≥68 green / ≥40 amber / red thresholds —
if retuning those thresholds, only one definition needs to change now.

**Gotcha hit during implementation:** `render_smoke.test.mjs`'s hand-rolled DOM stub doesn't
parse `innerHTML` strings into real child nodes — so a nested element (e.g. `#tab-radar`,
written as part of `renderDetail()`'s single parent-level `innerHTML` assignment) is invisible
to a direct `document.getElementById('tab-radar')` lookup performed afterwards; that lookup
returns a fresh, empty `FakeElement` instead. Only elements whose `innerHTML` is set *directly*
via `getElementById(...).innerHTML = ...` (as `radarToggleAxis()`'s re-render does) are
readable this way. Every existing `switchTab()` sub-tab test already worked around this by
asserting "does it throw" only, not content — the radar tests follow the same pattern, with
content assertions living on the `radarToggleAxis()` re-render test instead.

---

## Cross-namespace Compare radar chart (2026-08-14)

New top-level `compare` view tab (`renderCompare()`, `template.html`) overlays multiple
namespaces as radar polygons on 6 fixed macro axes — distinct from the per-namespace radar's
10 toggleable micro axes. Surface (2) from that feature's own deferred scope, now built on
explicit request.

Six fixed axes (`COMPARE_AXIS_DEFS`): Maturity (reality completeness), Learnings/Decisions/
Signals (raw counts), Long-run discipline (average of `goalByMonth`, distinct from the
per-namespace radar's "Discipline" axis which only reads the latest session's `goalRate`),
and Centrality (weighted dependency degree from `computeAllEdges(true)`, reusing DAG's own
`DEGREE_WEIGHT` map). No axis picker on this view — the 6 axes are fixed by design.

`nsColor(namespace)` was hoisted out of **three** independently-duplicated closures
(`renderDecisionsView()`, `renderArtefactsView()`, and this feature's own first draft) into
one shared function — same palette, same `NS`-array-position indexing as before, now with one
definition instead of three to keep in sync.

**Update (2026-08-30):** Compare's own namespace picker (`compareActiveNamespaces()`/
`compareToggleNamespace()`, `localStorage['compass-compare-namespaces']`, top-5-by-urgency
default) was removed and unified into the global namespace filter — see "Global namespace
filter" below. `renderCompare()` now reads `visibleNS()`/`globalVisibleNames()` like every
other affected view; min-max normalisation is still scoped to just the currently visible set,
so toggling the header filter still recalibrates every polygon's shape.

---

## Global namespace filter (2026-08-30)

A persistent header control (`#gfilter`, next to the search trigger) lets the user
select/deselect which namespaces are visible, driving six views at once: Overview,
Priorities, Scorecard, DAG, Heatmap, and Compare (Compare's own picker was retired in favour
of this — see the Compare section above). Distinct from DAG's own `showSystem` toggle
(hardcoded `SYSTEM_NS = {'global', 'compass'}` exclusion) and the per-namespace Radar's axis
picker — this is a user-driven, namespace-*selection* filter, orthogonal to both.

**State:** `globalVisibleNames()` returns a `Set` of visible namespace names, persisted to
`localStorage['compass-global-namespaces']`; absent/invalid storage defaults to *every*
namespace visible (a no-op filter), not a top-N-by-urgency default. `visibleNS()` returns
`NS.filter(...)` against that set. `NS` itself is never mutated — it stays `const`, filtered
copies only.

**Per-view wiring** (all in `template.html`):
- **Overview** has no render function — cards are static HTML baked at generation time
  (`id="card-{i}"`, `compass-dashboard.py`). `refreshOverviewVisibility()` hides/shows
  existing `#card-N` elements by membership, mirroring `initAttentionQueue()`'s existing
  card-lookup-by-`data-idx` technique; it also clears the detail panel if the selected card
  becomes hidden.
- **Priorities**: `computePriorities()`'s `NS.flatMap` became `NS.map((ns,idx)=>({ns,idx}))`
  `.filter(...).flatMap(...)` — **idx must stay an absolute index into `NS`**, not the
  filtered array's own index, because `onclick="selectCard(${idx})"` looks up `NS[idx]`
  directly. `detectSignals()`'s internal `NS.forEach` also gained a visibility check.
- **Scorecard**: `NS.map(...)` → `visibleNS().map(...)`; added an empty-`rows` guard (render
  an empty-state message) since an all-namespaces-hidden selection previously fed
  `Math.min/max` an empty array (`Infinity`/`-Infinity` → `NaN` range).
- **DAG**: node/edge indices are into the *full* `NS` array (`computeAllEdges` is always
  `NS`-index-keyed) — do **not** filter `NS` itself here. `renderDAG()`'s node-building
  `.filter(...)` chain (already pruning by `showSystem`/`SYSTEM_NS`) gained one more
  `.filter(n => globalVisibleNames().has(n.ns.namespace))` link, same as the existing pattern.
- **Heatmap**: each of the 7 sub-panel functions swapped its own `NS` references for
  `visibleNS()` (`renderVelocityPanel`'s locally-scoped `activeNS` kept its name, just gained
  the extra predicate alongside its existing `SYSTEM_NS` check).

**Re-render on filter change** (`globalFilterRerender()`): Priorities and Compare have no
render cache, so they're always just re-invoked. Scorecard/Heatmap-panels/DAG guard a cached
render behind `dataset.rendered`/`_dag.rendered` — for those, `globalFilterRerender()` only
clears-and-re-invokes ones that have **already been visited** (checked via their own guard
flag), leaving never-visited ones alone since they'll read `visibleNS()` fresh the first time
they're shown. This avoids needing to track "which view is currently active."

**UI**: the header button's own `onclick="toggleGlobalFilter()"` opens `#gfilter-panel`, a
checkbox list built by `renderGlobalFilterList()` (styled via the same `.cmp-ns-label`/
`.cmp-swatch` classes Compare's old picker used) plus "All"/"None" quick actions
(`globalSetAllNamespaces(true/false)`). A `document`-level `click` listener closes the panel
on outside-click. `globalToggleNamespace`, `globalSetAllNamespaces`, and `toggleGlobalFilter`
are exported via the `Object.assign(window, {...})` list (the 4th IIFE trap above) —
`compareToggleNamespace` was removed from that list since the function no longer exists.

---

## Verification Contracts, Decision Guidance & Zone distribution (2026-08-30)

A gap audit found compass core had shipped P59 through P76 since this dashboard's last
documented sync point (P58) — see `~/.claude/skills/compass/docs/roadmap-status.md` for the
authoritative shipped-feature index if auditing again. Three of those subsystems were wired
in this pass; several others (Contrastive Decision-Guidance's sibling P64 Gain-Gated Learning
Promotion, P59 confidence calibration, P69 skill-feedback failure-dimension grouping, etc.)
remain open gaps for a future session.

**Verification Contracts (P55)** — `state.json["goal_contracts"]` (`{goal_hash: {goal_text,
criteria, evidence_type, stopping_condition, created_at, verified_at, verified_criteria,
unmet_criteria}}`) was populated by compass core (confirmed live: `compass` namespace has 7
logged contracts) but never read by this dashboard. `_parse_goal_contracts(state)`
(`compass-dashboard.py`, near `_goal_outcomes_breakdown`) flattens it into `ns.contracts[]`,
merging compass core's separate `criteria`/`verified_criteria`/`unmet_criteria` arrays into a
single ordered `criteria: [{text, met}]` list — this is a deliberate reshape (not a 1:1 mirror
of state.json's shape) done to preserve the goal's authored criteria order for rendering,
avoiding the need to interleave two lists client-side. `_contract_coverage(state, window=20)`
mirrors compass core's `state.py::_compute_contract_coverage()` exactly (verified: running it
against real `compass` namespace data produces `{'contract_coverage': 1.0, 'criteria_hit_rate':
1.0}`, matching compass core's own output) — gated on ≥5 total logged contracts, else both
stats are `None` (rendered as "not enough verified goals yet", the same null-means-below-
threshold idiom used elsewhere for `outcomeRate`). `criteria_hit_rate` on an individual
contract is `None` until that contract has actually been verified (not `0.0`) — a pending
contract hasn't been evaluated yet, and `0.0` would misleadingly read as "failed evaluation."
Rendered by `renderStateSection_GoalContracts(ns)` in `template.html`, following
`renderStateSection_GoalOutcomes`'s exact precedent (empty-array early-return, so a namespace
below the 5-contract gate — before it, this section didn't exist at all — renders no
differently than before this feature shipped).

**Contrastive Decision-Guidance Mining (P65)** — new per-namespace `decision_guidance.jsonl`
(compass core: `cmd_log_decision_guidance`/`cmd_query_decision_guidance` in `_monolith.py`).
**Zero live namespaces have this file as of 2026-08-30** — it's a write-only-so-far feature
that shipped in compass core very recently. `load_namespace()` reads it like any other
per-namespace jsonl (`_read_jsonl` already returns `[]` gracefully when absent), filtering
out `status == "retired"` entries at read time — mirrors compass core's own query filter and
this file's existing `_community/feed.jsonl` retraction-filtering precedent (see "Cross-
namespace jsonl files drift too" above). `_js_data()` reshapes the snake_case persisted
fields to camelCase (`ns.decisionGuidance[]`: `guidanceId`, `contextSummary`,
`preferredDecisionText`, `avoidedDecisionText`, `evidence`, `qualityDelta` — the last is
computed convenience, `preferred_quality - avoided_quality` from the `evidence` dict, `null`
if either is missing — and `createdAt`). Rendered by `renderDecisionGuidance(ns)` inside
`renderDecisions(ns)` in `template.html` (not a new sub-tab — it lives where decisions already
provide context), as a "preferred ✓ / avoided ✗ (struck through)" card with a `qualityDelta`
badge. Returns `''` when empty, so every live namespace's Decisions tab is currently
byte-identical to before this feature shipped — **when real guidance data eventually exists,
re-verify the visual treatment against it**, since everything here was designed against
compass core's persisted-record shape with no real example to check the rendering against.
A 3-line discoverability breadcrumb ("`N guidance pairs mined`") was added to the global
cross-namespace Decisions view header, pointing at the per-namespace tabs — deliberately not a
second full UI for a feature with no live adoption yet.

**Zone distribution (P56 aggregate)** — per-learning `zone` (`golden`/`warning`/`preference`)
already flowed through to JS and rendered as a per-row badge before this pass (confirmed via
`grep -a`, not plain `grep` — see the fifth IIFE trap above); only a namespace-level summary
was missing. `_zone_distribution(learnings)` (`compass-dashboard.py`, near `_corpus_health`)
counts active learnings into `ns.zoneDistribution = {golden, warning, preference,
unclassified}` — any missing/unrecognised zone value counts as `unclassified`, so counts
always sum to `len(learnings)`. Kept as a **top-level** field, not nested under
`corpusHealth`, because `corpusHealth` returns `null` below 3 active learnings while a zone
count is meaningful even at 1–2. `renderZoneDistribution(ns, tableId, nsId)` in
`template.html` renders it as clickable chips at the top of the Learnings sub-tab (reusing
`.zone-preference`'s existing `rgba(139,148,158,.12)` colour formula for the "unclassified"
chip rather than inventing a new one — no `--purple` CSS variable exists in this file, see the
Tasks sub-tab section above). Click-to-filter required generalising the pre-existing
`filterLearningType(tableId, nsId, type)` into a shared `applyLearningFilters(table, nsId)`
that composes **both** an active type filter (`table.dataset.activeType`) and an active zone
filter (`table.dataset.activeZone`) against each row's `data-ltype`/`data-zone` attributes —
implementing zone filtering as a second independent function that also touched
`row.style.display` directly would have let one filter clobber the other's hidden rows.
`filterLearningZone` is a click-to-toggle (clicking the same active zone chip again clears the
filter) and **is** in the `Object.assign(window, {...})` export list (invoked via inline
`onclick`, per the fourth IIFE trap above) — `applyLearningFilters` is internal-only, never
called from HTML, and correctly is not exported.

**Quality-score component breakdown — smaller than it first looked.** `quality_history[]`
entries have carried `components: {goal_completion_rate, outcome_rate, learnings_density,
reality_freshness}` and `weakest_component` since P51 (compass core's `_compute_quality_score()`
spreads `**qs` into every `state.json["quality_history"]` entry at close time) — and
`load_namespace()`/`_js_data()` already passed the whole list through raw. `weakest_component`
was already rendered as a chip. The only missing piece was a per-component visual breakdown,
added as a collapsed `<details>/<summary>` block (mirroring `renderDecayTimeline()`'s existing
pattern — native `<details>` needs no `onclick`, so no `Object.assign` change) inside
`_renderQualityScoreSparklines()`, with the `weakest_component` bar visually distinguished
(amber vs. blue fill). **Lesson: before scoping a "data layer + UI" task, check whether the
data layer is already fully wired** — grepping `_js_data()`/`template.html` for the field name
first would have caught this in minutes instead of designing backend work that turned out to
be unnecessary.

Test fixture (`tests/js/fixtures/generate_fixture.py`) gained: a third learning with
`zone: "warning"` (the first two already had `golden` and no-zone, so all three
`zoneDistribution` buckets are now exercised), a populated `goal_contracts`/`decision_guidance`
example on `example-ns-one` and an empty/below-gate one on `example-ns-two` (exercising both
branches), and non-empty `quality_history[].components`/`weakest_component` on the latest
session. `tests/js/render_smoke.test.mjs`'s new tests for these features are "does it throw"
only, not content assertions — confirmed by testing that `filterLearningZone`'s
`table.querySelectorAll('tbody tr')` returns `[]` against this DOM stub for the same reason
documented in the Radar chart section above (nested `innerHTML` isn't parsed into real child
nodes); the feature was instead verified by hand against a real browser render of live data.

---

## Security

Use `esc(str)` (already defined in the JS) for any user-controlled string going into
`innerHTML`. Namespace names, learning text, decision text, and tooltip strings all
count as user-controlled.

---

## Libraries

- **None** — no D3, no Recharts, no Chart.js. The DAG force simulation
  (`dagInitPositions()`/`dagSimStep()`) and the mind map's radial tree layout are
  both hand-rolled vanilla JS, not D3 — despite this doc previously claiming D3 was
  loaded for the DAG tab (corrected 2026-08-07; no such load ever existed in
  `template.html`, confirmed by `grep -a "d3\."` returning zero hits outside comments
  explicitly noting "no D3 dependency"/"no D3 needed"). Hand-rolled CSS/SVG/vanilla JS
  throughout — the file must remain self-contained and fast to open locally.

---

## Module map

**Tests (`tests/`):**

| File | What it covers |
|------|----------------|
| `test_data_loading.py` | 101 unit tests for `_reality_completeness`, `_corpus_health`, `_goal_stats`, `_stale_bullet_count`, `_retrieval_stale_texts` (P58), `_normalize_confidence`, `_zone_distribution` (P56), `_contract_coverage`/`_parse_goal_contracts` (P55), and more — no filesystem deps (plus a small number of tempdir-based `load_namespace()` tests, e.g. P65 decision-guidance filtering) |
| `test_generate.py` | 71 smoke tests for `generate()` — structural markers, `const NS = [` embedding, script-tag injection escaping, community/mindmap/P51-P53/P55/P56/P58/P65 wiring |
| `js/dashboard_helpers.test.mjs` | Node-native (`node --test`, no deps) smoke tests for pure JS helpers in `template.html` — `esc`, `fmtYM`, `_daysSince`, `urgencyScore`, `scoreItem`, `scaleLinear`, `renderYAxisGridlines`. Extracts function source directly from the file text (brace-matched) since the script is wrapped in an IIFE with no module exports — see `extractFunction()` for the brace-matching approach and its default-parameter gotcha. Run: `node --test tests/js/dashboard_helpers.test.mjs` |
| `js/render_smoke.test.mjs` | Node-native (`node --test`, no deps — hand-rolled DOM stub, not jsdom) smoke tests for the ~46 `render*` functions that touch `document`/`window` and so can't be extracted in isolation like the pure helpers above. Runs the *entire* `<script>` IIFE in a `node:vm` sandbox against `js/fixtures/dashboard_fixture.json` (synthetic data only — regenerate via `python3 tests/js/fixtures/generate_fixture.py`, which builds it from the real `load_namespace()`/`_js_data()` field shapes so it can't drift from production shape), then calls `switchView()` for all 10 tabs, `selectCard()`+`switchTab()` for the detail panel, and the mind-map/search/DAG-resume entrypoints — asserting only "does it throw," not output content. This is exactly the safety net CLAUDE.md's four documented `<script>`-IIFE traps call for: it would have caught the historical `mmRotate is not defined` regression and would catch a broken template-literal quote before a `javascript_tool` debugging session is needed. Run: `node --test tests/js/render_smoke.test.mjs` |

Run: `python3 -m pytest tests/ -q` from the repo root.

**New `_js_data()` fields must use `n.get("field")`, never `n["field"]`:** `test_generate.py` builds fixture NS dicts directly (not via `load_namespace()`), so a fixture won't have every key the real Python data layer populates. Bracket-indexing a new field in `_js_data()` throws `KeyError` against every fixture-based test the moment the field is added, even though `load_namespace()` itself always sets it. Confirmed 2026-07-22 adding `outcomeRate`/`qualityPlateau`/`cadencePullForward`/`skillOptFrictionGate` — all four needed `.get()` to pass the existing suite.

**Testing rendered HTML: assert on content, not CSS class names.** A test asserting on a CSS class name (e.g. `"shared-badge"`) will pass even if that class is only ever declared in the `<style>` block and never actually applied to an element — the class name string appears in the generated HTML either way. Assert on the rendered element content instead (e.g. `"1 shared</span>"`), which only appears if the element actually renders.

**`docs/backlog/`:** scoped, unshipped feature/fix write-ups produced by data-model audits or similar review passes — each entry has implementation breadcrumbs and an effort estimate so a future session can pick one up without re-deriving context. Not auto-discovered by any script; linked from reality.md's "Skill enhancement backlog" section when added.
