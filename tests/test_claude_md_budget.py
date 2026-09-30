"""
CLAUDE.md size gate.

CLAUDE.md loads on every turn, so it drifts toward a changelog unless something pushes back.
compass core's CLAUDE.md review also fires early when this file is over budget, but only when a
compass session opens — this test catches overruns at commit time too. When it fails, run the
hygiene pass described in CLAUDE.md's "Keeping this file lean" section (archive dated narratives
verbatim into docs/claude-md-history.md), don't raise the budget.

Run: python3 -m pytest tests/test_claude_md_budget.py  (or python3 -m unittest)
"""

import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_CLAUDE_MD = _ROOT / "CLAUDE.md"
_HISTORY = _ROOT / "docs" / "claude-md-history.md"

# Mirrors compass core's claude_md_size_budget_bytes default.
BUDGET_BYTES = 20_000


class ClaudeMdBudgetTest(unittest.TestCase):
    def test_claude_md_under_budget(self):
        size = _CLAUDE_MD.stat().st_size
        self.assertLessEqual(
            size, BUDGET_BYTES,
            f"CLAUDE.md is {size} bytes, over the {BUDGET_BYTES}-byte budget. Run the hygiene "
            f"pass: move dated fix narratives verbatim to docs/claude-md-history.md.",
        )

    def test_history_archive_exists_and_is_linked(self):
        self.assertTrue(_HISTORY.exists(), "docs/claude-md-history.md is missing")
        self.assertIn("docs/claude-md-history.md", _CLAUDE_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
