# P65 Decision Guidance UI: findings from a synthetic-data check

**Status:** findings 1 and 2 fixed 2026-10-23; findings 3–6 open (tactical backlog candidate).
**Date:** 2026-10-23 · **Source:** compass-dashboard session 2026-10-23 (goal 4)

## Why

`decision_guidance.jsonl` is empty in every live namespace, so the P65 UI was never seen with data.
This check used synthetic data in a real browser.

## Method

- A scratch loop dir held two copies of the `compass-dashboard` namespace: `dg-with-decisions` and
  `dg-no-decisions` (no `decisions.jsonl`). Each got the same `decision_guidance.jsonl`: four active
  rows (positive delta, negative delta, empty `evidence`, HTML/`</script>` injection with long text)
  and one `retired` row. Row shape is from core's `cmd_log_decision_guidance`.
- Generated with `LOOP_DIR` pointed at the scratch dir. Served over `http://` and opened in the
  browser pane.
- A second run added one row with `evidence.preferred_quality: null`.

## What works

- Four cards render; the retired row does not.
- Escaping holds: no `<img>`, `<b>` or `<script>` element is created from the row text.
- Long text wraps. Signed deltas render (`Δ+17%`, `Δ-12%`, `Δ0%`). Empty `evidence` renders no pill.

## Findings

| # | Severity | Finding | Where |
|---|---|---|---|
| 1 | **High** | One row with a non-numeric quality (`null`, a string) crashes the whole generation: `TypeError` in the `qualityDelta` subtraction. Core stores `evidence` as given, without validation. | `_js_data()`, `compass-dashboard.py` ~L2431 |
| 2 | **High** | Guidance is unreachable in a namespace without decisions. `renderDetail()` adds the Decisions sub-tab only when `ns.decisions` is non-empty, and `renderDecisions()` returns the empty state before it calls `renderDecisionGuidance()`. The global Decisions view still counts these pairs ("8 guidance pairs mined" when 4 are reachable) and points to tabs that do not exist. | `renderDetail()`, `renderDecisions()`, `renderDecisionsView()` |
| 3 | Medium | No heading separates the guidance cards from the decision list. The two lists look the same, and the tab label (`Decisions (9)`) does not count the pairs. | `renderDecisions()` |
| 4 | Medium | A negative delta (the avoided option scored higher) uses the same blue pill as a positive one. It contradicts the ✓/✗ framing without a warning. | `.guidance-delta` |
| 5 | Low | `contextSummary` (the situation) renders last, in muted rationale style. It is the "when does this apply" line, so it should come first. | `renderDecisionGuidance()` |
| 6 | Low | The delta is a difference of 0–1 quality scores shown as `%`. Percentage points (`pp`) is the correct unit. | `renderDecisionGuidance()` |

## Fixed (2026-10-23)

- **1:** `_guidance_quality_delta()` returns `None` unless both qualities are `int`/`float` and not
  `bool`. Pinned by `test_generate.py::TestDecisionGuidance::test_quality_delta_only_for_numeric_evidence`.
- **2:** `detailTabs(ns)` (pulled out of `renderDetail()`) shows Decisions for decisions *or* guidance.
  `renderDecisions()` renders guidance before the empty state. Pinned by two `dashboard_helpers` cases.
  Browser re-check: `dg-no-decisions` now shows all 5 active pairs, including the `null`-quality
  row, with no delta pill. Generation with that row no longer crashes.

## Proposed fixes (1 and 2 done)

1. Compute `qualityDelta` only when both values are `int`/`float` (not `bool`); otherwise `None`.
   Add a `test_data_loading.py` case with a `null` quality. (~15 min)
2. Show the Decisions sub-tab when `decisions` **or** `decisionGuidance` is non-empty. Render guidance
   before the empty state. Add a smoke case for guidance-only. (~30 min)
3. Add a small "Guidance (N)" header above the cards, and count the pairs in the tab label. (~15 min)
4. Amber pill for a negative delta, with a tooltip "avoided option scored higher". (~10 min)
5. and 6. Move the context line to the top; show `pp`. (~10 min)

Confidence that the list is complete for the current UI: 7/10. Real rows from
`get-decision-guidance-candidates` can have shapes this check did not try.

## Pinned now

`tests/js/dashboard_helpers.test.mjs` has a `renderDecisionGuidance()` case: card count, signed
deltas, no pill without evidence, escaping, the date and empty input. Fixes 3–6 change that output,
so update the case with them.
