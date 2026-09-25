"""
End-to-end integration test: synthetic namespace directory -> load_namespace()
-> _js_data()/generate().

Closes the seam every other test suite leaves open: test_data_loading.py exercises
load_namespace() with tempdir fixtures, and test_generate.py exercises _js_data()/
generate() against a hand-typed minimal dict — but nothing runs a real on-disk
namespace through the *whole* pipeline. That gap is exactly where past shape-drift
bugs landed with no automated check (2026-07-22 KeyError incidents; see CLAUDE.md's
"New _js_data() fields must use n.get('field'), never n['field']" note) — a new
_js_data() field that bracket-indexes a key load_namespace() doesn't actually set
only throws when real load_namespace() output flows through it, which none of the
other suites do.

Run: python3 -m pytest tests/test_integration_pipeline.py  (or python3 -m unittest)
"""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

# Import via importlib because the filename contains a hyphen.
_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _write_synthetic_namespace(root, name="synthetic-ns"):
    """Build a real, on-disk namespace directory exercising the non-empty path of
    every major load_namespace() input: state.json, intent.md, reality.md,
    learnings.jsonl, decisions.jsonl, code_context.md, and a history/ session file.
    Returns the namespace directory Path.
    """
    ns_dir = Path(root) / name
    ns_dir.mkdir(parents=True)
    (ns_dir / "history").mkdir()

    (ns_dir / "state.json").write_text(json.dumps({
        "open_session": False,
        "last_close": "2026-09-20T09:00:00Z",
        "last_open": "2026-09-20T08:00:00Z",
        "planned_actions": ["Ship the thing"],
        "deferred_opportunities": {
            "some-feature": {"defer_count": 1, "reason": "not enough signal yet"},
        },
        "goal_completions": {
            "2026-09-20": {"hit_rate": 100.0, "total_goals": 2, "statuses": ["done", "done"]},
        },
        "cycle_history": [{"opened_at": "2026-09-20T08:00:00Z", "closed_at": "2026-09-20T09:00:00Z", "minutes": 60}],
        "last_cycle_minutes": 60,
        "sessions_since_dream": 1,
        "intent_versions": 1,
        "outcome_rate": 0.5,
        "sessions_since_skill_opt": 1,
        "quality_history": [{"session_id": "s1", "score": 0.9}],
    }, indent=2), encoding="utf-8")

    (ns_dir / "intent.md").write_text(
        "This namespace exists to prove the pipeline works end to end.\n",
        encoding="utf-8",
    )
    (ns_dir / "reality.md").write_text(
        "## What exists and works\n"
        "- Thing one is shipped ✅\n"
        "- Thing two is still in progress\n"
        "\n## Backlog\n\n### Tactical\n- A tactical item\n\n### Strategic\n- A strategic item\n",
        encoding="utf-8",
    )
    (ns_dir / "learnings.jsonl").write_text(
        "\n".join(json.dumps(l) for l in [
            {"text": "A golden learning worth replicating.", "tags": ["tooling"],
             "weight": 3, "zone": "golden", "learning_type": "fact",
             "confidence": "high", "status": "active"},
            {"text": "A hypothesis still open.", "tags": ["testing"], "weight": 1,
             "learning_type": "hypothesis", "confidence": "medium", "status": "active"},
        ]) + "\n",
        encoding="utf-8",
    )
    (ns_dir / "decisions.jsonl").write_text(
        json.dumps({
            "decision": "Use vanilla JS, no framework",
            "rationale": "Keeps the file self-contained",
            "alternatives": "React, Vue",
            "date": "2026-09-01T00:00:00Z",
        }) + "\n",
        encoding="utf-8",
    )
    (ns_dir / "code_context.md").write_text(
        "**Last updated:** 2026-09-20\nSomething useful for next time.\n",
        encoding="utf-8",
    )
    (ns_dir / "history" / "2026-09-20T0800.md").write_text(
        "**Opened:** 2026-09-20T08:00:00Z\n"
        "**Closed:** 2026-09-20T09:00:00Z\n\n"
        "## Planned\n- Ship the thing\n\n"
        "## Completed\n- Ship the thing\n\n"
        "## Incomplete\n(none)\n\n"
        "## Notes\nWent fine.\n",
        encoding="utf-8",
    )

    return ns_dir


class TestFullPipelineRealLoadNamespace(unittest.TestCase):
    """Runs a synthetic on-disk namespace through load_namespace() -> _js_data()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ns_dir = _write_synthetic_namespace(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_js_data_produces_valid_json(self):
        ns = _mod.load_namespace(self.ns_dir)
        # _js_data() never raising is the seam this test exists to catch: a new
        # field added there via n["field"] (rather than n.get("field")) throws
        # KeyError the moment load_namespace() doesn't actually populate that key.
        raw = _mod._js_data([ns])
        # Undo the </script>/<!-- escaping _js_data() applies for safe embedding
        # before parsing, mirroring how the browser's own JS would receive it.
        unescaped = raw.replace(r"<\/script>", "</script>").replace(r"<\!--", "<!--")
        parsed = json.loads(unescaped)
        self.assertEqual(len(parsed), 1)

    def test_every_expected_top_level_key_is_present(self):
        ns = _mod.load_namespace(self.ns_dir)
        raw = _mod._js_data([ns])
        unescaped = raw.replace(r"<\/script>", "</script>").replace(r"<\!--", "<!--")
        entry = json.loads(unescaped)[0]

        expected_keys = {
            "namespace", "open", "lastClose", "lastOpen", "intentSummary", "intent",
            "reality", "learnings", "decisions", "codeContext", "history",
            "sessionDates", "goalRate", "goalDots", "topTags", "deferred",
            "goalByMonth", "sessionCount", "plannedActions", "supersededCount",
            "cycleHistory", "lastCycleMinutes", "sessionsSinceDream", "dreamDue",
            "realityCompletenessScore", "suggestedGoalCount", "researchDue",
            "researchStatus", "codeReviewDue", "codeReviewStatus", "watches",
            "watchSignals", "intentVersion", "staleBulletCount", "backRefsByText",
            "conflictsByText", "intentHistory", "corpusHealth", "zoneDistribution",
            "confidenceCalibration", "retrievalStaleCount", "externalSignals",
            "explorationRatio", "lastRealityScore", "outcomeRate", "goalOutcomes",
            "contracts", "contractCoverage", "criteriaHitRate", "decisionGuidance",
            "goalTypeBySession", "carryForwardTrend", "qualityDist", "decayHistory",
            "codeReviewDeferCount", "researchDeferCount", "artefacts", "skillFeedback",
            "failureDimensionDistribution", "sessionsSinceSkillOpt", "skillOptDue",
            "qualityHistory", "skilloptHoldoutFrozen", "skilloptHoldoutMean",
            "skilloptRoundsCompleted", "skilloptRwi", "qualityPlateau",
            "cadencePullForward", "skillOptFrictionGate", "assumptionAuditDue",
            "assumptionAuditCandidates", "claudeReviewDue", "dreamDeferCount",
            "complexityClusteringSignals", "mindmap",
        }
        missing = expected_keys - set(entry.keys())
        self.assertEqual(missing, set(), f"_js_data() dropped expected keys: {missing}")

    def test_namespace_name_and_content_survive_the_pipeline(self):
        ns = _mod.load_namespace(self.ns_dir)
        raw = _mod._js_data([ns])
        unescaped = raw.replace(r"<\/script>", "</script>").replace(r"<\!--", "<!--")
        entry = json.loads(unescaped)[0]

        self.assertEqual(entry["namespace"], "synthetic-ns")
        self.assertEqual(len(entry["learnings"]), 2)
        self.assertEqual(len(entry["decisions"]), 1)
        self.assertEqual(entry["sessionCount"], 1)
        self.assertTrue(entry["intentSummary"].startswith("This namespace exists"))

    def test_generate_produces_full_html_with_embedded_json(self):
        ns = _mod.load_namespace(self.ns_dir)
        html = _mod.generate([ns])

        self.assertIn("<!DOCTYPE", html)
        self.assertIn("</html>", html)
        self.assertIn("const NS = [", html)

        match = re.search(r"const NS = (\[.*?\]);\s*\n", html, re.DOTALL)
        self.assertIsNotNone(match, "could not locate embedded const NS = [...] block")
        parsed = json.loads(match.group(1))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["namespace"], "synthetic-ns")


class TestFullPipelineMinimalNamespace(unittest.TestCase):
    """A namespace directory with only state.json (every other file absent) must
    still flow through the whole pipeline without raising — the defaults every
    _read_file/_read_json/_read_jsonl helper falls back to must be _js_data()-safe,
    not just load_namespace()-safe.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ns_dir = Path(self._tmpdir.name) / "bare-ns"
        self.ns_dir.mkdir(parents=True)
        (self.ns_dir / "state.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_bare_namespace_round_trips_without_error(self):
        ns = _mod.load_namespace(self.ns_dir)
        raw = _mod._js_data([ns])
        unescaped = raw.replace(r"<\/script>", "</script>").replace(r"<\!--", "<!--")
        entry = json.loads(unescaped)[0]
        self.assertEqual(entry["namespace"], "bare-ns")
        self.assertEqual(entry["learnings"], [])
        self.assertEqual(entry["decisions"], [])

    def test_bare_namespace_generates_full_html(self):
        ns = _mod.load_namespace(self.ns_dir)
        html = _mod.generate([ns])
        self.assertIn("<!DOCTYPE", html)
        self.assertIn("</html>", html)


if __name__ == "__main__":
    unittest.main()
