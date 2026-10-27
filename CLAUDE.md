# Compass Dashboard — CLAUDE.md

Current conventions only. Dated fix histories, incident narratives and design rationale live in
[`docs/claude-md-history.md`](docs/claude-md-history.md) (verbatim, append-only) — read an entry
there when you need the *why* behind a rule here or in the nested CLAUDE.md files.

## What this is

A Python script (`scripts/compass-dashboard.py`) that reads all compass loop namespaces
from `~/.claude/loop/` and generates a self-contained static HTML dashboard by injecting
data into `scripts/template.html`.

**Regenerate:**
```bash
python3 scripts/compass-dashboard.py
# Output: ~/Downloads/compass-dashboard.html — open directly in a browser, no server needed
```

---

## Where the rules live

| File | Holds | Loads |
|------|-------|-------|
| `CLAUDE.md` (this file) | What this is, upkeep, architecture, security | Every turn |
| [`scripts/CLAUDE.md`](scripts/CLAUDE.md) | `template.html` traps, template substitution, tab system, data model, stateful view tabs | When Claude reads a file in `scripts/` |
| [`docs/claude/views.md`](docs/claude/views.md) | Per-view rules (DAG, Mind Map, Radar, Compare, global filter, Live strip, Tasks, State, Learnings, Decision Guidance) | Only when followed from the pointer in `scripts/CLAUDE.md` |
| [`tests/CLAUDE.md`](tests/CLAUDE.md) | Test file table and testing rules | When Claude reads a file in `tests/` |

A nested file arrives only after the Read tool opens a file in its folder. A Bash-only
`rg`/`sed` pass over `scripts/` or `tests/` does not load it, so Read the folder's CLAUDE.md
first when you work there that way.

Before calling work done, run `python3 -m pytest tests/ -q` **and** `node --test tests/js/`.

---

## Keeping these files lean

This file loads on every turn and the nested ones load whenever their folder is touched, so
they hold rules, not stories. **Budget: 20KB per file** (`tests/test_claude_md_budget.py` fails
above it, and checks that no section of the pre-split file was dropped).

- **When adding a fix or feature note:** state the resulting rule here in one or two sentences.
  Put the narrative (what broke, how it was found, before/after numbers) in
  `docs/claude-md-history.md` under a new `## <YYYY-MM-DD> archival pass` section. Never rewrite
  or delete older sections of that file.
- **Periodic hygiene pass:** compass core's CLAUDE.md review
  (`~/.claude/skills/compass/scripts/prompts/claude-md-hygiene-review.md`) fires for this
  namespace every 15 sessions, or early once any rules file above is over budget (core finds them by convention: root, `<dir>/CLAUDE.md`, `docs/claude/*.md`). When it fires — or when
  the budget test fails — run it: correct stale facts against the code, archive dated narratives
  verbatim with `~/.claude/skills/compass/scripts/archive_claude_md.py` (`--list` for the size
  table; it refuses to write unless nothing was lost), then
  `python3 ~/.claude/skills/compass/scripts/compass.py record-claude-review compass-dashboard`.
- **Things that go stale fastest:** line counts, test counts, "authoritative list" copies of
  arrays in `template.html`. Prefer pointing at the code over copying it.

---

## Architecture

```
scripts/
├── compass-dashboard.py   — data layer + generate() + main()
│   ├── load_namespace()    — thin composition: _read_namespace_files() -> _assemble_namespace_dict()
│   │   ├── _read_namespace_files()    — file-reading/parsing phase (I/O only, no derived fields)
│   │   └── _assemble_namespace_dict() — derived/computed fields + final return dict
│   ├── _js_data()          — serialises NS array as JSON embedded in HTML (camelCase rename table)
│   └── generate()          — reads template.html, injects [[PLACEHOLDER]] markers
└── template.html           — HTML + <style> + <script>
    └── JS                  — all interactivity; operates on const NS = [...]
```

All data is baked into `const NS = [...]` at generation time. There is no runtime backend
and there never will be — static HTML only. Stdlib-only Python; no JS libraries (no D3,
Chart.js etc. — the DAG force simulation and mind-map radial layout are hand-rolled).

---

## Security

Use `esc(str)` (already defined in the JS) for any user-controlled string going into
`innerHTML`. Namespace names, learning text, decision text, and tooltip strings all
count as user-controlled.
