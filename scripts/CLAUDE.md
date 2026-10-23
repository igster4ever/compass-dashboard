# Compass Dashboard — scripts/ rules

Loads when Claude reads a file in `scripts/`. Root `CLAUDE.md` holds the upkeep rules and budget.

**Before you edit a view's code, read its section in [`docs/claude/views.md`](../docs/claude/views.md).**
It covers `renderDAG()`/`dagInitPositions()`/`dagSimStep()`, `renderMindMap()`/`mmLayout()`/`mmDraw()`,
`renderRadar()`, `renderCompare()`, the global filter (`globalVisibleNames()`/`visibleNS()`/
`globalFilterRerender()`), `renderLiveStrip()`/`_build_pulse()`, `deriveTasks()`, `renderState()`,
`renderLearnings()`/`applyLearningFilters()` and `renderDecisionGuidance()`.

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

7. **`</style>` appears inside JS template literals.** Add CSS before the *2-space-indented*
   `  </style>` closing the main stylesheet, never the first `</style>` string match.

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
  `_check_claude_review_due()` (per-file budget over root + `scripts/CLAUDE.md` via `_claude_md_files()`, shared with the pulse), research/code-review/skill-opt due
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
