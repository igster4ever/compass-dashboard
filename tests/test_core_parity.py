"""
Live parity: every compass-core logic mirror in compass-dashboard.py vs compass core itself.

The dashboard can't import compass (stdlib-only, separate repo), so it keeps local copies of
core's gates and scoring. Three side-by-side audits (2026-08-30, 09-11, 09-30) each found
drift, including a phantom dream_due gate that survived two of them. This suite replaces the
manual audit: it imports core from ~/.claude/skills/compass/scripts and compares both sides on
every live namespace in ~/.claude/loop. Skipped when either is absent (CI, fresh machine).

When you mirror a new piece of core logic, add a case here. When a case fails, core has
changed: port the change, don't loosen the test.

Run: python3 -m pytest tests/test_core_parity.py -v
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
dash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dash)

CORE_SCRIPTS = Path.home() / ".claude" / "skills" / "compass" / "scripts"
LOOP = Path.home() / ".claude" / "loop"


def _load_core():
    if not (CORE_SCRIPTS / "compass" / "reality.py").exists():
        return None
    sys.path.insert(0, str(CORE_SCRIPTS))
    try:
        from compass import dream, learnings, orient, reality, research, skillopt, state
    except ImportError:
        return None
    finally:
        sys.path.remove(str(CORE_SCRIPTS))
    return {"dream": dream, "learnings": learnings, "orient": orient, "reality": reality,
            "research": research, "skillopt": skillopt, "state": state}


core = _load_core()


def _read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_jsonl(p):
    try:
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def _namespaces():
    """(name, ns_dir, state, config, reality_md) for every live namespace."""
    out = []
    for d in sorted(LOOP.iterdir()) if LOOP.is_dir() else []:
        if not d.is_dir() or d.name.startswith("_") or not (d / "state.json").exists():
            continue
        md_path = d / "reality.md"
        md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        out.append((d.name, d, _read_json(d / "state.json"), _read_json(d / "config.json"), md))
    return out


@unittest.skipIf(core is None or not LOOP.is_dir(), "compass core or live loop data not present")
class TestCoreParity(unittest.TestCase):

    def setUp(self):
        self.namespaces = _namespaces()
        self.assertTrue(self.namespaces, "no live namespaces found")

    def _each(self):
        for ns in self.namespaces:
            with self.subTest(namespace=ns[0]):
                yield ns

    # ── reality.md scoring ──────────────────────────────────────────────────

    def test_reality_completeness(self):
        for name, _, _, _, md in self._each():
            self.assertEqual(dash._reality_completeness(md),
                             core["reality"]._compute_reality_completeness(md, {})["score"])

    def test_stale_bullet_count(self):
        for name, _, state, _, md in self._each():
            self.assertEqual(dash._stale_bullet_count(md, state),
                             len(core["reality"]._get_stale_bullets(md, state)))

    def test_reality_bullet_hashes(self):
        # Goal-outcome links and verification records are keyed by these hashes.
        for name, _, _, _, md in self._each():
            dash_hashes = [dash.hashlib.sha256(t.encode()).hexdigest()[:8]
                           for t, _ in dash._iter_reality_bullets(md)]
            self.assertEqual(dash_hashes, [h for h, _ in core["reality"]._parse_reality_bullets(md)])

    def test_marker_and_header_sets(self):
        for attr in ("_COMPLETION_MARKERS", "_BACKLOG_HEADERS", "_NON_ACHIEVEMENT_HEADERS"):
            with self.subTest(constant=attr):
                self.assertEqual(getattr(dash, attr), getattr(core["reality"], attr))

    # ── cadence gates ───────────────────────────────────────────────────────

    def test_dream_due(self):
        for name, _, state, config, _ in self._each():
            self.assertEqual(dash._check_dream_due(state, config)[0],
                             core["dream"]._check_dream_due(state, config)["due"])

    def test_claude_review_due(self):
        for name, d, state, config, _ in self._each():
            ours = dash._check_claude_review_due(d, state, config, state.get("repo_path", ""))
            theirs = core["orient"]._check_claude_review_due(
                state, config, core["orient"]._resolve_claude_md_path(state, name))
            # Core reports cadence-due even with no CLAUDE.md; its skill step then resets
            # the counter and skips. The dashboard folds that "no file" case into due=False.
            if ours["claude_md_bytes"] is not None:
                self.assertEqual(ours["due"], theirs["due"])
            self.assertEqual(ours["pulled_forward_by_size"], theirs["pulled_forward_by_size"])
            self.assertEqual(ours["claude_md_bytes"], theirs["claude_md_bytes"])

    def test_research_due(self):
        for name, d, state, config, _ in self._each():
            signals = core["orient"]._get_complexity_clustering_signals(d)
            ours_signals = dash._complexity_clustering_signals(_read_jsonl(d / "decisions.jsonl"))
            self.assertEqual(ours_signals, signals)
            self.assertEqual(dash._check_research_due(state, config, ours_signals)[0],
                             core["research"]._check_research_due(state, config, signals)["due"])

    def test_code_review_due(self):
        for name, d, state, config, _ in self._each():
            ours_due, ours_status = dash._check_code_review_due(d, state, config)
            theirs = core["orient"]._check_review_due(
                state, config, core["orient"]._get_review_complexity_signal(d, state, config))
            self.assertEqual(ours_due, theirs["due"])
            self.assertEqual(ours_status["pulled_forward_by_complexity"],
                             theirs.get("pulled_forward_by_complexity", False))

    def test_skill_opt_due(self):
        # The dashboard computes this inline in _assemble_namespace_dict(); compare the
        # assembled namespace dict rather than a helper.
        for name, d, state, config, _ in self._each():
            self.assertEqual(dash.load_namespace(d)["skill_opt_due"],
                             core["skillopt"]._check_skill_opt_due(state, config)["due"])

    def test_assumption_audit_due(self):
        for name, d, state, config, _ in self._each():
            self.assertEqual(
                dash._check_assumption_audit_due(state, config, _read_jsonl(d / "learnings.jsonl"))[0],
                core["orient"]._check_assumption_audit_due(state, config)["due"])

    def test_quality_plateau(self):
        for name, _, state, _, _ in self._each():
            ours = dash._check_quality_plateau(state.get("quality_history", []))
            theirs = core["state"]._get_quality_plateau_signal(state)
            self.assertEqual(ours["plateaued"], theirs["plateaued"])

    # ── corpus / goal statistics ────────────────────────────────────────────

    def test_confidence_calibration(self):
        for name, d, _, _, _ in self._each():
            learnings = _read_jsonl(d / "learnings.jsonl")
            self.assertEqual(dash._compute_confidence_calibration(learnings),
                             core["learnings"]._compute_confidence_calibration(learnings))

    def test_contract_coverage(self):
        for name, _, state, _, _ in self._each():
            self.assertEqual(dash._contract_coverage(state),
                             core["state"]._compute_contract_coverage(state))


if __name__ == "__main__":
    unittest.main()
