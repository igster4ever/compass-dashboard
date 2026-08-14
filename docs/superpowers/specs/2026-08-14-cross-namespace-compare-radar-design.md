# Cross-namespace "Compare" radar chart — design

Status: approved (2026-08-14)

## Problem

The per-namespace radar chart (shipped earlier this session) covers surface (1) — one
namespace's health in the round. There is still no way to compare multiple namespaces'
macro-level posture side by side as overlaid shapes; Scorecard's parallel-coordinates view
does cross-namespace comparison but was explicitly left untouched (see the per-namespace
radar's own design spec, "Out of scope") pending a separate request for this exact surface.
That request has now landed.

## Scope

In scope: a new top-level view tab, **"Compare"**, showing multiple namespaces as overlaid
radar polygons on 6 fixed macro-level axes, with a namespace on/off toggle that recalibrates
the normalisation live.

Out of scope: axis configurability on this view (the per-namespace radar's toggle-able axis
pool does not apply here — Compare's 6 axes are fixed, deliberately macro rather than micro).
No changes to Scorecard or the per-namespace radar.

## Architecture

Pure frontend addition — no Python/data-model changes. All 6 macro axes read fields already
present on `NS` (`realityCompletenessScore`, `learnings`, `decisions`, `externalSignals`,
`goalByMonth`), plus a namespace-relationship graph from the already-shared, stateless
`computeAllEdges()` function (used today by the DAG tab) for the centrality axis. Calling
`computeAllEdges(true)` from Compare has no ordering dependency on the DAG tab ever having
been opened — the function operates directly on the global `NS` array.

- New view tab `compare` (`view-compare`/`vtab-compare`), added to `switchView()`'s tab array
  alongside the existing 10 (`overview, priorities, scorecard, dag, heatmap, timeline,
  decisions, artefacts, mindmap, community`) — becomes 11.
- New `renderCompare()` function, dispatched from `switchView()`'s
  `if (v === 'compare') renderCompare();`.
- **Targeted refactor**: the namespace→colour palette currently duplicated as a local closure
  inside `renderDecisionsView()` (`nsBadgeColour`, an 8-colour palette indexed by position in
  the `NS` array) is hoisted to a shared module-level `nsColor(namespace)` function, placed
  next to `healthColor()`. Both Decisions' namespace badges and Compare's polygons then use
  the identical mapping — the same namespace gets the same colour everywhere in the dashboard.
  This is the second use site for that exact logic, the right moment to extract per this
  namespace's own corpus learning ("extract the normaliser at first duplication, not third").
- No `rendered`-flag guard (unlike Scorecard/DAG) — Compare has no expensive simulation or
  drag state to preserve, so `renderCompare()` always fully rebuilds its own content. It is
  called both from `switchView('compare')` and directly from the namespace-toggle handler,
  mirroring the per-namespace radar's `radarToggleAxis()` re-render pattern exactly.
- Any control using inline `onclick`/`onchange` (the namespace checkboxes) must be added to
  the `Object.assign(window, {...})` IIFE export list — per CLAUDE.md's fourth documented
  `<script>`-IIFE trap.

## Macro axes, default selection, normalisation

Six fixed axes — deliberately macro (project-level posture), distinct from the per-namespace
radar's micro/session-behavioural axes:

| Axis | Raw formula | Fallback |
|---|---|---|
| Maturity | `ns.realityCompletenessScore` | null → raw 50, `fallback: true` |
| Learnings | `(ns.learnings \|\| []).length` | always defined (0 if empty) |
| Decisions | `(ns.decisions \|\| []).length` | always defined (0 if empty) |
| Signals | `(ns.externalSignals \|\| []).length` | always defined (0 if empty) |
| Long-run discipline | `avg(Object.values(ns.goalByMonth \|\| {}))` | empty → raw 50, `fallback: true` |
| DAG centrality | weighted-degree from `computeAllEdges(true)`, same `DEGREE_WEIGHT` map DAG uses (`dep`/`blocking`: 3, `conflict`: 2, `shared`/`concurrent`: 1) | always defined (0 if no edges) |

"Long-run discipline" is deliberately distinct from the per-namespace radar's "Discipline"
axis — that one reads `ns.goalRate`, which is only the **latest session's** hit rate
(`_goal_stats()` in `compass-dashboard.py`); this one averages `goalByMonth`, an existing
pre-aggregated field, giving a genuine lifetime average with no new Python field needed.

Centrality is computed once over the **full** namespace graph — independent of which
namespaces are toggled on, since dependency importance is an intrinsic relationship property
— then min-max normalised, like every other axis, **only across the currently active
namespace set**. This is what makes the polygons visibly recalibrate on toggle: toggling
changes the comparison set, so relative shapes shift, exactly as requested.

**Default selection**: top 5 namespaces by `urgencyScore(ns)` — the existing pure function
Priorities already uses (reused directly, not duplicated). This naturally deprioritises
`global`/`compass` without a special case, since their session/deferred/goal-rate profile
tends to score low on urgency already.

Fallback cells (Maturity/Long-run discipline when data is missing) render as a dashed/hollow
marker at the neutral midpoint on the **raw** scale (50), fed through the same min-max
transform as every other namespace so it stays comparable rather than being dropped — same
convention as the per-namespace radar's null handling.

## Interaction, rendering, testing

**Namespace picker**: a checkbox row above the SVG, one per namespace (all 12, alphabetical),
each swatched with its `nsColor()`. No structural minimum, but **0 active namespaces** shows
an empty-state message ("select at least 1 namespace to compare") instead of a degenerate
SVG.

Toggle state persists to `localStorage['compass-compare-namespaces']` — a separate key from
the per-namespace radar's `compass-radar-axes`, independent persistence.

**Rendering**: same hand-rolled SVG radar mechanics as the per-namespace radar (6 axes spaced
evenly around a circle, concentric gridline rings, one `<polygon>` per active namespace) —
differences:
- No `healthColor()` — each polygon is stroked/filled in its own `nsColor()`, at a lower
  fill-opacity than the per-namespace radar (`0.12` vs `0.22`) so overlapping polygons stay
  legible with several namespaces active.
- A legend row under the picker maps each visible colour swatch to its namespace name —
  redundant with the checkbox labels' own swatches, but useful once several namespaces are
  toggled on and the reader is following the polygon shapes rather than the checkbox list.
- Axis labels are the 6 fixed macro-axis names; no per-axis tooltip picker, since axes are not
  user-configurable on this view (unlike the per-namespace radar's axis pool).

**Testing**:
- `render_smoke.test.mjs`: add `'compare'` to the `switchView()` all-tabs doesNotThrow test
  (10 → 11 tabs); add a namespace-toggle-and-rerender test mirroring the existing
  `radarToggleAxis()` persistence tests.
- `dashboard_helpers.test.mjs`: add a pure `compareAxisValue(ns, key)` helper (mirroring
  `radarAxisValue`'s shape: `{ value, fallback }`) with one unit test per axis; add tests for
  the hoisted `nsColor()` (stable per-namespace mapping, palette wraps past 8 namespaces).
- `test_generate.py`: not expected to need changes — this is a JS-only feature touching no
  `[[PLACEHOLDER]]` markers or Python fields, same as the per-namespace radar. Confirm this
  holds once implementation starts; add a test only if it turns out otherwise.

## Non-goals

- No changes to Scorecard or the per-namespace radar's own axes/behaviour.
- No new Python data-model fields — every axis formula reads fields that already exist on
  `NS`, or derives from the existing `computeAllEdges()` function.
- No axis configurability on this view — the 6 macro axes are fixed by design, to keep this
  view's comparison basis stable and distinct from the per-namespace radar's user-tunable
  micro axes.
