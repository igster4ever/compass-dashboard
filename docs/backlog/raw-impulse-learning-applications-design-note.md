# Design note — `raw_impulse` and `learning_applications` (Rank 5)

Date: 2026-10-30. Status: decided, not built. Source: Tactical backlog Rank 5/9
(data-model-audit-2026-10-28). Written in Simplified Technical English.

## Verdict

| Data | View it earns | Confidence |
|------|---------------|------------|
| `raw_impulse` text | **None.** Do not show the text. | 8/10 |
| `raw_impulse` capture rate | **One line** on the State tab: "Impulse captured in N of M opens; P74 Phase 2 needs 8–10". | 7/10 |
| `learning_applications.jsonl` | **One count per learning** ("applied in N sessions") in the Learnings tab. Show P64 gain only when core says the sample is sufficient. Do not show `quality_score` per learning. | 7/10 |
| `goal_origin` | **A "from goal" link per learning**, resolved through the history file of the session that logged it. | 6/10 |
| `last_surfaced_at` | **"Last surfaced Nd ago"** with `times_surfaced`, as a sort key in the Learnings tab. | 7/10 |

The Rank 5 bullet asked for "the raw impulse beside that session's planned goals" and
"applications and quality_score per learning". This note rejects both of those, and
gives the reasons below.

## Data as of 2026-10-30

- **`raw_impulse`:** 4 namespaces have the key in `cycle_history` (34 entries). Only **3**
  entries are non-empty. The other 31 are skips. `impulses.jsonl` has 3 rows in total, one
  each in compass, compass-pulse and standards-compliance-audit. The Rank 5 bullet said
  "33 entries carry it". That is true for the key, but not for the value.
- **`learning_applications.jsonl`:** 8 rows in 2 namespaces (compass 7, compass-dashboard 1).
  Only one learning (`60e00233`) is in 2 distinct sessions. That is the minimum for P64 gain
  (`_MIN_APPLICATION_SESSIONS = 2`). No learning has a `promoted` key.
- **`quality_score` on an application row** is the score of the **session**, not of the
  learning. All rows of one session have the same value (for example, 0.965 for 3 rows on
  2026-10-26).
- **`goal_origin`:** 126 of 598 learnings. It is `list[int]`, an index into the goals of
  the session that logged the learning. 21 learnings have more than one index. No learning
  has `session_ref`, but all 126 have `date`.
- **`last_surfaced_at`:** 138 learnings. The dashboard does not show `times_surfaced` either.

## Reasons

### 1. Do not show `raw_impulse` text (observer effect)

- The compass-open skill, Step 0, says: do not interpret the impulse, and never surface it
  again. The P74 Phase 1 plan says: no "surfacing of `raw_impulse` back to the user".
- The purpose of P74 is to measure the impulse **before** mediation. If the user can see
  past impulses beside the goals they became, the user can start to write impulses
  for the dashboard. That changes the data that P74 Phase 2 will measure.
- The dashboard is a surface that the user reads. Thus, the same rule applies to it.
- **Revisit when:** P74 Phase 2 ships and core itself decides to surface pairs. Then mirror
  core. Do not get ahead of it.

### 2. Show the capture rate, not the content

- The capture rate is 3 of 34 (9%). This is the real blocker for P74 Phase 2, which needs
  8–10 real sessions. At the current rate, that can take many months.
- A capture rate shows no impulse text. Thus, it does not cause the observer effect.
- It makes the gate visible: "3 of 8 needed". The user can then decide to answer Step 0
  more often, or decide that P74 is not worth it.
- **Data:** count `cycle_history` entries that have the key, and the ones with a
  non-empty value. Use `impulses.jsonl` row count as the durable total, because
  `cycle_history` keeps only 10 entries (see Rank 4).

### 3. Do not show `quality_score` per learning

- The score belongs to the session. If you show it per learning, it implies that the learning
  caused the score. With 8 rows, that is noise.
- Core already has the correct statistic: `_compute_learning_gain()` (P64). It compares
  sessions with the learning against a shrinkage baseline, and it returns `None` below
  2 sessions.
- **Do:** show "applied in N sessions" (a plain count). Mirror `_compute_learning_gain()`
  and show gain only when `sufficient_sample` is true. Add a parity case to
  `tests/test_core_parity.py`, as for every other mirror.
- Today, this shows a count on 8 learnings and gain on 1. Core a88a6fd records every
  confirmed boost at close, so the count will increase each session.

### 4. `goal_origin` needs a join, and the join is possible

- An index without its session has no meaning. No learning has `session_ref`.
- Use `date`: find the history file where `opened <= date <= closed`, then take
  `planned[index]`. `raw["history_parsed"]` (goal 3, 2026-10-30) holds all history files in
  one pass, so this costs no extra I/O.
- **Risk:** a learning that is logged after close (by the dream pass or a manual
  `log-learning`) is outside all windows. Show nothing for it. Do not guess.
- Confidence is lower (6/10) because no one has measured the join hit rate yet. Before you
  build the UI, measure how many of the 126 resolve. If fewer than 80% resolve, stop and
  report.

### 5. `last_surfaced_at` is cheap and useful now

- `times_surfaced` and `last_surfaced_at` together show learnings that the loop never
  shows to the user. A learning with high weight and 0 surfacings is a retrieval gap.
- Add both as sort keys in the Learnings tab. Do not add a new panel.

## Out of scope

- Mediation-drift scoring and the 3-way bucket taxonomy (sharpened, redirected, dropped).
  Core's P74 Phase 2 owns this, and it is gated on 8–10 sessions and a validated taxonomy.
- Learning promotion (P64 `promote-learning`). No learning is promoted yet.

## Build order (when picked up)

1. `last_surfaced_at` and `times_surfaced` sort keys. About 30 minutes, no risk.
2. "Applied in N sessions", and P64 gain with a parity case. About 1 hour.
3. Impulse capture-rate line. About 30 minutes.
4. `goal_origin` join. Measure the hit rate first, then build. About 1 hour.

After each step, remove the matching entry from `IGNORED` in
`tests/test_surface_inventory.py`: `last_surfaced_at`, `learning_applications.jsonl`,
`impulses.jsonl` and `raw_impulse` (step 3, as a count only), and `goal_origin`.
