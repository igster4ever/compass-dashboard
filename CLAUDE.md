# Compass Dashboard — CLAUDE.md

Current conventions only. Dated fix histories, incident narratives and design rationale live in
[`docs/claude-md-history.md`](docs/claude-md-history.md) (verbatim, append-only) — read an entry
there when you need the *why* behind a rule here.

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

## Keeping this file lean

This file loads on every turn, so it holds rules, not stories. **Budget: 20KB**
(`tests/test_claude_md_budget.py` fails above it).

- **When adding a fix or feature note:** state the resulting rule here in one or two sentences.
  Put the narrative (what broke, how it was found, before/after numbers) in
  `docs/claude-md-history.md` under a new `## <YYYY-MM-DD> archival pass` section. Never rewrite
  or delete older sections of that file.
- **Periodic hygiene pass:** compass core's CLAUDE.md review
  (`~/.claude/skills/compass/scripts/prompts/claude-md-hygiene-review.md`) fires for this
  namespace every 15 sessions, or early once this file is over budget. When it fires — or when
  the budget test fails — run it: correct stale facts against the code, archive dated narratives
  verbatim with `~/.claude/skills/compass/scripts/archive_claude_md.py` (`--list` for the size
  table; it refuses to write unless nothing was lost), then
  `python3 ~/.claude/skills/compass/scripts/compass.py record-claude-review compass-dashboard`.
- **Things that go stale fastest:** line counts, test counts, "authoritative list" copies of
  arrays in `template.html`. Prefer pointing at the code over copying it.

---

## Architecture

```
scripts/
├── compass-dashboard.py   — data layer + generate() + main()
│   ├── load_namespace()    — thin composition: _read_namespace_files() -> _assemble_namespace_dict()
│   │   ├── _read_namespace_files()    — file-reading/parsing phase (I/O only, no derived fields)
│   │   └── _assemble_namespace_dict() — derived/computed fields + final return dict
│   ├── _js_data()          — serialises NS array as JSON embedded in HTML (camelCase rename table)
│   └── generate()          — reads template.html, injects [[PLACEHOLDER]] markers
└── template.html           — HTML + <style> + <script>
    └── JS                  — all interactivity; operates on const NS = [...]
```

All data is baked into `const NS = [...]` at generation time. There is no runtime backend
and there never will be — static HTML only. Stdlib-only Python; no JS libraries (no D3,
Chart.js etc. — the DAG force simulation and mind-map radial layout are hand-rolled).
*Alternative considered, not adopted:* a `<script type="application/json">` data island
parsed by `render(data)` would remove the JS-literal escaping surface; `const NS` plus
`generate()`'s `</script>` escaping and `esc()` in `innerHTML` covers it today.

---

## `template.html` traps

Several of these fail as a silent parse error: the whole `<script>` block dies and every
function becomes undefined (`ReferenceError: switchView is not defined`). Run
`node --test tests/js/render_smoke.test.mjs` after any `template.html` edit — it catches them.

1. **Single quotes in inline `onclick` inside a `'...'` string literal** break the outer string.
   Use a template literal (backticks) for any `innerHTML` containing `onclick="fn('arg')"`.
2. **The script is an IIFE.** Any function called from an inline `onclick`/`oninput`/`onkeydown`
   attribute must be listed in `Object.assign(window, {...})` just before `})();`, or it throws
   `ReferenceError` (or silently no-ops). Exception: `decSort`/`decExpand` self-assign to
   `window` inside `renderDecisionsView()` — don't add them to the list. Internal-only helpers
   (never called from HTML) stay out of it.
3. **`\xa0` non-breaking spaces** sit inside some template literals. If an Edit reports "string
   not found" on a line you can see, check with
   `python3 -c "lines=open('scripts/template.html').readlines(); [print(repr(l)) for l in lines[N-1:N+2]]"`
   and do the replacement via Python `str.replace()`.
4. **Always `grep -a` (or `rg -a`) this file.** Plain grep treats it as binary and silently
   under-reports matches — "no hits" is not proof of absence.
5. **Native `<details>/<summary>`** needs no `window` export. An element inside a *closed*
   `<details>` has no layout box, so open its ancestors before `scrollIntoView()` or filtering
   (see `navigateToResult()`).
6. **Scroll anchoring is off page-wide** (`html, body { overflow-anchor: none }`). With it on,
   opening a drawer while scrolled to the bottom made the clicked summary jump up by the
   drawer's height (Chrome anchored on the footer). Don't scope it back down to `#detail`.

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

**Top-level view tabs** (`.view-tab`, `switchView(v)`) — full-page views. The `forEach` array in
`switchView()` is the authoritative list (overview, priorities, scorecard, dag, heatmap,
timeline, decisions, artefacts, mindmap, community, compare). Each view has `id="view-<name>"`
and `id="vtab-<name>"`. Adding one requires: a `<nav>` button, a `<div id="view-<name>">`, the
name in `switchView()`'s `forEach`, an `if (v === '<name>') render<Name>();` branch, and a
`render<Name>()` function.

**Namespace detail sub-tabs** (`.tab-btn`, `switchTab(t)`) — panels within a selected namespace.
`renderDetail()`'s `tabs` array is the authoritative list (`decisions` only when present,
`signals` only when `externalSignals` is non-empty).

Long panels use collapsible `stateGroup(title, headline, bodyHtml)` drawers with a one-line
data-derived headline in the `<summary>`; `stateGroup` renders nothing when its body is empty.

---

## Data model — key fields in each NS object

| Field | Source | Notes |
|-------|--------|-------|
| `history[]` | last 5 session files | parsed content (planned/completed/incomplete) |
| `sessionDates[]` | all session filenames | full history as `YYYY-MM-DD` — use this for time-series viz |
| `sessionCount` | count of all history files | total, not capped |
| `learnings[]` | learnings.jsonl | sorted by weight desc; **active only** (see filter below) |
| `decisions[]` | decisions.jsonl | reverse-chronological |
| `reality` | reality.md | raw markdown string |
| `deferred[]` | state.json `deferred_opportunities` | expanded from dict to array with `key` field |
| `goalByMonth` | state.json `goal_completions` | `{YYYY-MM: avg_rate}` via `_goal_by_month()` |
| `explorationRatio` | state.json `goal_completions` | `{ratio, sessionsWithTypes, explore, total, low}`; `null` below 2 typed sessions |
| `goalTypeBySession` | state.json `goal_completions` | `[{date, exploit, explore}]` chronological |
| `carryForwardTrend` | all history/*.md files | `[{date, carryForward, goalsCompleted}]`; carry-forward = `## Incomplete` bullet count |
| `lastRealityScore` | state.json `last_reality_score` | completeness % written by compass core at close; comparable only because both algorithms are identical |
| `zoneDistribution` | active `learnings[]` | P56 `{golden, warning, preference, unclassified}`; top-level, not under `corpusHealth` |
| `contracts[]` / `contractCoverage` / `criteriaHitRate` | state.json `goal_contracts` | P55; coverage stats `null` below 5 contracts |
| `decisionGuidance[]` | `decision_guidance.jsonl` | P65; `status == "retired"` filtered out |
| `confidenceCalibration` | learnings.jsonl (**unfiltered**) | P59; `null` below 8 resolved hypotheses |
| `failureDimensionDistribution` | `skill_feedback.jsonl` | P69; dashboard-only aggregation |

`history` is capped at 5 for rendering. `sessionDates` is the full set.

**Rules:**
- **`goal_completions` values are structs** `{hit_rate, total_goals, statuses, ...}` — read
  `entry["hit_rate"]`, don't iterate as a list.
- **Learning fields (P31+):** `learning_id` (may be absent on old entries), `tags` (canonical via
  taxonomy.json), `superseded_by`/`superseded_by_id`, `zone`, `status`.
- **Active-learnings filter:** `not l.get("superseded_by") and l.get("status") not in
  ("archived", "superseded")`. Calibration-style stats that count *resolved* data points use the
  unfiltered list instead, matching compass core.
- **Null means below threshold.** Gated stats (`outcomeRate`, `contractCoverage`,
  `confidenceCalibration`, `corpusHealth`) return `None`/`null` below their gate, and a pending
  per-item rate is `None`, not `0.0`. Render "not enough data yet", never zero.
- **Counting distributions always sum to the total:** missing/unrecognised values go to
  `unclassified`.
- **Mirrored compass-core logic:** `_COMPLETION_MARKERS`, `_BACKLOG_HEADERS`,
  `_NON_ACHIEVEMENT_HEADERS`, `_reality_completeness()` (section-aware P22), `_iter_reality_bullets()`,
  `_stale_bullet_count()` (whole-day threshold), `_parse_section_bullets()`,
  `_normalise_validation_entry()`, `_check_reality_compaction_due()`,
  `_compaction_eligible_count()` (steady-state only), `_contract_coverage()`,
  `_compute_confidence_calibration()`, and the cadence gates `_check_dream_due()`,
  `_check_claude_review_due()` (incl. size pull-forward), research/code-review/skill-opt due
  are local copies of `~/.claude/skills/compass/scripts/compass/*.py` (can't import —
  stdlib-only, separate repo). Read thresholds from `config` with core's defaults, never
  hard-code them. `tests/test_core_parity.py` imports core and checks every mirror against it
  on all live namespaces; add a case there whenever you mirror something new.
- **Re-audit against compass core** by running `test_core_parity.py`; a failure means core
  changed, so port the change rather than loosening the test. It can't see *new* core fields,
  so still skim core's git log for new persisted fields now and then. Last manual audit:
  2026-09-30. Don't trust `compass/docs/roadmap-status.md` as the index; it lags the code.
- **Computed-at-read-time fields:** some compass fields are computed fresh in compass's `read()`
  and never persisted (`dream_due`, `exploration_ratio` — stored as `None`,
  `quality_plateau`/`cadence_pull_forward`, the `skill_opt` friction gate,
  `claude_review_status.pulled_forward_by_size`, reality-compaction-due, P78
  contradiction warnings). Grep the compass
  source for how a field is produced before wiring a plain `state.get(...)`; replicate the
  derivation if it isn't persisted.
- **Backlog docs are hypotheses, not specs.** Verify filenames/shapes against compass source
  before implementing (e.g. `dream_defer_count` is a `state.json` scalar, not a jsonl count).
- **Shared cross-namespace files drift too.** `_community/feed.jsonl` dedups on
  `(learning_id, event_type)`; `load_community()` filters `community.learning_retracted` rows so
  every consumer treats a feed row as "currently shared".
- **Check whether data is already wired** (grep `_js_data()` and `template.html -a`) before
  scoping "data layer + UI" work — e.g. `quality_history[].components` already flowed through.

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

## View-specific rules

**DAG** (`_dag`, `dagInitPositions()`/`dagSimStep()`)
- The dependency edge type is `'dep'` (per `EDGE_META`/`computeAllEdges()`), not `'depends'` —
  check init and sim both when retuning.
- Node geometry reads `n.r` (18–40px) and `n.fade`, computed once in
  `dagComputeVisualEncoding()`. Never hardcode a radius.
- `'shared'` (tag-overlap) edges are near-complete in this dataset. Tightening that spring
  collapses the graph into a blob. Keep spring force clamped to `±MAX_SPRING_F` and `REPEL`
  scaled by canvas area; re-verify visually with `showSystem` on after any canvas/spring change.
- Node/edge indices are into the full `NS` array — filter nodes, never `NS` itself.

**Mind Map** (`_mm`, `mmLayout`/`mmDraw`)
- `_mm.rotation` spins the whole compass (`mmRotate(±30)`, reset by `mmResetView()`, *not* by
  `mmSelectNs()`). Per-label rotation along each node's spoke is separate and composes with it.
- `mm-detail` is an absolutely-positioned overlay inside `.mm-canvas-wrap`, so its growth never
  resizes `mm-svg`. Keep it that way.
- `_mindmap_data(n)` is built fresh inside `_js_data()` — annotate the tree there, not on the
  `load_namespace()` dict.

**Radar** (per-namespace sub-tab, `renderRadar(ns)`) — 10 toggleable axes (`RADAR_AXIS_DEFS`),
each normalised 0–100 per namespace, min 3 active, persisted to
`localStorage['compass-radar-axes']`. Insufficient-data axes render hollow at 50, not dropped.
`healthColor()` (≥68 green / ≥40 amber / red) is module-scope and shared with Scorecard.

**Compare** (`renderCompare()`) — 6 fixed macro axes (`COMPARE_AXIS_DEFS`), no axis picker;
min-max normalisation across the currently visible namespaces only. `nsColor(namespace)` is the
single shared palette function — don't re-duplicate it.

**Global namespace filter** (`#gfilter`) — drives Overview, Priorities, Scorecard, DAG, Heatmap,
Compare. `globalVisibleNames()` (Set, `localStorage['compass-global-namespaces']`, default all
visible) and `visibleNS()` (filtered copy — `NS` stays `const`, never mutated).
- Overview cards are static HTML; `refreshOverviewVisibility()` hides/shows `#card-N`.
- Anything emitting `selectCard(${idx})` must use the **absolute** `NS` index, not the filtered
  array's index.
- Guard empty selections (e.g. Scorecard's `Math.min/max` on `[]`).
- `globalFilterRerender()` re-invokes uncached views and only clears+re-renders cached views
  (`dataset.rendered`/`_dag.rendered`) that have already been visited.

**Tasks sub-tab** (`deriveTasks(ns)`, pure JS over `ns.reality`) — reads `## What is next`,
inline `Next session:` lines, `plannedActions`, `deferred`, recent `history[].incomplete`, and
`## Backlog` → `### Tactical` (score N+3) / `### Strategic` (score N+1). Any other heading ends
the backlog bucket. There's no `--purple` CSS variable; Strategic uses a one-off `#a371f7`.

**State sub-tab** (`renderState()`) — always-visible Intent, Active goals and a "Health &
cadence" strip (`.state-health-strip`), then `stateGroup` drawers (Reality, Decisions & backlog,
Goal tracking, Cross-namespace signals, Feedback & failure analysis, Intent history). New
sections go in the matching drawer, not the flat top. The Reality drawer's upkeep lines
(`renderRealityUpkeep()`) show compaction cadence, eligible/archived counts with a `file://`
link to `reality_archive.md`, and verification durability over bullets still in reality.md.

**Learnings sub-tab** — type and zone filters compose through `applyLearningFilters(table,
nsId)` over `data-ltype`/`data-zone`; never set `row.style.display` from a second independent
filter. `filterLearningZone` (click-to-toggle) is exported; `applyLearningFilters` is not.

**Decision Guidance** (P65) — rendered inside the Decisions sub-tab by
`renderDecisionGuidance(ns)`, returns `''` when empty. No live namespace had data as of
2026-08-30; re-verify the visual treatment once real data exists.

---

## Security

Use `esc(str)` (already defined in the JS) for any user-controlled string going into
`innerHTML`. Namespace names, learning text, decision text, and tooltip strings all
count as user-controlled.

---

## Tests

Run `python3 -m pytest tests/ -q` **and** `node --test tests/js/` before calling work done.

| File | What it covers |
|------|----------------|
| `test_data_loading.py` | Pure data-layer helpers (completeness, corpus health, goal stats, zones, contracts, calibration, failure dimensions…) plus a few tempdir `load_namespace()` cases |
| `test_generate.py` | `generate()` smoke tests — structural markers, `const NS = [` embedding, script-tag escaping, feature wiring |
| `test_integration_pipeline.py` | End-to-end: on-disk synthetic namespace → `load_namespace()` → `_js_data()`/`generate()` |
| `test_claude_md_budget.py` | Fails when this file exceeds its 20KB budget |
| `test_core_parity.py` | Imports compass core; asserts every dashboard mirror matches it on all live namespaces (skips when absent) |
| `js/dashboard_helpers.test.mjs` | Pure JS helpers extracted from `template.html` by brace-matching (`extractFunction()` — mind its default-parameter gotcha); add new pure helpers to `PURE_HELPERS` |
| `js/render_smoke.test.mjs` | Runs the whole `<script>` IIFE in `node:vm` against a hand-rolled DOM stub and `js/fixtures/dashboard_fixture.json`; calls every view/sub-tab entrypoint and asserts "does not throw" |

**Testing rules:**
- **Regenerate the JS fixture** with `python3 tests/js/fixtures/generate_fixture.py` — it builds
  from real `load_namespace()`/`_js_data()` shapes. Compute derived expectations by calling the
  real function, not by hand-typing numbers.
- **The DOM stub doesn't parse `innerHTML` into child nodes.** A nested element written by a
  parent's `innerHTML` is invisible to `getElementById`/`querySelectorAll`. Assert content only
  on elements whose `innerHTML` is set directly; otherwise assert "does not throw" and verify by
  hand in a real browser.
- **New `_js_data()` fields use `n.get("field")`, never `n["field"]`** — fixture dicts don't
  carry every key.
- **Assert on rendered content, not CSS class names** — a class name appears in the `<style>`
  block whether or not any element uses it.
- **Verify pipeline refactors by comparing parsed objects:** `json.loads()` the old and new
  `const NS = [...]` and compare for equality. A raw-text diff flags harmless key reordering.

**`docs/backlog/`** — scoped, unshipped write-ups with implementation breadcrumbs and effort
estimates. Not auto-discovered; linked from reality.md's backlog section.
