"""
Tests for compass-dashboard.py pure data-loading functions.
No filesystem access — all inputs are in-memory strings/dicts.

Run: python3 -m pytest tests/test_data_loading.py  (or python3 -m unittest)
"""
import hashlib
import importlib.util
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Import via importlib because the filename contains a hyphen.
_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_reality_completeness = _mod._reality_completeness
_corpus_health        = _mod._corpus_health
_goal_stats           = _mod._goal_stats
_stale_bullet_count   = _mod._stale_bullet_count


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:8]

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
_FRESH_TS  = "2026-06-15T10:00:00Z"   # 2 days ago — fresh
_STALE_TS  = "2026-05-01T10:00:00Z"   # 47 days ago — stale


# ─────────────────────────────────────────────────────────────────────────────
# _reality_completeness
# ─────────────────────────────────────────────────────────────────────────────

class TestRealityCompleteness(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(_reality_completeness(""))

    def test_no_bullets_returns_none(self):
        self.assertIsNone(_reality_completeness("## What exists\n\nSome prose, no bullets."))

    def test_all_bullets_no_markers_returns_zero(self):
        md = "## What exists\n- Thing A\n- Thing B\n"
        self.assertEqual(_reality_completeness(md), 0.0)

    def test_all_bullets_with_marker_returns_hundred(self):
        md = "## What exists\n- Feature live\n- Auth done\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_mixed_bullets(self):
        md = "## What exists\n- Feature live\n- Feature B\n- Feature C\n"
        # 1 of 3 achieved
        self.assertAlmostEqual(_reality_completeness(md), 33.3, places=1)

    def test_backlog_section_bullets_excluded(self):
        md = (
            "## What exists\n- Live thing\n"
            "## What is next\n- Pending thing\n- Another pending\n"
        )
        # Only "Live thing" counts; backlog bullets excluded
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_backlog_keyword_variants(self):
        for header in ("## Backlog", "## Planned work", "## Missing", "## Todo"):
            md = f"## What exists\n- Done thing exists and works\n{header}\n- Backlog item\n"
            score = _reality_completeness(md)
            self.assertEqual(score, 100.0, msg=f"Failed for header: {header!r}")

    def test_blank_and_underscore_bullets_excluded(self):
        md = "## What exists\n- \n- _italic note_\n- Real bullet live\n"
        # blank and underscore skipped; only "Real bullet live" counted
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_completion_marker_case_insensitive(self):
        md = "## What exists\n- Feature Shipped\n- Another COMPLETE\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_checkmark_marker(self):
        md = "## What exists\n- ✓ deployed\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_subsection_header_under_backlog_does_not_reset_in_backlog(self):
        # ### headers inside a backlog section should NOT reset in_backlog=False.
        # Regression: "### P40-Dashboard" under "## What is next" previously
        # reset in_backlog because "p40-dashboard" contains no backlog keyword.
        md = (
            "## What exists\n- Done thing live\n"
            "## What is next\n"
            "### P40-Dashboard — future phases\n"
            "- P40-D Phase 2: pending\n"
            "- P40-D Phase 3: pending\n"
        )
        # "Done thing live" counts (achieved); the two phase bullets are in backlog.
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_subsection_header_under_non_backlog_does_not_flip_in_backlog(self):
        # ### under "## What exists" should keep in_backlog=False.
        md = (
            "## What exists\n"
            "### Core features\n"
            "- Feature shipped\n"
            "- Feature B live\n"
        )
        self.assertAlmostEqual(_reality_completeness(md), 100.0)

    def test_level1_header_does_not_set_in_backlog(self):
        # A # title at the top should not affect section classification.
        md = "# Reality — myns\n## What exists\n- Thing done\n"
        self.assertEqual(_reality_completeness(md), 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# _corpus_health
# ─────────────────────────────────────────────────────────────────────────────

class TestCorpusHealth(unittest.TestCase):

    def _fact(self, weight=2):
        return {"learning_type": "fact", "weight": weight}

    def _hyp(self, validated=False, weight=2):
        l = {"learning_type": "hypothesis", "weight": weight}
        if validated:
            l["validation_result"] = "confirmed"
        return l

    def test_fewer_than_three_learnings_returns_none(self):
        self.assertIsNone(_corpus_health([], 0))
        self.assertIsNone(_corpus_health([self._fact(), self._fact()], 0))

    def test_all_facts_high_weight_returns_high_score(self):
        learnings = [self._fact(weight=3)] * 5
        result = _corpus_health(learnings, 0)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["score"], 90)

    def test_unvalidated_hypotheses_reduce_score(self):
        all_facts = [self._fact()] * 4 + [self._hyp(validated=True)]
        with_unvalidated = [self._fact()] * 4 + [self._hyp(validated=False)]
        score_clean   = _corpus_health(all_facts, 0)["score"]
        score_unclean = _corpus_health(with_unvalidated, 0)["score"]
        self.assertGreater(score_clean, score_unclean)

    def test_high_low_weight_ratio_reduces_score(self):
        high_weight = [self._fact(weight=3)] * 5
        low_weight  = [self._fact(weight=1)] * 5
        score_high = _corpus_health(high_weight, 0)["score"]
        score_low  = _corpus_health(low_weight, 0)["score"]
        self.assertGreater(score_high, score_low)

    def test_superseded_count_adds_small_bonus(self):
        learnings = [self._fact()] * 5
        score_no_sup  = _corpus_health(learnings, 0)["score"]
        score_with_sup = _corpus_health(learnings, 3)["score"]
        self.assertGreaterEqual(score_with_sup, score_no_sup)

    def test_score_clamped_between_0_and_100(self):
        # Worst case: all unvalidated hypotheses, all weight-1
        learnings = [self._hyp(validated=False, weight=1)] * 5
        result = _corpus_health(learnings, 0)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_returned_fields_present(self):
        learnings = [self._fact()] * 4
        result = _corpus_health(learnings, 2)
        for key in ("score", "unvalidatedHypotheses", "lowWeightCount", "totalActive", "supersededCount"):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_counts_correct(self):
        learnings = [self._fact(weight=1), self._hyp(validated=False), self._fact(weight=2)]
        result = _corpus_health(learnings, 1)
        self.assertEqual(result["totalActive"], 3)
        self.assertEqual(result["unvalidatedHypotheses"], 1)
        self.assertEqual(result["lowWeightCount"], 1)
        self.assertEqual(result["supersededCount"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# _goal_stats
# ─────────────────────────────────────────────────────────────────────────────

class TestGoalStats(unittest.TestCase):

    def test_empty_state_returns_none_and_empty_dots(self):
        rate, dots = _goal_stats({})
        self.assertIsNone(rate)
        self.assertEqual(dots, [])

    def test_empty_completions_returns_none(self):
        rate, dots = _goal_stats({"goal_completions": {}})
        self.assertIsNone(rate)
        self.assertEqual(dots, [])

    def test_dict_format_entries(self):
        state = {"goal_completions": {
            "2026-06-01T10:00:00Z": {"total_goals": 4, "hit_rate": 100},
            "2026-06-02T10:00:00Z": {"total_goals": 3, "hit_rate": 67},
        }}
        rate, dots = _goal_stats(state)
        self.assertEqual(rate, 67)
        self.assertEqual(len(dots), 2)
        self.assertEqual(dots[0]["level"], "high")
        self.assertEqual(dots[1]["level"], "mid")

    def test_legacy_list_format_entries(self):
        # Old format: list of status strings
        state = {"goal_completions": {
            "2026-06-01T10:00:00Z": ["completed", "completed", "completed", "abandoned"],
        }}
        rate, dots = _goal_stats(state)
        self.assertEqual(rate, 75)
        self.assertEqual(dots[0]["level"], "mid")

    def test_capped_at_last_5_sessions(self):
        # 7 sessions — only last 5 should appear in dots
        completions = {}
        for i in range(7):
            key = f"2026-06-{i+1:02d}T10:00:00Z"
            completions[key] = {"total_goals": 1, "hit_rate": 100}
        _, dots = _goal_stats({"goal_completions": completions})
        self.assertEqual(len(dots), 5)

    def test_low_hit_rate_dot_level(self):
        state = {"goal_completions": {
            "2026-06-01T10:00:00Z": {"total_goals": 2, "hit_rate": 40},
        }}
        _, dots = _goal_stats(state)
        self.assertEqual(dots[0]["level"], "low")

    def test_zero_total_goals_returns_none_rate(self):
        state = {"goal_completions": {
            "2026-06-01T10:00:00Z": {"total_goals": 0, "hit_rate": 0},
        }}
        rate, dots = _goal_stats(state)
        self.assertIsNone(rate)


# ─────────────────────────────────────────────────────────────────────────────
# _stale_bullet_count
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleBulletCount(unittest.TestCase):

    def _make_state(self, bullets_and_timestamps):
        """Build a state dict with reality_validation entries.
        bullets_and_timestamps: list of (text, ts_or_None)
        """
        validation = {}
        for text, ts in bullets_and_timestamps:
            h = _hash(text)
            if ts:
                validation[h] = ts
        return {"reality_validation": validation}

    def _make_md(self, bullets):
        return "## What exists\n" + "".join(f"- {b}\n" for b in bullets)

    def test_empty_reality_returns_zero(self):
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count("", {}, days=30), 0)

    def test_never_verified_bullet_is_stale(self):
        md = self._make_md(["Some feature"])
        state = self._make_state([("Some feature", None)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 1)

    def test_freshly_verified_bullet_not_stale(self):
        md = self._make_md(["Some feature"])
        state = self._make_state([("Some feature", _FRESH_TS)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 0)

    def test_old_verified_bullet_is_stale(self):
        md = self._make_md(["Some feature"])
        state = self._make_state([("Some feature", _STALE_TS)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 1)

    def test_mixed_bullets(self):
        bullets = ["Fresh feature", "Stale feature", "Never verified"]
        state = self._make_state([
            ("Fresh feature", _FRESH_TS),
            ("Stale feature", _STALE_TS),
            ("Never verified", None),
        ])
        md = self._make_md(bullets)
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 2)

    def test_blank_and_underscore_bullets_excluded(self):
        md = "## What exists\n- \n- _italic_\n- Real bullet\n"
        state = self._make_state([("Real bullet", None)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 1)

    def test_custom_days_threshold(self):
        # With days=1, the "fresh" timestamp (2 days ago) becomes stale
        md = self._make_md(["Some feature"])
        state = self._make_state([("Some feature", _FRESH_TS)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=1), 1)

    def test_empty_validation_dict_all_stale(self):
        md = self._make_md(["Feature A", "Feature B"])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, {}, days=30), 2)


if __name__ == "__main__":
    unittest.main()
