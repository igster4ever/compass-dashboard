# Catalogue completeness: spike over live data

**Status:** spike done 2026-10-27; all 3 amendments accepted the same day (ladder note Decisions
4–6). It feeds the maturity-ladder build
(`maturity-ladder-scorecard-design-note.md`). It proposes 3 amendments to that note. Amendment 2 reverses
part of the 2026-10-27 zone decision.
**Date:** 2026-10-27 · **Source:** compass-dashboard session 2026-10-27 (goal 4), from the research
signal "portals track catalogue completeness (missing metadata, missing ownership) as a metric".

## Recommendation

Do not build a separate catalogue-completeness metric. **Ladder completeness is catalogue
completeness:** the same check list gives the level, the percentage and the gap list (ASIT
Unification). The spike shows that the check list itself needs three changes first (see Amendments).

Confidence: 8/10 for "no separate metric". 7/10 for the amendments.

## Method

A scratch script (not committed) ran the ladder from the design note over all 14 live namespaces. It
used `load_namespace()` from `scripts/compass-dashboard.py`, so the inputs are the same as the
page's. It included the two L4 checks that the 2026-10-23 run did not compute (outcome rate, stale
bullets), and it used the 2026-10-27 zone decision (learnings logged since 2026-07-05 only). It was
read-only: it wrote no loop files.

## Result

| Namespace | Level · completeness | Next step (failing checks at the next level) |
|---|---|---|
| `compass-dashboard`, `standards-compliance-audit` | L3 · 93% | ≥ 5 goal contracts |
| `compass` | L2 · 93% | zone ≥ 50% (17/54 since 2026-07-05) |
| `gps-adr-dashboard`, `gps-wiki`, `incident-investigator` | L2 · 77% | ≥ 90% `learning_id` |
| `agentic-loopkit`, `agentic-memorykit` | L2 · 73% | ≥ 90% `learning_id`, zone |
| `mpsm`, `wiki-frontend` | L2 · 69% | ≥ 90% `learning_id`, ≥ 1 decision |
| `compass-pulse` | L1 · 87% | `CLAUDE.md` |
| `squad-gps-radar` | L1 · 54% | ≥ 3 sessions |
| `global` | L1 · 43% | `code_context`, ≥ 3 sessions |
| `3p-skill` | L1 · 31% | `repo_path`, `CLAUDE.md`, `code_context`, ≥ 3 sessions |

No namespace reaches L4. For the two L3 namespaces, contracts are the only L4 blocker. Only `compass`
has ≥ 5 contracts, and it fails at L3. So L4 is aspirational today. That is acceptable for a top tier.

## Findings

1. **`learning_id` is a schema-adoption check, not a discipline check.** 0 of 240 learnings from
   before 2026-06-15 have an id; 376 of 376 after that date have one. Core assigns the id at write
   time, so the check is always 100% for new learnings and 0% for old ones. It holds 7 namespaces at
   L2 only because they have old learnings. This is the same problem as the raw zone check (decided
   2026-10-27), but stronger: the zone rate since the ship date still varies (17/54 to 26/31), and
   the id rate since its ship date is fixed at 100%, so it measures nothing.
2. **"N/A" and "no data" are different, and the first run treated them the same.** The spike made
   `outcome_rate == null` N/A. That lets a namespace with no goal-outcome links pass an L4 check with
   no evidence. "Calibrated" needs evidence, so "no data" must fail. N/A is only for checks that
   cannot apply to the namespace's shape (no repo).
   The same rule applies to the zone check. The 2026-10-27 decision made it N/A when a namespace has
   no learnings since 2026-07-05. With `learning_id` removed, that N/A put `gps-adr-dashboard`,
   `gps-wiki` and `incident-investigator` (no learnings since July) at L3, above `compass` (L2,
   active every week). So N/A rewarded dormancy. Zero learnings since the ship date is "no data", not
   "does not apply".
3. **`global` is a sink namespace, and the repo checks misread it.** It has 2 session snapshots but
   161 active learnings, mostly propagated from other namespaces, so "≥ 3 sessions" measures the
   wrong thing. Its `state.json` also has `repo_path` set to a work monorepo
   (`be-hkjc-mono`). That looks like a stale value from an old `init`, not a deliberate setting.
   Check it before the build relies on `repo_path`.

## Amendments to the ladder design (accepted 2026-10-27)

1. **Remove `≥ 90% learning_id` from L3.** If old learnings must count, a one-off core backfill of
   ids is the correct fix, not a ladder check.
2. **Each check returns one of three values: pass, fail or N/A.** A predicate that has no data
   returns fail, with a reason that says so (for example "no learnings since 2026-07-05"), so the
   next-step list does not tell a dormant namespace to tag zones it does not have. It returns N/A
   only when its `applies(ns)` is false. This reverses the zone check's "N/A when there are none"
   (Finding 2). `ladderLevel(ns)` tests: "no data" is a fail, and "does not apply" is not counted.
3. **Give `global` its own profile.** The session-count and repo checks are N/A for the namespace
   `global` (named, not inferred). Fix its `repo_path` first if it is stale.

With amendments 1 and 2 (rerun on live data), the levels stay as above, but the reasons change.
The zone check, not `learning_id`, now holds all 8 L2 namespaces. Completeness separates the
active from the dormant: `compass` 93%, `agentic-loopkit`/`agentic-memorykit` 79%, the three
dormant `gps-*`/`incident-investigator` namespaces 71%, `mpsm`/`wiki-frontend` 64%. With amendment 1
only (zone N/A for dormant namespaces), the three dormant namespaces moved to L3 above `compass`.
That result is the reason for amendment 2.

## Effort impact

None on the 4 h estimate. The amendments remove one check and fix the meaning of N/A, which
`ladderLevel(ns)` needs to define anyway.
