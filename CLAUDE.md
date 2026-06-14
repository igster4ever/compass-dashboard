# Compass Dashboard — CLAUDE.md

## What this is

A single Python script (`scripts/compass-dashboard.py`) that reads all compass loop
namespaces from `~/.claude/loop/` and generates a self-contained static HTML dashboard.

**Regenerate:**
```bash
python3 scripts/compass-dashboard.py
# Output: ~/Downloads/compass-dashboard.html — open directly in a browser, no server needed
```

---

## Architecture

```
compass-dashboard.py
├── Python top (~330 lines)   — data loading, serialisation, HTML generation
│   ├── load_namespace()       — reads state.json, *.md, *.jsonl, history/*.md
│   ├── _js_data()             — serialises NS array as JSON embedded in HTML
│   └── HTML_TEMPLATE          — the entire HTML/CSS/JS as a Python triple-quoted string
└── JS inside HTML_TEMPLATE    — all interactivity; operates on const NS = [...]
```

All data is baked into `const NS = [...]` at generation time. There is no runtime backend
and there never will be — static HTML only.

---

## Critical gotcha — JS regex/string escaping inside Python strings

The JS lives inside a Python triple-quoted string. Any backslash that needs to reach the
browser as `\` must be written as `\\` in the Python source:

| You want in JS | Write in Python source |
|----------------|------------------------|
| `\n`           | `\\n`                  |
| `\s`, `\d`     | `\\s`, `\\d`           |
| `\.`           | `\\.`                  |
| `×`       | `\\u00d7`              |

Forgetting this produces **silent bugs** — the JS runs but regex patterns silently fail
to match. Always verify new regex patterns render correctly in the generated HTML.

**Second trap — single quotes inside JS string literals with inline `onclick`:**

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
python3 -c "lines = open('scripts/compass-dashboard.py').readlines(); [print(repr(l)) for l in lines[N-1:N+2]]"
```

Fix: use a Python script (`str.replace()`) to do the replacement, passing the `\xa0`
character explicitly in the old string.

---

## Template substitution

HTML_TEMPLATE uses `[[PLACEHOLDER]]` markers replaced by `generate()`:

| Marker | Replaced with |
|--------|---------------|
| `[[NS_DATA]]` | JSON-serialised namespace array |
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
| `learnings[]` | learnings.jsonl | sorted by weight descending |
| `decisions[]` | decisions.jsonl | reverse-chronological |
| `reality` | reality.md | raw markdown string |
| `deferred[]` | state.json `deferred_opportunities` | expanded from dict to array with `key` field |
| `goalByMonth` | state.json `goal_completions` | `{YYYY-MM: avg_rate}` — pre-aggregated by `_goal_by_month()` |

`history` is capped at 5 for rendering (planned/completed detail). `sessionDates` is the
full set and must be used for any time-based visualisation.

**`goal_completions` schema:** values are structs `{hit_rate, total_goals, statuses, ...}`, not arrays. Read `entry["hit_rate"]` directly — do not iterate the dict as if it were a list of status strings.

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

| Lines (approx) | What lives there |
|----------------|-----------------|
| 1–95 | Python helpers: file reading, time formatting, history parsing |
| 96–270 | `_corpus_health()`, `_stale_bullet_count()`, `_goal_stats()`, `_goal_by_month()` |
| 271–420 | `load_namespace()`, `discover_namespaces()` |
| 421–520 | `_js_data()`, `generate()`, `__main__` |
| 521–950 | `HTML_TEMPLATE` — HTML structure + all CSS |
| 951–1080 | JS: constants, `esc()`, card rendering, detail panel, tab switching |
| 1081–1150 | JS: `deriveTasks()`, `renderTasks()` |
| 1151–1420 | JS: detail panel sub-tabs (state, learnings, decisions, history) |
| 1421–1480 | JS: `renderExternalSignals()` |
| 1481–1700 | JS: `switchView()`, priority scoring helpers |
| 1701–2010 | JS: `renderPriorities()`, search / command palette |
| 2011–2440 | JS: `renderHeatmap()`, `renderVelocityPanel()`, `renderSessionHeatmapPanel()` |
| 2441–2640 | JS: `renderLearningTimeline()`, `renderScorecard()` |
| 2641–2980 | JS: `renderGoalHeatmapPanel()`, `renderDAG()`, force simulation, DAG tooltip |
