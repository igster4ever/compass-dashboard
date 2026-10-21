"""
Live parity: the dashboard's baked `pulse` object vs `compass.py pulse <ns>` (Live strip, spec
docs/superpowers/specs/2026-10-12-live-strip-design.md).

The strip bakes one `pulse` per namespace at generation time, using the same field names as
core's read-only `pulse` command. The dashboard can't import compass, so `_build_pulse()` is a
mirror; this suite compares it field by field against the real command on every live namespace
in ~/.claude/loop. Skipped when core or the loop data is absent (CI, fresh machine).

Cadences compare against pulse's *cheap gates* (no git complexity pull-forward), by decision:
the strip answers "what does pulse say?", so it must not inherit the ORIENT brief's wider view.

When a case fails, core has changed: port the change, don't loosen the test.
Written test-first: until `dash._build_pulse` exists every case fails with a clear message.

Run: python3 -m pytest tests/test_pulse_parity.py -v
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
dash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dash)

CORE_SCRIPTS = Path.home() / ".claude" / "skills" / "compass" / "scripts"
LOOP = Path.home() / ".claude" / "loop"

# Compared exactly. `now` and `elapsed_seconds` are time-dependent and handled separately;
# `resolved_by` is a property of the CLI call, not of the namespace.
EXACT_FIELDS = (
    "namespace", "phase", "open_session", "last_open", "last_close", "close_phase_started_at",
    "typical_minutes", "goals", "reality_changes", "reality_delta", "cadences", "quality", "git",
)
ELAPSED_TOLERANCE_S = 5


def _core_pulse(ns, loop_dir=None):
    """`compass.py pulse <ns>` parsed, or None when it can't run here. `loop_dir` points core
    at a fixture loop via COMPASS_LOOP_DIR instead of ~/.claude/loop."""
    env = dict(os.environ, COMPASS_LOOP_DIR=str(loop_dir)) if loop_dir else None
    try:
        p = subprocess.run([sys.executable, str(CORE_SCRIPTS / "compass.py"), "pulse", ns],
                           capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def _namespace_dirs():
    return [d for d in sorted(LOOP.iterdir()) if LOOP.is_dir()
            and d.is_dir() and not d.name.startswith("_") and (d / "state.json").exists()] \
        if LOOP.is_dir() else []


def _pulse(ns_dir):
    return dash._build_pulse(ns_dir.name, dash._read_namespace_files(ns_dir))


@unittest.skipIf(not (CORE_SCRIPTS / "compass.py").exists() or not LOOP.is_dir(),
                 "compass core or live loop data not present")
class TestPulseParity(unittest.TestCase):

    def setUp(self):
        self.dirs = _namespace_dirs()
        self.assertTrue(self.dirs, "no live namespaces found")
        self.assertTrue(hasattr(dash, "_build_pulse"),
                        "dash._build_pulse(namespace, raw) not implemented yet (Live strip goal 4)")

    def _each(self):
        for d in self.dirs:
            theirs = _core_pulse(d.name)
            self.assertIsNotNone(theirs, f"compass.py pulse {d.name} did not return JSON")
            yield d, _pulse(d), theirs

    def test_exact_fields(self):
        for d, ours, theirs in self._each():
            for field in EXACT_FIELDS:
                with self.subTest(namespace=d.name, field=field):
                    self.assertIn(field, ours)
                    mine = ours[field]
                    if field == "git" and mine is not None:
                        # `errors` is dashboard-only; core's keys must still match exactly.
                        mine = {k: v for k, v in mine.items() if k != "errors"}
                    self.assertEqual(mine, theirs[field])

    def test_cadences_per_name(self):
        """Field-by-field so a drifting gate names itself instead of failing as one list."""
        for d, ours, theirs in self._each():
            by_name = {c["name"]: c for c in ours["cadences"]}
            for expected in theirs["cadences"]:
                with self.subTest(namespace=d.name, cadence=expected["name"]):
                    self.assertEqual(by_name.get(expected["name"]), expected)

    def test_elapsed_is_baked_from_generated_at(self):
        """Elapsed is only meaningful against the snapshot's own clock (spec risk 3)."""
        for d, ours, theirs in self._each():
            with self.subTest(namespace=d.name):
                self.assertIn("generated_at", ours)
                if theirs["open_session"]:
                    self.assertLessEqual(abs(ours["elapsed_seconds"] - theirs["elapsed_seconds"]),
                                         ELAPSED_TOLERANCE_S)
                else:
                    self.assertIsNone(ours["elapsed_seconds"])

    def test_building_pulse_writes_nothing(self):
        """The strip is read-only: building it must leave every namespace file untouched."""
        def snapshot():
            return {str(p): p.stat().st_mtime_ns for d in self.dirs for p in d.rglob("*") if p.is_file()}
        before = snapshot()
        for d in self.dirs:
            _pulse(d)
        self.assertEqual(snapshot(), before)


@unittest.skipIf(not (CORE_SCRIPTS / "compass.py").exists(), "compass core not present")
class TestPulseParityNestedClaudeMd(unittest.TestCase):
    """A fixture namespace whose scripts/CLAUDE.md is over budget while the root one is not.
    Live namespaces have no nested CLAUDE.md, so the live suite can't see the pulse's
    claude_review gate fall back to measuring only the root file (the 4e6f6da drift)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.loop = root / "loop"
        self.ns_dir = self.loop / "fixture-ns"
        repo = root / "repo"
        (repo / "scripts").mkdir(parents=True)
        self.ns_dir.mkdir(parents=True)
        (repo / "CLAUDE.md").write_text("x" * 4_000)
        (repo / "scripts" / "CLAUDE.md").write_text("x" * 20_001)
        (self.ns_dir / "state.json").write_text(json.dumps({
            "open_session": False, "repo_path": str(repo), "sessions_since_claude_review": 2}))
        (self.ns_dir / "config.json").write_text("{}")
        (self.ns_dir / "reality.md").write_text("# Reality\n\n## What exists and works\n\n- a thing\n")

    def test_claude_review_cadence_matches_core(self):
        theirs = _core_pulse("fixture-ns", self.loop)
        self.assertIsNotNone(theirs, "compass.py pulse fixture-ns did not return JSON")
        ours = _pulse(self.ns_dir)
        by_name = {c["name"]: c for c in ours["cadences"]}
        expected = next(c for c in theirs["cadences"] if c["name"] == "claude_review")
        self.assertTrue(expected["due"], "fixture should pull the review forward by size in core")
        self.assertEqual(by_name["claude_review"], expected)


if __name__ == "__main__":
    unittest.main()
