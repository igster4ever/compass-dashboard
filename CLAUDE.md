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
├── compass-dashboard.py   — data layer + generate() + main()   (~1,098 lines)
│   ├── load_namespace()    — reads state.json, *.md, *.jsonl, history/*.md
│   ├── _js_data()          — serialises NS array as JSON embedded in HTML
│   └── generate()          — reads template.html, injects [[PLACEHOLDER]] markers
└── template.html           — HTML + <style> + <script>          (~3,961 lines)
    └── JS                  — all interactivity; operates on const NS = [...]
```

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

**Top-level view tabs** (`.view-tab`, `switchView(v)`) — full-page views:
- `overview` — card grid + namespace detail panel
- `priorities` — cross-namespace priority signals
- `dag` — force-directed dependency graph
- `heatmap` — session activity heatmap

Each view has `id="view-<name>"` and `id="vtab-<name>"`. Adding a new view tab requires:
1. Button in the `<nav>` HTML
2. `<div id="view-<name>">` in the HTML
3. Name added to the `forEach` array in `switchView()`
4. `if (v === '<name>') render<Name>();` in `switchView()`
5. A `render<Name>()` function

**Namespace detail sub-tabs** (`.tab-btn`, `switchTab(t)`) — panels within a selected namespace:
`state`, `learnings`, `decisions`, `history`, `tasks`

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

`history` is capped at 5 for rendering (planned/completed detail). `sessionDates` is the
full set and must be used for any time-based visualisation.

**`goal_completions` schema:** values are structs `{hit_rate, total_goals, statuses, ...}`, not arrays. Read `entry["hit_rate"]` directly — do not iterate the dict as if it were a list of status strings.

**Learning object fields (P31+):** each learning in `learnings[]` now carries:
- `learning_id` — stable uuid4 (present on all learnings written after P31 shipped; may be absent on older entries)
- `tags` — normalised to canonical forms via taxonomy.json (P34); use these for tag counting and display
- `superseded_by` — text of the anchor learning if this entry was merged via dream pass; excluded from `learnings[]` by `load_namespace()`
- `superseded_by_id` — `learning_id` of the anchor (parallel to `superseded_by`; present only when anchor had a `learning_id`)

**`active_learnings` filter — P33/P44 status exclusion (fixed 2026-07-22):** `load_namespace()` now filters via `not l.get("superseded_by") and l.get("status") not in ("archived", "superseded")` — the P33 forward-compat gap noted here previously was live: P44 (episodic learning auto-decay) ships in compass's `_monolith.py` and sets `status: "archived"` on stale episodic learnings, and the old filter only excluded `superseded_by`. Lines 370 and 405 in this file already handled both statuses correctly — only the `load_namespace()` filter (formerly ~line 500) was behind.

**Constants sync:** `_COMPLETION_MARKERS`, `_BACKLOG_HEADERS`, and `_NON_ACHIEVEMENT_HEADERS` in this script are local copies of the same constants in `scripts/compass/reality.py`. They cannot be imported (stdlib-only constraint). If reality.py's constants change, update this script's copies to match. (`_NON_ACHIEVEMENT_HEADERS` was dashboard-local-only until 2026-07-18, when the same fix was ported upstream to `reality.py` — both copies are now in sync, not diverging.)

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

## Security

Use `esc(str)` (already defined in the JS) for any user-controlled string going into
`innerHTML`. Namespace names, learning text, decision text, and tooltip strings all
count as user-controlled.

---

## Libraries

- **D3** — loaded for the DAG force simulation only. Fine to use D3 utilities (scale,
  layout) in other tabs if genuinely needed.
- **Everything else** — hand-rolled CSS/SVG/vanilla JS. Don't add Recharts, Chart.js,
  or similar. The file must remain self-contained and fast to open locally.

---

## Module map

**`scripts/compass-dashboard.py`** (~1,098 lines — Python only):

| Lines (approx) | What lives there |
|----------------|-----------------|
| 1–95 | Python helpers: file reading, time formatting, history parsing |
| 96–302 | `_corpus_health()`, `_stale_bullet_count()`, `_goal_stats()`, `_goal_by_month()` |
| 303–342 | `_compute_exploration_ratio()`, `_goal_type_by_session()` |
| 343–594 | `load_namespace()`, `discover_namespaces()`, `_card_html()` |
| 595–660 | `_extract_blocking_edges()`, `_js_blocking_edges()` (E24a cross-namespace blocking edges) |
| 661–755 | `_js_data()`, `_js_community()`, `generate()` (reads template.html), `main()`, `__main__` |

**`scripts/template.html`** (~3,961 lines — HTML/CSS/JS):

| Lines (approx) | What lives there |
|----------------|-----------------|
| 1–81 | HTML structure + `[[PLACEHOLDER]]` markers |
| 82–746 | CSS `<style>` block |
| 747–1186 | JS: constants, `esc()`, card rendering, detail panel, tab switching |
| 1187–1242 | JS: `deriveTasks()`, `renderTasks()` |
| 1243–1636 | JS: detail panel sub-tabs — `renderState()` (slim dispatcher) + 10 `renderStateSection_*` helpers, learnings, decisions, history, `renderExternalSignals()` |
| 1637–1831 | JS: `switchView()`, priority scoring helpers, `renderPriorities()` |
| 1832–2282 | JS: search / command palette |
| 2283–2630 | JS: `renderHeatmap()`, `renderSessionHeatmapPanel()`, `renderGoalHeatmapPanel()` |
| 2631–2762 | JS: `renderGoalTypesPanel()` (E18), `renderPlanningPanel()` (E15) |
| 2763–2953 | JS: `renderVelocityPanel()`, `renderLearningTimeline()`, `renderScorecard()` |
| 2954–end | JS: `renderDAG()`, force simulation, DAG tooltip |

**Tests (`tests/`):**

| File | What it covers |
|------|----------------|
| `test_data_loading.py` | 62 unit tests for `_reality_completeness`, `_corpus_health`, `_goal_stats`, `_stale_bullet_count`, `_retrieval_stale_texts` (P58), and more — no filesystem deps |
| `test_generate.py` | 55 smoke tests for `generate()` — structural markers, `const NS = [` embedding, script-tag injection escaping, community/mindmap/P51-P53/P56-P58 wiring |
| `js/dashboard_helpers.test.mjs` | Node-native (`node --test`, no deps) smoke tests for pure JS helpers in `template.html` — `esc`, `fmtYM`, `_daysSince`, `urgencyScore`, `scoreItem`, `scaleLinear`, `renderYAxisGridlines`. Extracts function source directly from the file text (brace-matched) since the script is wrapped in an IIFE with no module exports — see `extractFunction()` for the brace-matching approach and its default-parameter gotcha. Run: `node --test tests/js/dashboard_helpers.test.mjs` |

Run: `python3 -m pytest tests/ -q` from the repo root.

**New `_js_data()` fields must use `n.get("field")`, never `n["field"]`:** `test_generate.py` builds fixture NS dicts directly (not via `load_namespace()`), so a fixture won't have every key the real Python data layer populates. Bracket-indexing a new field in `_js_data()` throws `KeyError` against every fixture-based test the moment the field is added, even though `load_namespace()` itself always sets it. Confirmed 2026-07-22 adding `outcomeRate`/`qualityPlateau`/`cadencePullForward`/`skillOptFrictionGate` — all four needed `.get()` to pass the existing suite.

**`docs/backlog/`:** scoped, unshipped feature/fix write-ups produced by data-model audits or similar review passes — each entry has implementation breadcrumbs and an effort estimate so a future session can pick one up without re-deriving context. Not auto-discovered by any script; linked from reality.md's "Skill enhancement backlog" section when added.
