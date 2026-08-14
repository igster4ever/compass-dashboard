# Per-namespace radar chart — design

Status: approved (2026-08-14)

## Problem

Scorecard (`renderScorecard()`, view tab `scorecard`) already gives a cross-namespace
comparison of 5 fitness axes via parallel coordinates. There is no equivalent view for
looking at a *single* namespace's health shape in the round, and no way to bring in the
richer per-namespace health signals already computed in the data layer (corpus health,
exploration ratio, quality trend, cadence pressure, retrieval freshness) without cluttering
Scorecard's cross-namespace comparison.

## Scope

In scope: a new configurable radar (spider) chart for **one namespace at a time**, added as
a sub-tab of the namespace detail panel.

Out of scope (explicitly deferred): converting or extending the existing cross-namespace
Scorecard view to also use radar/overlaid-polygon rendering. That view keeps its current
parallel-coordinates form. Revisit only if this per-namespace radar proves valuable and a
cross-namespace radar overlay is separately requested.

## Architecture

Pure frontend addition — no Python/data-model changes. Every candidate axis metric already
exists on the `NS` object per CLAUDE.md's data model table (`corpusHealth.score`,
`explorationRatio.ratio`, `qualityDist`, `researchDue`/`codeReviewDue`/`dreamDue`,
`retrievalStaleCount`, plus Scorecard's existing 5 raw inputs).

- New sub-tab `radar` added to the namespace detail panel's `.tab-btn` / `switchTab(t)`
  system, alongside `state` / `learnings` / `decisions` / `history` / `tasks`.
- New `renderRadar(ns)` function in `template.html`, invoked from `switchTab('radar')` the
  same way `renderStateSection_*` functions are invoked from `state`.
- Axis selection is **global** (one `Set` of active axis keys), persisted to
  `localStorage['compass-radar-axes']`, read on first render and applied regardless of
  which namespace is currently selected.
- Any control using inline `onclick` (the axis checkboxes) must be added to the
  `Object.assign(window, {...})` IIFE export list — per CLAUDE.md's fourth documented
  `<script>`-IIFE trap. `renderRadar` itself does not need exporting (only called from
  `switchTab`, itself already in scope inside the IIFE).

## Axis pool & formulas

Ten candidate axes, each independently normalised to 0–100 per namespace (no cross-namespace
min-max — unlike Scorecard, only one polygon is drawn here, so relative normalisation across
`NS` would be meaningless). Default-on axes (✅) are Scorecard's existing 5, so the chart's
first-view shape is familiar to anyone who already reads Scorecard.

| Axis | Formula | Null handling |
|---|---|---|
| ✅ Recency | `100 - daysSinceLastSession * (100/30)`, clamped 0–100 | always computable |
| ✅ Discipline | `ns.goalRate ?? 50` | defaults to 50, same as Scorecard |
| ✅ Maturity | `ns.realityCompletenessScore ?? 50` | defaults to 50 |
| ✅ Learning | `min(100, (learnings.length / sessionCount) / 2 * 100)` (cap: 2 learnings/session = 100%) | 0 if `sessionCount` is 0 |
| ✅ Focus | `(1 / (1 + deferred.length)) * 100` | always computable |
| Corpus health | `ns.corpusHealth?.score ?? 50` | dashed/hollow point + tooltip "insufficient data (< 3 learnings)" when `corpusHealth` is null |
| Exploration ratio | `(ns.explorationRatio?.ratio ?? 0.5) * 100` | dashed/hollow + tooltip "insufficient data (< 2 typed sessions)" when null |
| Quality trend | `qualityDist.high / (high+neutral+poor) * 100` | 50 if no sessions classified yet (denominator 0) |
| Cadence pressure (inverted) | `100 - (countTrueOf([reviewDue, researchDue, dreamDue]) / 3 * 100)` | always computable (booleans always present) |
| Retrieval freshness (inverted) | `100 - min(100, retrievalStaleCount * 10)` (every 10 stale-surfacing learnings drops 100pts) | 0 stale → 100, field absent → treated as 0 stale |

Null-data axes render as a **dashed/hollow point at the neutral midpoint (50)** rather than
being silently dropped — keeps the polygon shape stable when switching namespaces, and the
tooltip explains why. This mirrors Scorecard's existing `?? 50` fallback convention rather
than inventing a new one.

## Interaction, persistence & rendering mechanics

**Axis picker:** a checkbox row above the SVG, e.g.:

```
⚙ Axes: ☑ Recency ☑ Discipline ☑ Maturity ☑ Learning ☑ Focus
        ☐ Corpus health ☐ Exploration ratio ☐ Quality trend
        ☐ Cadence pressure ☐ Retrieval freshness
```

Minimum enforced at **3 active axes** — unchecking below 3 is blocked with a brief inline
message ("at least 3 axes needed"), since a radar needs ≥3 points to read as a shape. No
maximum; all 10 may be active at once.

On any toggle: recompute the active axis list, write it to
`localStorage['compass-radar-axes']`, and redraw. This is a namespace-detail sub-tab, not a
stateful full-page view like DAG or Mind Map — there's no simulation state or dragged
positions to preserve — so a full rebuild on every toggle is correct and no `rendered` guard
is needed (CLAUDE.md's "stateful view tabs" guidance does not apply here).

**Rendering:** hand-rolled SVG, no libraries (per CLAUDE.md's library constraint — no D3, no
charting libs, self-contained file) — consistent with the DAG and Mind Map's existing
approach:

- N axes spaced evenly around a circle: `angle = i * 2π/N - π/2` (axis 0 points up), the same
  trick used by Mind Map's radial layout.
- Concentric gridline rings at 25/50/75/100%, reusing the visual language of
  `renderYAxisGridlines` where practical.
- One filled `<polygon>` connecting each axis's normalised value, coloured using the same
  ≥68 green / ≥40 amber / red thresholds as Scorecard's `healthColor()`. That function is
  currently declared *inside* `renderScorecard()`'s closure, not shared module-level like
  `scaleLinear`/`renderYAxisGridlines` — it must be hoisted out to top-level IIFE scope (or
  simply duplicated, if hoisting risks an unrelated Scorecard regression) so `renderRadar()`
  can call it too. Colour is computed as the mean across only the *currently active* axes —
  so it recalibrates live as axes are toggled.
- Axis labels at the outer ring, passed through `esc()` per the existing security
  convention; each label's `<title>` carries the metric's description from the table above.
- Dashed/hollow marker style for null-fallback points as described above.

**Testing:** extend `tests/js/render_smoke.test.mjs` to call the new radar render path for at
least one namespace with the default axis set (catches the string-literal/IIFE-export traps
CLAUDE.md warns about — this is exactly the safety net that test file exists for).
`tests/test_generate.py` is not expected to need changes, since this feature is JS-only and
touches no `[[PLACEHOLDER]]` markers or Python data fields — confirm this holds once
implementation starts, and add a test only if it turns out otherwise.

## Non-goals

- No changes to the cross-namespace Scorecard view.
- No new Python data-model fields — every axis formula above reads fields that already exist
  on `NS` per CLAUDE.md's data model table.
- No per-namespace axis-selection memory — selection is global by design (see brainstorming
  transcript: explicitly chosen over per-namespace memory for consistent comparison).
