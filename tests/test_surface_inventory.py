"""
Surface inventory: every state key, entry key and loop file compass core writes is either read by
the dashboard or listed in IGNORED with a reason.

test_core_parity.py can only check logic the dashboard already mirrors; it cannot see a field
core starts writing. The manual audits that filled that gap drifted (core had 109 commits
between the 2026-09-30 audit and the 2026-10-28 one, which found 14 unread state keys and 6
unread files). This suite derives what core writes from two sources and fails on anything new:

- core source: `state["k"] = ...`, `state.setdefault("k", ...)`, and quoted `*.jsonl|json|md`
  names in ~/.claude/skills/compass/scripts/compass/*.py;
- live data: the union of keys across every ~/.claude/loop/*/state.json, its cycle_history and
  quality_history entries, learnings.jsonl rows, and the entries in each namespace directory and
  the loop root.

"Read" means the name appears as a quoted string literal in scripts/compass-dashboard.py, or as
a snake_case member read (`s.command_count`) in scripts/template.html: `_js_data()` passes some
lists, such as cycle_history, to the page unchanged.

When this fails on a new name: wire it into the dashboard, or add it to IGNORED with a reason.
When an IGNORED name is now read or no longer written, remove it from IGNORED.
Skipped when core or the loop directory is absent (CI, fresh machine).

Run: python3 -m pytest tests/test_surface_inventory.py -v
"""

import json
import re
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
CORE_PKG = Path.home() / ".claude" / "skills" / "compass" / "scripts" / "compass"
LOOP = Path.home() / ".claude" / "loop"

_UNREAD_AUDIT = "unread; see data-model-audit-2026-10-28 backlog item"
_NOT_LOOP_FILE = "not a loop file: core names it for repo/skill checks"

# Names core writes that the dashboard deliberately does not read, keyed by surface.
# Seeded from the 2026-10-28 data-model audit. Each reason says why it is unread.
IGNORED = {
    "state": {
        "goal_types": "per-session types already reach the dashboard via goal_completions",
        "prompt_tally": "prompt-count instrumentation for core's own overhead metric",
        "prompt_screens": "prompt-count instrumentation for core's own overhead metric",
        "pending_raw_impulse": "transient: held between open and close, then moved to cycle_history",
        "last_backlog_match": "transient: written at close-prepare, popped at close-apply",
        "declined_opportunities": "core-side suppression list for skill-opportunity prompts",
        "session_command_count": "loop-overhead counter; cycle_history carries the per-session value",
        "close_phase_command_count": "loop-overhead counter; cycle_history carries the per-session value",
        "_warnings": "core's own write-time warnings, not namespace data",
    },
    "cycle_history": {
        "raw_impulse": f"{_UNREAD_AUDIT} Rank 5 (P74)",
        "prompt_count_sources": "prompt-count instrumentation for core's own overhead metric",
        "open_prompt_count": "prompt-count instrumentation for core's own overhead metric",
        "close_prompt_count": "prompt-count instrumentation for core's own overhead metric",
        "close_command_count": "loop-overhead counter",
        "close_duration_seconds": "loop-overhead timer",
        "closed_at": "the session's close time; opened_at dates the entry",
    },
    "quality_history": {
        "closed_at": "session_id identifies the entry",
    },
    "learnings": {
        "goal_origin": f"{_UNREAD_AUDIT} Rank 5",
        "last_surfaced_at": f"{_UNREAD_AUDIT} Rank 5",
        "priority": "core's retrieval ranking input; weight is the displayed strength",
        "seed_origin": "P67 cold-start provenance; seeded learnings are rare",
        "test_window": "hypothesis validation window; core prompts on expiry at open",
        "validated_at": "hypothesis validation time; validation_result carries the outcome",
        "superseded_at": "superseded rows are filtered out by the active filter",
        "superseded_by_id": "set together with superseded_by, which the active filter reads",
        "superseded_reason": "superseded rows are filtered out by the active filter",
    },
    "files": {
        "impulses.jsonl": f"{_UNREAD_AUDIT} Rank 5 (P74)",
        "learning_applications.jsonl": f"{_UNREAD_AUDIT} Rank 5 (P64)",
        "section_loads.jsonl": f"{_UNREAD_AUDIT} Rank 7 (loop root, not per namespace)",
        "skill_edit_rejections.jsonl": "SkillOpt-internal rejection log",
        "code_reviews": f"{_UNREAD_AUDIT} Rank 7",
        "claude.md": _NOT_LOOP_FILE,
        "SKILL.md": _NOT_LOOP_FILE,
        "skill.md": _NOT_LOOP_FILE,
        "readme.md": _NOT_LOOP_FILE,
        "code-review-agent.md": "core prompt template under scripts/prompts, not a loop file",
        "agents.md": _NOT_LOOP_FILE,
        "changelog.md": _NOT_LOOP_FILE,
        "package.json": _NOT_LOOP_FILE,
        "taxonomy.json": "core's tag taxonomy, shipped with core, not loop data",
    },
}

_STATE_ASSIGN = re.compile(r"""\bstate\[["'](\w+)["']\]\s*(?:=(?!=)|\+=|-=)""")
_STATE_SETDEFAULT = re.compile(r"""\bstate\.setdefault\(["'](\w+)["']""")
_QUOTED_FILE = re.compile(r"""["']([\w.-]+\.(?:jsonl|json|md))["']""")
_QUOTED = re.compile(r"""["']([\w.-]+)["']""")
_MEMBER_READ = re.compile(r"\b\w+\??\.([a-z]+(?:_[a-z]+)+)\b")
# Loop-root entries that are not namespace data (archive and shared-feed directories are
# namespaces of their own kind) and scratch directories left by core's tests.
_ROOT_SKIP = re.compile(r"^(_archived|_community|v\d+-[\w-]+)$")


def _core_source():
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(CORE_PKG.glob("*.py")))


def _namespace_dirs():
    return [d for d in LOOP.iterdir() if d.is_dir() and not _ROOT_SKIP.match(d.name)]


def _read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _live_entry_keys(field):
    keys = set()
    for d in _namespace_dirs():
        for entry in _read_json(d / "state.json").get(field) or []:
            if isinstance(entry, dict):
                keys |= entry.keys()
    return keys


def _live_learning_keys():
    keys = set()
    for d in _namespace_dirs():
        try:
            lines = (d / "learnings.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                keys |= row.keys()
    return keys


def _surfaces():
    """{surface: set of names core writes}, from core source and live data."""
    src = _core_source()
    state_keys = set(_STATE_ASSIGN.findall(src)) | set(_STATE_SETDEFAULT.findall(src))
    files = set(_QUOTED_FILE.findall(src))
    for d in _namespace_dirs():
        state_keys |= _read_json(d / "state.json").keys()
        files |= {p.name for p in d.iterdir()
                  if not _ROOT_SKIP.match(p.name) and not p.name.startswith(".")}
    files |= {p.name for p in LOOP.iterdir() if p.is_file() and not p.name.startswith(".")}
    # A namespace's per-session files live under history/; the directory itself is the surface.
    return {
        "state": state_keys,
        "cycle_history": _live_entry_keys("cycle_history"),
        "quality_history": _live_entry_keys("quality_history"),
        "learnings": _live_learning_keys(),
        "files": files,
    }


def _dashboard_reads():
    template = (_SCRIPT.parent / "template.html").read_text(encoding="utf-8")
    return set(_QUOTED.findall(_SCRIPT.read_text(encoding="utf-8"))) | set(_MEMBER_READ.findall(template))


_AVAILABLE = CORE_PKG.is_dir() and LOOP.is_dir()


@unittest.skipUnless(_AVAILABLE, "compass core or ~/.claude/loop not present")
class TestSurfaceInventory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.surfaces = _surfaces()
        cls.reads = _dashboard_reads()

    def test_every_written_name_is_read_or_ignored(self):
        for surface, names in self.surfaces.items():
            with self.subTest(surface=surface):
                unaccounted = sorted(names - self.reads - IGNORED[surface].keys())
                self.assertEqual(
                    unaccounted, [],
                    f"{surface}: core writes these but the dashboard neither reads them nor "
                    f"lists them in IGNORED[{surface!r}]. Wire them in or add a reason.")

    def test_ignored_names_are_not_read(self):
        for surface, ignored in IGNORED.items():
            with self.subTest(surface=surface):
                stale = sorted(ignored.keys() & self.reads)
                self.assertEqual(
                    stale, [],
                    f"{surface}: the dashboard now reads these; remove them from IGNORED.")

    def test_ignored_names_are_still_written(self):
        for surface, ignored in IGNORED.items():
            with self.subTest(surface=surface):
                gone = sorted(ignored.keys() - self.surfaces[surface])
                self.assertEqual(
                    gone, [],
                    f"{surface}: core no longer writes these; remove them from IGNORED.")

    def test_derivation_finds_known_core_writes(self):
        """Guards the regexes: if they stop matching, every other test passes vacuously."""
        self.assertIn("goal_completions", self.surfaces["state"])
        self.assertIn("last_backlog_match", self.surfaces["state"])  # source-only: transient
        self.assertIn("learnings.jsonl", self.surfaces["files"])
        self.assertIn("history", self.surfaces["files"])
        self.assertIn("weight", self.surfaces["learnings"])
        self.assertIn("goal_completions", self.reads)
        self.assertIn("command_count", self.reads)  # template-only member read


if __name__ == "__main__":
    unittest.main()
