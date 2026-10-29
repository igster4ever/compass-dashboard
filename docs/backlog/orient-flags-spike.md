# Spike: call `compass.py orient-flags` at generation time, or keep the mirrors

**Status:** decided 2026-10-29: **no-go**. Keep the mirrored `_check_*_due` copies and their parity
tests. · **Source:** compass-dashboard session 2026-10-29, goal 5 (explore); data-model audit
2026-10-28, Rank 9b.

## Recommendation

Do not call `orient-flags` from `compass-dashboard.py`. Four findings show it costs more than it saves.
The mirrors are safe now, because two tests find drift: `test_core_parity.py` finds changed logic,
and `test_surface_inventory.py` finds new core fields.

Overall confidence: 8/10.

## Findings (live data, 14 namespaces)

All CLI runs used a copy of the loop (`COMPASS_LOOP_DIR`), so the real namespaces did not change.

| Measurement | Result |
|---|---|
| Full dashboard generation today | 1.63 s |
| `orient-flags` CLI, 14 calls in sequence | 3.82 s (0.16–0.38 s per call) |
| `orient-flags` CLI, 14 calls, 8 threads | 1.69 s |
| `_build_orient_flags()` imported in-process, 14 calls | 1.46 s (import 0.02 s) |
| Payload per namespace | 0.8–3 KB |

1. **The CLI writes state.** `orient-flags` is in core's `_NS_BEARING` set, so `main()` calls
   `_increment_session_counter()` before the command runs. For an open namespace, each call adds 1 to
   `session_command_count` and rewrites `state.json`. In the copy, two runs changed the counter of
   the open namespace from 2 to 4. `--watch` regenerates every 30 s, which adds 120 to the counter
   per hour. That makes core's P24 complexity advisory (`session_complexity.elevated`) wrong. It
   also writes `state.json` while a compass session can write the same file. **This is a blocker.**
2. **It makes generation 2–3 times slower.** It adds 1.5–3.8 s to a 1.6 s run, because
   `_build_orient_flags()` builds the full orient context (`_build_orient_context()`) for each
   namespace. `--watch` pays this cost on each tick.
3. **It replaces only part of the mirrors.** `orient-flags` gives the six cadence `*_due` booleans,
   `suggested_goal_count`, `stale_bullet_count` and `goal_completion_trend`. It gives a
   `<name>_status` block only for a gate that is due. The cadence cards show "N of M sessions" for
   every gate, so the dashboard still needs the counters. These mirrors have no `orient-flags`
   equivalent: `_reality_completeness()`, `_check_reality_compaction_due()`,
   `_compaction_eligible_count()`, `_check_cadence_pull_forward()`, `_check_quality_plateau()`,
   `_compute_confidence_calibration()`, `_contract_coverage()`, `_check_reality_structure()`. So
   the parity test stays in every case.
4. **It couples the dashboard to core at run time.** Today the dashboard is stdlib-only and runs
   without core. With the call, generation needs core and Python 3.10 or later (`compass.sh`
   refuses macOS's 3.9). Without them, generation fails, or the dashboard needs a second code path.

## The contradiction (TRIZ / ASIT)

- **Contradiction:** one source of truth for gate logic (call core) vs. a static, stdlib-only,
  fast and side-effect-free generator (copy the logic).
- **Ideal final result:** the copies check themselves, so a duplicate is never wrong for long.
  This exists now: `test_core_parity.py` compares every mirror with core on all live namespaces,
  and `test_surface_inventory.py` fails on a core field that the dashboard does not read or ignore.
- **ASIT, Object removal:** remove the risk of the mirrors, not the mirrors. The tests do that.
- **ASIT, Division:** a split (call core only for the `*_due` booleans) keeps every cost above and
  removes only 6 of 15 mirrors. Rejected.
- **Designed friction that stays:** core's command counter is intentional (P24 measures loop
  overhead in a session). The dashboard must not go around it or turn it off.

| Aspect (1–10, higher is better) | Call `orient-flags` | Keep mirrors + tests | Confidence |
|---|---|---|---|
| No side effects on loop data | 2 | 10 | 9/10 |
| Generation speed (`--watch`) | 4 | 9 | 8/10 |
| Mirror code removed | 4 (6 of 15) | 1 | 7/10 |
| Drift caught | 8 | 8 (parity + inventory) | 7/10 |
| Runs without core / on Python 3.9 | 2 | 10 | 9/10 |

## When to look at this again

Look again only if both of these become true:

- core adds a read-only entry point that does not count the call. Examples: a command not in
  `_NS_BEARING`, or a pure function with a stable import path.
- one call gives all gate statuses, not only the due ones.

Then measure again: an in-process import (1.46 s today) is the only form with an acceptable cost.
