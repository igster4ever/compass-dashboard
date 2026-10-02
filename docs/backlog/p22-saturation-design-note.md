# P22 completeness saturation: design note for compass core

**Status:** proposal for compass core to decide. Nothing is mirrored here until core decides.
**Date:** 2026-10-02 · **Source:** Strategic backlog bullet "P22 completeness now saturates…" (session-2026-09-30)

## Recommendation

Keep P22 unchanged, and add a separate **open-work ratio** next to it:
`backlog / (achieved + backlog)`.
Do **not** put Backlog bullets into P22's denominator.

Confidence: 7/10. The data supports it. The open question is whether core wants one number or two.

## The problem

Since P22 became section-aware (2026-09-30), every bullet under a "What exists and works"-style
header counts as achieved, and Backlog sections are excluded. For any namespace that uses the
standard layout, the score is now 100% by construction. It is truthful ("every claim is in an
achieved section"), but it no longer separates namespaces. Live data, 12 scored namespaces:

| Namespace | P22 | achieved/scored | backlog | A′ = achieved/(scored+backlog) | open-work ratio |
|---|---|---|---|---|---|
| `agentic-loopkit` | 98.7 | 75/76 | 21 | 77.3 | 21.9 |
| `agentic-memorykit` | 100.0 | 32/32 | 3 | 91.4 | 8.6 |
| `compass` | 100.0 | 94/94 | 41 | 69.6 | 30.4 |
| `compass-dashboard` | 100.0 | 115/115 | 13 | 89.8 | 10.2 |
| `global` | 8.3 | 1/12 | 0 | 8.3 | 0.0 |
| `gps-adr-dashboard` | 40.0 | 14/35 | 1 | 38.9 | 6.7 |
| `gps-wiki` | 66.7 | 8/12 | 17 | 27.6 | 68.0 |
| `incident-investigator` | 100.0 | 25/25 | 4 | 86.2 | 13.8 |
| `mpsm` | 22.2 | 2/9 | 0 | 22.2 | 0.0 |
| `squad-gps-radar` | 100.0 | 19/19 | 3 | 86.4 | 13.6 |
| `standards-compliance-audit` | 100.0 | 55/55 | 7 | 88.7 | 11.3 |
| `wiki-frontend` | 100.0 | 12/12 | 2 | 85.7 | 14.3 |

P22: 8 of 12 namespaces at ≥95. A′: none at ≥95.

## Options considered

1. **The backlog question's original form: `achieved / (achieved + backlog)`.** Rejected. It drops
   P22's unachieved non-backlog bullets from the denominator, so `global` (1/12 achieved, no backlog)
   jumps from 8.3 to **100**. It inverts the namespaces P22 already scores correctly.
2. **A′ = `achieved / (scored + backlog)`.** It separates namespaces well and is never higher than P22.
   But it moves against good practice: writing down a new backlog item lowers the score. That
   punishes the exact backlog hygiene the namespace-backlog standard asks for.
3. **Freshness (achieved bullets verified within 30 days).** Rejected as a completeness metric. It
   measures how recently the loop was used, not completeness: 9 of 12 namespaces score 0 just
   because nobody opened them this month. The stale count and the new verification-durability
   line on the State tab already show this.
4. **Two numbers: P22 as now + open-work ratio (recommended).**

## Why two numbers (TRIZ/ASIT)

**Contradiction:** the score should *separate namespaces* (so it must react to open work), yet it
should *not penalise recording open work* (so it must ignore backlog). One number can't do both.

- **Ideal Final Result:** the score reacts to open work and recording work costs nothing. That works
  when the two quantities live on different axes.
- **ASIT Division:** split the single "completeness" number into "claims achieved" (P22, which answers
  *is reality.md true?*) and "open work share" (which answers *how much is left?*). A long backlog
  then reads as "lots planned", not "low quality".
- **Designed check kept:** P22's section-aware achievement rule stays exactly as it is. The
  saturation is accidental friction; the achievement rule is deliberate.

| Aspect | A′ (single) | P22 + open-work (split) |
|---|---|---|
| Separates namespaces | 8/10 | 8/10 (open-work spread 0–68) |
| Doesn't punish recording backlog | 3/10 | 9/10 |
| Backward compatible (`last_reality_score`, regression flag) | 4/10: every score drops, so a one-off regression fires everywhere | 9/10: P22 untouched |
| Fits the radar/compare axes | 8/10 | 6/10: needs one new axis or a tooltip |

## If core adopts it

- Core: add the open-work ratio to `_compute_reality_completeness()`'s return dict (for example
  `backlog_count`, `open_work_ratio`), computed in the same pass as P22. Use the same `_BACKLOG_HEADERS`
  (whose `###` boundary handling needs care: a `###` under Backlog must not end the bucket).
- Dashboard: mirror it next to `_reality_completeness()`, add a parity case to `test_core_parity.py`,
  and show "N% open" beside the completeness pill on the Overview card and in the State tab's Reality headline.
- Don't put it on the radar until it has a few weeks of real data. Compare's min-max normalisation
  would exaggerate small differences.

## Not decided here

- Whether a namespace with **no Backlog section** should show open-work as `0` or as "no backlog
  recorded" (`global`, `mpsm`). This is a null-vs-zero choice. Following the dashboard's own rule
  ("null means below threshold"), it should probably be `null`.
