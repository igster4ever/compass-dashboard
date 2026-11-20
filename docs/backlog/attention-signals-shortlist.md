# Shortlist — missing "what needs attention" signals in Priorities

Date: 2026-11-20. Status: explored, not built. Written in Simplified Technical English.

## Finding

`computePriorities()` scores 10 signals: open session, days since session, goal rate,
deferred items, planned actions, high-weight learnings, no sessions, corpus health,
review/research **deferral counts**, and latest review severity.

The data layer already carries these fields, and Priorities uses none of them:
`staleBulletCount`, `codeReviewDue`/`researchDue`/`skillOptDue`/`dreamDue`/`claudeReviewDue`,
`pulse.dirty_files`, `realityStructureWarnings`, `retrievalStaleCount`, `dataProblems`,
`carryForwardTrend`. No new data layer work is needed for any item below.

## Ranked shortlist

| Rank | Signal | Live evidence (2026-11-20) | Proposed weight | Confidence |
|------|--------|----------------------------|-----------------|------------|
| 1 | Stale reality bullets | agentic-loopkit 87, gps-adr-dashboard 35, agentic-memorykit 34, incident-investigator 29, squad-gps-radar 24. These are the largest numbers in the dataset. | +1 per 5 stale, cap 15 | 8/10 |
| 2 | Maintenance **due** (not only deferred) | 8 namespaces show code review due, 4 research due. Priorities only reads deferral counts, so a namespace that never defers is never flagged. | +6 code review, +4 research, +3 SkillOpt, +2 dream, +2 CLAUDE.md review | 7/10 |
| 3 | Dirty working tree | squad-gps-radar 41 files, agentic-loopkit 18. **Caveat:** global shows 1485 and gps-wiki/wiki-frontend share a repo, so the count needs a cap and a repo-dedupe. | +3 above 10 files, cap 6 | 5/10 |
| 4 | Reality structure warnings | 9 namespaces have 1–2. | +2 per warning, cap 4 | 6/10 |
| 5 | Retrieval-stale learnings | global 31, agentic-memorykit 6. | +1 per 5, cap 6 | 4/10 |
| 6 | Carry-forward above 0 | global 5, two others 1. | +2 per item, cap 8 | 4/10 |

Out of scope: `dataProblems` (0 live, already shown as a card chip) and `intentChanged`
(not in the NS data; it is a core gate flag).

## Risks

- **Score inflation.** Ranks 1 and 2 would lift old, quiet namespaces over active ones, because
  they have the most stale bullets. Priorities shows only 4 cards. Test the new total against live
  data before shipping, and keep the existing "days since last session" signal dominant.
- **Weights are guesses.** Existing weights were also set by judgement. Do not tune them to
  look right; pick them, then watch two sessions of real use.
- **Rank 3 is noisy by construction**, so build it last or not at all.

## Contradiction (TRIZ)

More signals give better coverage, but a longer reasons list hides the one reason that matters
(`reasons.slice(0, 5)` already truncates). Ideal result: the reason list ranks itself.
Cheapest step: sort `reasons` by points added before the slice. That is a 5-line change, and it
makes every new signal safe to add.

## Build order (when picked up)

1. Sort `reasons` by points added, then slice. Test with a fixture that has more than 5 reasons.
2. Rank 1 and Rank 2 together, with tests that pin the caps. About 1 hour.
3. Ranks 4 and 6 if the first two read well on live data.
