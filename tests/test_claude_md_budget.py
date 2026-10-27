"""
CLAUDE.md size gate.

The root CLAUDE.md loads on every turn and the nested ones load whenever their folder is read,
so each drifts toward a changelog unless something pushes back. compass core's CLAUDE.md review
also fires early when any rules file it finds by convention (root, <dir>/CLAUDE.md,
docs/claude/*.md) is over budget, but only when a compass session opens — this test catches overruns at commit time too, for every rules file. When it
fails, run the hygiene pass described in the root CLAUDE.md's "Keeping these files lean" section
(archive dated narratives verbatim into docs/claude-md-history.md), don't raise the budget.

The 2026-10-23 split (docs/backlog/claude-md-progressive-disclosure.md) moved sections out of
the root by location. The no-rule-lost tests pin every pre-split section to exactly one file, so
a later edit can move a section but not silently drop or duplicate it.

Run: python3 -m pytest tests/test_claude_md_budget.py  (or python3 -m unittest)
"""

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_CLAUDE_MD = _ROOT / "CLAUDE.md"
_HISTORY = _ROOT / "docs" / "claude-md-history.md"

# Every rules file, keyed by repo-relative path. Each gets its own budget.
_RULES_FILES = {
    "CLAUDE.md": _CLAUDE_MD,
    "scripts/CLAUDE.md": _ROOT / "scripts" / "CLAUDE.md",
    "tests/CLAUDE.md": _ROOT / "tests" / "CLAUDE.md",
    "docs/claude/views.md": _ROOT / "docs" / "claude" / "views.md",
}

# Mirrors compass core's claude_md_size_budget_bytes default.
BUDGET_BYTES = 20_000

# The level-2 sections of the pre-split root CLAUDE.md (git b229aac). Matched by prefix so a
# heading can gain a suffix ("Keeping this file lean" became "Keeping these files lean").
_PRE_SPLIT_SECTIONS = [
    "What this is",
    "Keeping th",
    "Architecture",
    "`template.html` traps",
    "Template substitution",
    "Tab system",
    "Data model",
    "Stateful view tabs",
    "View-specific rules",
    "Security",
    "Tests",
]


def _h2_headings(text):
    return [m.group(1) for m in re.finditer(r"(?m)^## (.+)$", text)]


class ClaudeMdBudgetTest(unittest.TestCase):
    def test_every_rules_file_under_budget(self):
        for rel, path in _RULES_FILES.items():
            with self.subTest(file=rel):
                self.assertTrue(path.exists(), f"{rel} is missing")
                size = path.stat().st_size
                self.assertLessEqual(
                    size, BUDGET_BYTES,
                    f"{rel} is {size} bytes, over the {BUDGET_BYTES}-byte budget. Run the hygiene "
                    f"pass: move dated fix narratives verbatim to docs/claude-md-history.md.",
                )

    def test_history_archive_exists_and_is_linked(self):
        self.assertTrue(_HISTORY.exists(), "docs/claude-md-history.md is missing")
        self.assertIn("docs/claude-md-history.md", _CLAUDE_MD.read_text(encoding="utf-8"))


class NoRuleLostTest(unittest.TestCase):
    def setUp(self):
        self.headings = {
            rel: _h2_headings(path.read_text(encoding="utf-8"))
            for rel, path in _RULES_FILES.items()
        }

    def test_each_pre_split_section_lives_in_exactly_one_file(self):
        for section in _PRE_SPLIT_SECTIONS:
            with self.subTest(section=section):
                homes = [
                    rel for rel, hs in self.headings.items()
                    for h in hs if h.startswith(section)
                ]
                self.assertEqual(
                    len(homes), 1,
                    f"section {section!r} found in {homes or 'no file'}; it must be in exactly one "
                    f"of {list(_RULES_FILES)}",
                )

    def test_root_maps_every_nested_file(self):
        root = _CLAUDE_MD.read_text(encoding="utf-8")
        for rel in _RULES_FILES:
            if rel == "CLAUDE.md":
                continue
            with self.subTest(file=rel):
                self.assertIn(f"]({rel})", root, f"root CLAUDE.md has no link to {rel}")

    def test_scripts_rules_point_to_views_doc(self):
        # views.md never auto-loads; this pointer is the only way Claude reaches it.
        scripts = _RULES_FILES["scripts/CLAUDE.md"].read_text(encoding="utf-8")
        self.assertIn("](../docs/claude/views.md)", scripts)
        self.assertIn("read its section", scripts)


if __name__ == "__main__":
    unittest.main()
