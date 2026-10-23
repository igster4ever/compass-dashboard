# CLAUDE.md progressive disclosure: split by location

**Status:** shipped 2026-10-23 (steps 1–9). Step 4 of Costs (the compass core hygiene-review prompt) is open, in the `compass` repo.
**Date:** 2026-10-21 · **Source:** compass-dashboard session 2026-10-21 (CLAUDE.md at 19,993 of 20,000 bytes)

## Recommendation

Split the root CLAUDE.md into files that load only when Claude works in their area.
Use nested CLAUDE.md files for areas of the tree. Use one pointer doc for per-view rules.
Do **not** use `@path` imports. Claude Code loads imports at launch, so they save no context.

Expected result: a turn that does not touch code loads about 5 KB, not 20 KB.
Each file gets its own 20 KB budget.

## The problem

- The root CLAUDE.md loads on every turn. It is at 19,993 of 20,000 bytes (2026-10-21).
- The last two rules each needed an archival pass first. Each pass moved one paragraph.
- Most of the file applies only when a specific file is edited.
  Compass open and close turns, and questions, load all of it for no use.

## Size by section (2026-10-21)

| Section | Bytes | Needed when |
|---|---|---|
| Data model | 5,352 | You edit `compass-dashboard.py` |
| View-specific rules | 4,940 | You edit one view's `render*` code |
| Tests | 2,427 | You write or run tests |
| `template.html` traps | 2,044 | You edit `template.html` |
| Keeping this file lean | 1,240 | Every turn (hygiene rules) |
| Architecture | 1,051 | Every turn |
| Tab system | 983 | You edit `template.html` |
| Stateful view tabs | 541 | You edit `template.html` |
| Template substitution | 525 | You edit `generate()` or `template.html` |
| What this is + preamble | 676 | Every turn |
| Security | 214 | Every turn |

## Target layout

| File | Content | Size | Loads |
|---|---|---|---|
| `CLAUDE.md` (root) | What this is, Keeping lean, Architecture, Security, the two test commands, a "where rules live" map | ~5 KB | Every turn |
| `scripts/CLAUDE.md` | Template traps, Template substitution, Tab system, Stateful view tabs, Data model | ~10 KB | When Claude reads a file in `scripts/` |
| `docs/claude/views.md` | View-specific rules (DAG, Mind Map, Radar, Compare, global filter, Live strip, Tasks, State, Learnings, Decision Guidance) | ~5 KB | When Claude follows the pointer |
| `tests/CLAUDE.md` | Test table and testing rules | ~2.4 KB | When Claude reads a file in `tests/` |

The pointer line in `scripts/CLAUDE.md`:
"Before you edit a view's `render*` function, read its section in `docs/claude/views.md`."
Name the functions each section covers, so the trigger is specific.

## Design reasoning

**Contradiction:** a rule must be available when it applies, but it must not load when it does not.

**Ideal result:** a rule loads exactly when Claude touches the file that the rule controls.
A nested CLAUDE.md does this by design. This is division by location, not by topic.

**Compromise:** the views pointer doc. It depends on Claude reading it when the trigger occurs.
Only the per-view rules go there, because each turn touches one view at most.

**Keep these checks unchanged:** the budget test, the no-loss check in `archive_claude_md.py`,
and the hygiene review every 15 sessions. These are deliberate checks.

## Costs

1. `tests/test_claude_md_budget.py` must check each CLAUDE.md file, not only the root.
2. Compass core measures only the root file and `scripts/CLAUDE.md` (`_claude_md_files()` mirrors this).
   Core does not see `tests/CLAUDE.md` for the review cadence. The file is small, so this is acceptable.
3. The views doc depends on the pointer. This is the weakest part.
4. The CLAUDE.md hygiene review prompt must know about the new files.

## Implementation steps

1. Verify the load behaviour first. In a fresh session, put a marker rule in a test `scripts/CLAUDE.md`.
   Confirm that it is not in context at session start. Confirm that it loads after Claude reads a file in `scripts/`.
   If it loads at start, stop. Use pointer docs only.
   **Result (2026-10-23): pass.** A fresh subagent did not have the marker before any tool call.
   After it read the first lines of `scripts/compass-dashboard.py`, the marker arrived in a system reminder
   that quoted `scripts/CLAUDE.md`. The main session showed the same result. After the split, with the CLI
   re-authenticated, fresh `claude -p` sessions confirmed it on the real file: with no tools there was no
   `overflow-anchor` rule; after one Read in `scripts/`, the model quoted trap 6 from `scripts/CLAUDE.md`.
2. Save the current rule text. Run `archive_claude_md.py --list` to record the section sizes.
3. Make `scripts/CLAUDE.md`, `tests/CLAUDE.md` and `docs/claude/views.md`. Move each section verbatim.
4. Write the "where rules live" map in the root file. One line for each new file.
5. Add the views pointer line to `scripts/CLAUDE.md`.
6. Change `test_claude_md_budget.py`: check each CLAUDE.md file against 20,000 bytes.
   Add a test that every section in the old file is now in exactly one new file.
7. Run `test_core_parity.py`. The claude_review gate must still agree with core.
8. Update the CLAUDE.md history file with a dated archival-pass entry.
9. Run both test suites.

## Effort and confidence

Effort: about 1–1.5 hours.

| Aspect | Confidence | Why |
|---|---|---|
| Nested files decrease the every-turn load | 8/10 | Documented Claude Code behaviour. Step 1 verifies it here |
| The pointer doc is read when necessary | 6/10 | It depends on a trigger phrase. Specific function names decrease the risk |
| No rule is lost in the move | 9/10 | `archive_claude_md.py` refuses to write when content is lost. Step 6 adds a test |
| Budget test and core parity stay green | 8/10 | Core already measures each file. The test needs a loop |
