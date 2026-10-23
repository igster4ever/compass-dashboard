# Maturity-ladder scorecard with catalogue completeness: design note

**Status:** exploration, not scheduled. Strategic backlog candidate.
**Date:** 2026-10-23 · **Source:** compass-dashboard session 2026-10-23 (goal 5, explore), from two
research signals in reality.md: scorecards move from one score to a maturity-level ladder; portals
track catalogue completeness (missing metadata, missing ownership) as a metric.

## Recommendation

Add a **maturity ladder** to the Scorecard: levels L0–L4, each a list of named checks over the
baked `NS` data. Show each namespace as **level + completeness** in one chip (for example
`L2 · 64%`), plus a "next step" list: the checks that fail at the next level.

- The checks are data (a JS array of predicates), so the ladder is query-driven *over the snapshot*.
  This needs no backend. `--watch` already makes the snapshot recent.
- A check can be **N/A** for a namespace. N/A is not a failure and is not counted.
- Keep the 5-axis parallel-coordinates chart. The ladder is added to the ranked table; it does not
  replace the chart.

Overall confidence: 6/10. The data supports it. The level thresholds need one tuning pass with you.

## The problem with the current Scorecard

1. **Maturity is saturated.** The Maturity axis is P22 reality completeness. Since 2026-09-30 it is
   about 100% for every namespace that uses the standard layout (`docs/backlog/p22-saturation-design-note.md`).
   It does not separate namespaces.
2. **Scores are relative.** Maturity, Learning and Focus use min-max normalisation across the visible
   namespaces. A change to the global filter changes every score. "Health 72%" has no fixed meaning.
3. **Scores are not actionable.** A number does not tell you what to do next.

A ladder solves all three: a level is absolute, it does not depend on the filter, and the failing
checks are the next actions.

## What the data shows (live, 14 namespaces, 2026-10-23)

Metadata coverage varies much more than any current axis shows:

| Signal | Range across namespaces |
|---|---|
| Active learnings with `zone` | 0%–59% (8 of 14 at 0%) |
| Active learnings with `learning_id` | 0%–100% (6 of 14 at 0%) |
| Sessions with goal types recorded | 0/16 – 11/11 |
| Namespaces with ≥ 5 goal contracts | 1 of 14 (`compass`) |
| `CLAUDE.md` present | 12 of 14 |
| `code_context.md` present | 12 of 14 |

Provisional ladder, run once over the live data (scratch script, not committed):

| Level | Checks (all must pass, plus all lower levels) |
|---|---|
| L1 Registered | `intent.md` not empty · `reality.md` exists · ≥ 1 closed session |
| L2 Wired | `repo_path` set · `CLAUDE.md` exists · `code_context.md` exists · ≥ 3 sessions |
| L3 Instrumented | every active learning tagged · ≥ 90% with `learning_id` · ≥ 50% with `zone` · goal types in ≥ 3 of the last 5 sessions · ≥ 1 decision |
| L4 Calibrated | ≥ 5 goal contracts · outcome rate ≥ 30% · no stale reality bullets |

| Result | Namespaces |
|---|---|
| L3 (86%) | `compass-dashboard`, `standards-compliance-a` |
| L2 (57–86%) | `compass` (86%: only `zone` fails), `agentic-loopkit`, `agentic-memorykit`, `gps-adr-dashboard`, `gps-wiki`, `incident-investigator`, `mpsm`, `wiki-frontend` |
| L1 | `compass-pulse` (79%: only `CLAUDE.md` fails), `global` (43%), `squad-gps-radar` (50%), `3p-skill` (21%) |

The run did not compute two L4 checks: outcome rate counted as a fail for every namespace, and
stale bullets were not checked. So no namespace could reach L4, and L4 placements are untested.

Two findings from this run changed the design:

- **A strict ladder hides progress.** `compass-pulse` passes 79% of all checks but is L1 because of
  one check. So the chip shows completeness next to the level.
- **Some checks do not apply.** `global` has no repo, so `repo_path`, `CLAUDE.md` and
  `code_context.md` cannot pass. So a check can declare `applies(ns)`; when it is false, the check is N/A.

## Contradictions and how the design resolves them

**C1 — live query-driven ladder vs static HTML with no backend.**
- *Ideal result:* the levels evaluate themselves when the data changes, with no server.
- *Resolution:* the checks are predicates in the page, evaluated over `NS`. `--watch` regenerates
  `NS`. Evaluation is "live" over the snapshot, and the snapshot is minutes old. (The static-only
  constraint is deliberate, so it stays.)

**C2 — strict gating (absolute, actionable) vs partial credit (shows progress).**
- *Ideal result:* one view shows both "what tier" and "how far along".
- *ASIT Unification:* the same check list produces both numbers. Level = highest fully passed tier;
  completeness = passed / applicable over all tiers.
- *ASIT Breaking symmetry:* checks are not equal. A failing check at the next level is shown as
  "next step"; failing checks at higher levels are shown only in the detail drawer.
- *ASIT Object removal:* no weights and no composite formula. A tier is a list of booleans.

Rubric (1–10, higher is better):

| Aspect | Raw-number Scorecard (today) | Ladder + completeness | Confidence |
|---|---|---|---|
| Absolute meaning (does not change with the filter) | 3 | 9 | 8/10 |
| Actionable (tells you the next step) | 2 | 9 | 8/10 |
| Separates namespaces | 4 (Maturity is saturated) | 8 | 7/10 |
| Effort and risk | 10 (exists) | 6 | 6/10 |
| Shows partial progress | 7 | 8 | 7/10 |

## Data-layer gaps

Most inputs are already in `NS`: `intent`, `codeContext`, `learnings[]` (`tags`, `learning_id`,
`zone`), `decisions`, `sessionCount`, `goalTypeBySession`, `staleBulletCount`, `contracts`,
`outcomeRate`, `claudeReviewStatus`, `pulse`. Two inputs are not:

1. `repo_path`: not in `_js_data()`. Add it as a boolean `hasRepoPath`, not the path, so local paths
   stay out of the page.
2. Reality structure warnings: `_check_reality_structure()` is core-only. Mirror it and add a parity
   case in `test_core_parity.py`, or drop the check from L1.

## Open questions (decide before implementation)

1. Is L3's `zone ≥ 50%` correct? Today it is the check that holds 8 namespaces at L2. Zone tagging
   is new, so it can measure "adopted the new feature" and not "maturity".
2. Does the ladder go only in the Scorecard, or also on Overview cards (one chip)?
3. Does completeness replace the saturated Maturity axis on the parallel-coordinates chart?
   Recommendation: yes. It is a direct improvement, and it is absolute (no min-max).

## Effort (if adopted)

About 3–4 hours: `LADDER` checks array and a pure `ladderLevel(ns)` helper (~1 h, tested in
`dashboard_helpers`), two data-layer fields and a parity case (~1 h), Scorecard table column and
detail drawer (~1–1.5 h), browser check (~0.5 h).
