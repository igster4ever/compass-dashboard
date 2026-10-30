"""
Tests for compass-dashboard.py pure data-loading functions.
No filesystem access — all inputs are in-memory strings/dicts.

Run: python3 -m pytest tests/test_data_loading.py  (or python3 -m unittest)
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Import via importlib because the filename contains a hyphen.
_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_reality_completeness  = _mod._reality_completeness
_corpus_health         = _mod._corpus_health
_goal_stats            = _mod._goal_stats
_suggested_goal_count  = _mod._suggested_goal_count
_stale_bullet_count    = _mod._stale_bullet_count
_retrieval_stale_texts = _mod._retrieval_stale_texts
_load_watch_signals    = _mod._load_watch_signals
_normalize_confidence  = _mod._normalize_confidence
_zone_distribution     = _mod._zone_distribution
_compute_confidence_calibration = _mod._compute_confidence_calibration
_failure_dimension_distribution = _mod._failure_dimension_distribution


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

    def test_blank_bullet_excluded_underscore_bullet_counted(self):
        # 2026-09-11 fix (mirrors compass core's da6a012, 2026-09-07): the old
        # `startswith("_")` check was dead code intended to filter cmd_init's stub
        # reality.md, but that stub line has no "- "/"* " prefix at all, so it never
        # reached this branch — the check only ever matched a *real* bullet that
        # happens to start with an underscore (e.g. naming a private Python function),
        # silently excluding it from the completeness denominator.
        md = "## What exists\n- \n- _private_helper is complete and shipped\n- Real bullet live\n"
        # blank still skipped; both real bullets now counted, both carry a marker
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_underscore_bullet_without_marker_lowers_score(self):
        md = "## What exists\n- _private_helper does a thing\n- Real bullet live\n"
        # underscore-prefixed bullet now counted but has no completion marker
        self.assertEqual(_reality_completeness(md), 50.0)

    def test_completion_marker_case_insensitive(self):
        md = "## What exists\n- Feature Shipped\n- Another COMPLETE\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_checkmark_marker(self):
        md = "## What exists\n- ✓ deployed\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_check_mark_emoji_marker(self):
        # Real reality.md files use ✅ (U+2705), not ✓ (U+2713) — 2026-08-30 audit found
        # this halved reported scores in namespaces that only use the emoji.
        md = "## What exists\n- ✅ deployed\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_mixed_ascii_and_emoji_checkmarks(self):
        md = "## What exists\n- ✓ thing one\n- ✅ thing two\n- thing three\n"
        self.assertAlmostEqual(_reality_completeness(md), 66.7, places=1)

    def test_non_achievement_keyword_variants(self):
        for header in ("## What is blocked", "## Known limitations", "## Known doc staleness"):
            md = f"## What exists\n- Done thing exists and works\n{header}\n- Excluded item\n"
            score = _reality_completeness(md)
            self.assertEqual(score, 100.0, msg=f"Failed for header: {header!r}")

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


class TestRealityCompletenessSectionAware(unittest.TestCase):
    """Mirror of compass core's section-aware P22 (reality.py, 2026-09-30): every bullet
    under an H2 carrying a completion marker counts as achieved; ### inherits; exclusion
    beats the header marker. Keep in lockstep with scripts/tests/test_reality.py upstream."""

    def test_bullets_under_what_exists_and_works_count_as_achieved(self):
        self.assertEqual(_reality_completeness("## What exists and works\n- A\n- B\n"), 100.0)

    def test_subheaders_inherit_the_achieved_section(self):
        md = "## What exists and works\n### Tabs\n- Tab A\n### Data model\n- field x\n"
        self.assertEqual(_reality_completeness(md), 100.0)

    def test_plain_section_still_scores_per_bullet(self):
        self.assertEqual(_reality_completeness("## Platform\n- Service A shipped\n- Service B\n"), 50.0)

    def test_marker_in_header_does_not_override_backlog_exclusion(self):
        md = "## What exists and works\n- A\n## Phase 2 — complete\n- B\n## Platform\n- C\n"
        self.assertEqual(_reality_completeness(md), 50.0)


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
# _retrieval_stale_texts (P58)
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrievalStaleTexts(unittest.TestCase):

    def _learning(self, text="t", weight=1, times_surfaced=0, learning_type="fact"):
        return {"text": text, "weight": weight, "times_surfaced": times_surfaced, "learning_type": learning_type}

    def test_below_threshold_not_flagged(self):
        learnings = [self._learning(times_surfaced=9)]
        self.assertEqual(_retrieval_stale_texts(learnings), set())

    def test_at_threshold_flagged(self):
        learnings = [self._learning(text="a", times_surfaced=10)]
        self.assertEqual(_retrieval_stale_texts(learnings), {"a"})

    def test_weight_above_one_excluded(self):
        learnings = [self._learning(text="a", weight=2, times_surfaced=20)]
        self.assertEqual(_retrieval_stale_texts(learnings), set())

    def test_hypothesis_excluded(self):
        learnings = [self._learning(text="a", times_surfaced=20, learning_type="hypothesis")]
        self.assertEqual(_retrieval_stale_texts(learnings), set())

    def test_custom_threshold(self):
        learnings = [self._learning(text="a", times_surfaced=4)]
        self.assertEqual(_retrieval_stale_texts(learnings, surfaced_threshold=5), set())
        self.assertEqual(_retrieval_stale_texts(learnings, surfaced_threshold=4), {"a"})

    def test_mixed_corpus_returns_only_matching(self):
        learnings = [
            self._learning(text="stale", times_surfaced=15),
            self._learning(text="fresh", times_surfaced=2),
            self._learning(text="heavy", weight=3, times_surfaced=15),
        ]
        self.assertEqual(_retrieval_stale_texts(learnings), {"stale"})


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

class TestSuggestedGoalCount(unittest.TestCase):
    """Mirrors compass core's trailing-window suggestion (state._get_goal_completion_trend
    feeding orient._compute_suggested_goal_count): the LAST FIVE sessions by timestamp, the
    average rounded to one decimal BEFORE the 80/60 thresholds, fractional hit rates kept."""

    @staticmethod
    def _state(rates):
        """Oldest first; ISO timestamps sort chronologically."""
        return {"goal_completions": {
            f"2026-10-{i + 1:02d}T09:00:00Z": {"hit_rate": r, "total_goals": 5}
            for i, r in enumerate(rates)}}

    def test_no_history_uses_the_default(self):
        self.assertEqual(_suggested_goal_count({}),
                         {"count": 4, "basis": "no history \u2014 using default"})

    def test_averages_only_the_five_most_recent_sessions(self):
        # Three old 0% sessions must not drag down five strong recent ones.
        result = _suggested_goal_count(self._state([0, 0, 0, 100, 100, 100, 100, 100]))
        self.assertEqual(result["count"], 5)
        self.assertIn("(100.0%)", result["basis"])

    def test_window_follows_timestamps_not_insertion_order(self):
        newest_first = dict(reversed(list(self._state([0, 0, 0, 100, 100, 100, 100, 100])["goal_completions"].items())))
        result = _suggested_goal_count({"goal_completions": newest_first})
        self.assertEqual(result["count"], 5)
        self.assertIn("(100.0%)", result["basis"])

    def test_fractional_hit_rates_are_not_truncated(self):
        result = _suggested_goal_count(self._state([83.3] * 5))
        self.assertIn("(83.3%)", result["basis"])

    def test_average_is_rounded_to_one_decimal_before_the_threshold(self):
        # 79.96 rounds to 80.0, so core suggests 5 goals; an unrounded compare would say 4.
        result = _suggested_goal_count(self._state([79.96] * 5))
        self.assertEqual(result["count"], 5)
        self.assertIn("(80.0%)", result["basis"])

    def test_calibrated_band_is_sixty_to_below_eighty(self):
        self.assertEqual(_suggested_goal_count(self._state([60] * 5))["count"], 4)
        self.assertEqual(_suggested_goal_count(self._state([79] * 5))["count"], 4)

    def test_below_sixty_reduces_scope(self):
        result = _suggested_goal_count(self._state([59] * 5))
        self.assertEqual(result["count"], 3)
        self.assertIn("reduce scope", result["basis"])

    def test_a_legacy_list_entry_does_not_raise(self):
        state = {"goal_completions": {"2026-10-01T09:00:00Z": ["completed", "blocked"]}}
        self.assertEqual(_suggested_goal_count(state)["count"], 3)  # 50% -> reduce scope


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

    def test_backlog_bullets_never_stale(self):
        # Mirrors compass core's _get_stale_bullets (2026-10-02): any H2 containing
        # "backlog" is pending work; ### subsections inherit, other sections still count.
        md = ("## What exists\n- Shipped\n## Backlog\n### Tactical\n- Todo\n"
              "## Known limitations\n- Limit\n")
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, {}, days=30), 2)

    def test_old_verified_bullet_is_stale(self):
        md = self._make_md(["Some feature"])
        state = self._make_state([("Some feature", _STALE_TS)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 1)

    def test_p66_dict_shape_freshly_verified_not_stale(self):
        # compass P66 (2026-07-28) writes {"verified_at", "confidence"} instead of a bare
        # ISO string; this must not silently read as "not stale" forever via a swallowed
        # AttributeError in _parse_iso.
        md = self._make_md(["Some feature"])
        state = {"reality_validation": {
            _hash("Some feature"): {"verified_at": _FRESH_TS, "confidence": 1.0},
        }}
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 0)

    def test_p66_dict_shape_old_verified_bullet_is_stale(self):
        md = self._make_md(["Some feature"])
        state = {"reality_validation": {
            _hash("Some feature"): {"verified_at": _STALE_TS, "confidence": 0.6},
        }}
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

    def test_blank_bullet_excluded_underscore_bullet_counted(self):
        # 2026-09-11 fix (mirrors compass core's da6a012): underscore-prefixed bullets
        # are real bullets, not stub placeholders — only blank lines are skipped.
        md = "## What exists\n- \n- _private_helper\n- Real bullet\n"
        state = self._make_state([("Real bullet", None), ("_private_helper", None)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 2)

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

    def test_partial_day_past_threshold_not_stale(self):
        # compass core's _get_stale_bullets decays confidence on whole days
        # ((now - verified_at).days), so 30 days + a few hours is still day 30 -> not
        # stale. A raw timedelta comparison wrongly flagged these (24 bullets verified
        # in one batch on compass, 2026-09-30).
        md = self._make_md(["Edge feature"])
        ts = (_NOW - timedelta(days=30, hours=5)).isoformat()
        state = self._make_state([("Edge feature", ts)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 0)

    def test_thirty_one_whole_days_is_stale(self):
        md = self._make_md(["Old feature"])
        ts = (_NOW - timedelta(days=31, minutes=1)).isoformat()
        state = self._make_state([("Old feature", ts)])
        with patch.object(_mod, "_now_utc", return_value=_NOW):
            self.assertEqual(_stale_bullet_count(md, state, days=30), 1)



# ─────────────────────────────────────────────────────────────────────────────
# Reality compaction cadence + verification durability
# ─────────────────────────────────────────────────────────────────────────────

class TestMindmapData(unittest.TestCase):
    """E25a — _mindmap_data() hierarchy builder."""

    _mindmap = staticmethod(_mod._mindmap_data)

    def _ns(self, **overrides):
        base = {
            "namespace":  "test-ns",
            "learnings":  [],
            "decisions":  [],
            "history":    [],
            "reality":    "",
            "artefacts":  [],
        }
        base.update(overrides)
        return base

    # ── Root node ─────────────────────────────────────────────────────────────

    def test_root_node_structure(self):
        mm = self._mindmap(self._ns())
        self.assertEqual(mm["id"],    "root")
        self.assertEqual(mm["type"],  "root")
        self.assertEqual(mm["label"], "test-ns")

    def test_five_primary_branches(self):
        mm = self._mindmap(self._ns())
        ids = [c["id"] for c in mm["children"]]
        self.assertEqual(ids, ["learnings", "decisions", "goals", "reality", "artefacts"])

    def test_all_branches_are_branch_type(self):
        mm = self._mindmap(self._ns())
        for child in mm["children"]:
            self.assertEqual(child["type"], "branch")

    # ── Learnings branch ──────────────────────────────────────────────────────

    def test_learnings_count_in_label(self):
        ns = self._ns(learnings=[
            {"text": "A fact", "tags": ["tooling"], "weight": 1, "learning_type": "fact"},
            {"text": "B fact", "tags": ["tooling"], "weight": 1, "learning_type": "fact"},
        ])
        branch = self._mindmap(ns)["children"][0]
        self.assertIn("2", branch["label"])

    def test_learnings_clustered_by_primary_tag(self):
        ns = self._ns(learnings=[
            {"text": "T1", "tags": ["tooling"], "weight": 1, "learning_type": "fact"},
            {"text": "T2", "tags": ["tooling"], "weight": 1, "learning_type": "fact"},
            {"text": "A1", "tags": ["architecture"], "weight": 1, "learning_type": "fact"},
        ])
        branch = self._mindmap(ns)["children"][0]
        cluster_ids = [c["id"] for c in branch["children"]]
        self.assertIn("cluster-tooling",      cluster_ids)
        self.assertIn("cluster-architecture", cluster_ids)

    def test_learning_cluster_children_are_leaves(self):
        ns = self._ns(learnings=[
            {"text": "Some learning", "tags": ["tooling"], "weight": 2, "learning_type": "fact"},
        ])
        branch   = self._mindmap(ns)["children"][0]
        cluster  = branch["children"][0]
        leaf     = cluster["children"][0]
        self.assertEqual(leaf["type"], "leaf")
        self.assertIn("Some learning", leaf["label"])
        self.assertEqual(leaf["meta"]["weight"], 2)

    def test_learning_text_truncated_at_60(self):
        long_text = "x" * 80
        ns = self._ns(learnings=[
            {"text": long_text, "tags": ["t"], "weight": 1, "learning_type": "fact"},
        ])
        branch  = self._mindmap(ns)["children"][0]
        cluster = branch["children"][0]
        leaf    = cluster["children"][0]
        self.assertLessEqual(len(leaf["label"]), 62)  # 60 + "…"
        self.assertEqual(leaf["meta"]["full_text"], long_text)

    def test_learning_without_tags_falls_back_to_untagged(self):
        ns = self._ns(learnings=[
            {"text": "No tags", "tags": [], "weight": 1, "learning_type": "fact"},
        ])
        branch = self._mindmap(ns)["children"][0]
        self.assertEqual(branch["children"][0]["id"], "cluster-untagged")

    def test_clusters_ordered_by_size_descending(self):
        ns = self._ns(learnings=[
            {"text": "A", "tags": ["rare"],    "weight": 1, "learning_type": "fact"},
            {"text": "B", "tags": ["common"],  "weight": 1, "learning_type": "fact"},
            {"text": "C", "tags": ["common"],  "weight": 1, "learning_type": "fact"},
            {"text": "D", "tags": ["common"],  "weight": 1, "learning_type": "fact"},
        ])
        branch = self._mindmap(ns)["children"][0]
        self.assertEqual(branch["children"][0]["id"], "cluster-common")

    # ── Decisions branch ──────────────────────────────────────────────────────

    def test_decisions_are_leaves(self):
        ns = self._ns(decisions=[
            {"decision": "Use D3 only", "rationale": "already loaded", "date": "2026-01-01"},
        ])
        branch = self._mindmap(ns)["children"][1]
        self.assertEqual(branch["children"][0]["type"], "leaf")
        self.assertIn("Use D3", branch["children"][0]["label"])

    def test_decision_meta_contains_rationale(self):
        ns = self._ns(decisions=[
            {"decision": "A", "rationale": "because B", "alternatives": "C", "date": "2026-01-01"},
        ])
        branch = self._mindmap(ns)["children"][1]
        self.assertEqual(branch["children"][0]["meta"]["rationale"], "because B")

    # ── Goals branch ──────────────────────────────────────────────────────────

    def test_goals_sessions_are_session_type(self):
        ns = self._ns(history=[
            {"opened": "2026-06-21T08:00:00Z", "completed": ["Goal A", "Goal B"],
             "filename": "2026-06-21T0800.md", "closed": None,
             "planned": [], "incomplete": [], "notes": "", "learnings_extracted": []},
        ])
        branch  = self._mindmap(ns)["children"][2]
        session = branch["children"][0]
        self.assertEqual(session["type"], "session")
        self.assertEqual(session["label"][:10], "2026-06-21")

    def test_goals_completed_items_are_leaves(self):
        ns = self._ns(history=[
            {"opened": "2026-06-21T08:00:00Z", "completed": ["Ship E25a"],
             "filename": "2026-06-21T0800.md", "closed": None,
             "planned": [], "incomplete": [], "notes": "", "learnings_extracted": []},
        ])
        branch  = self._mindmap(ns)["children"][2]
        session = branch["children"][0]
        leaf    = session["children"][0]
        self.assertEqual(leaf["type"], "leaf")
        self.assertIn("Ship E25a", leaf["label"])

    def test_goals_capped_at_5_sessions(self):
        history = [
            {"opened": f"2026-06-{20-i:02d}T08:00:00Z", "completed": [],
             "filename": f"2026-06-{20-i:02d}T0800.md", "closed": None,
             "planned": [], "incomplete": [], "notes": "", "learnings_extracted": []}
            for i in range(8)
        ]
        branch = self._mindmap(self._ns(history=history))["children"][2]
        self.assertLessEqual(len(branch["children"]), 5)

    # ── Reality branch ────────────────────────────────────────────────────────

    def test_reality_sections_parsed(self):
        ns = self._ns(reality="## What exists\n- A\n- B\n## What is next\n- C\n")
        branch = self._mindmap(ns)["children"][3]
        labels = [c["label"] for c in branch["children"]]
        self.assertIn("What exists",  labels)
        self.assertIn("What is next", labels)

    def test_reality_bullet_count_in_meta(self):
        ns = self._ns(reality="## What exists\n- A\n- B\n- C\n")
        branch = self._mindmap(ns)["children"][3]
        self.assertEqual(branch["children"][0]["meta"]["bullet_count"], 3)

    def test_reality_empty_string_produces_empty_branch(self):
        branch = self._mindmap(self._ns(reality=""))["children"][3]
        self.assertEqual(branch["children"], [])

    # ── Artefacts branch ──────────────────────────────────────────────────────

    def test_artefacts_are_leaves(self):
        ns = self._ns(artefacts=[
            {"title": "My Chart", "type": "svg", "created_at": "2026-06-20T10:00:00Z",
             "description": "A chart", "tags": ["tooling"], "artefact_id": "abc",
             "file": "artefacts/my-chart.svg", "session_id": None, "linked_decision_id": None},
        ])
        branch = self._mindmap(ns)["children"][4]
        leaf   = branch["children"][0]
        self.assertEqual(leaf["type"], "leaf")
        self.assertIn("My Chart", leaf["label"])
        self.assertEqual(leaf["meta"]["artefact_type"], "svg")

    def test_artefact_count_in_label(self):
        ns = self._ns(artefacts=[
            {"title": "A", "type": "svg", "created_at": "", "description": "", "tags": [],
             "artefact_id": "1", "file": "a.svg", "session_id": None, "linked_decision_id": None},
            {"title": "B", "type": "html", "created_at": "", "description": "", "tags": [],
             "artefact_id": "2", "file": "b.html", "session_id": None, "linked_decision_id": None},
        ])
        branch = self._mindmap(ns)["children"][4]
        self.assertIn("2", branch["label"])

    # ── generate() integration ────────────────────────────────────────────────

    def test_mindmap_key_embedded_in_ns_json(self):
        mm = self._mindmap(self._ns())
        self.assertEqual(mm["type"], "root")
        branch_ids = [c["id"] for c in mm["children"]]
        self.assertIn("learnings", branch_ids)
        self.assertIn("decisions", branch_ids)
        self.assertIn("goals",     branch_ids)
        self.assertIn("reality",   branch_ids)
        self.assertIn("artefacts", branch_ids)


class TestParseSectionBullets(unittest.TestCase):

    def test_section_bullets_include_subsections_and_stop_at_next_h2(self):
        md = "## What exists and works\n- A\n### Sub\n- B\n## Backlog\n- C\n"
        texts = [t for _, t in _mod._parse_section_bullets(md, "## What exists and works")]
        self.assertEqual(texts, ["A", "B"])


class TestLoadWatchSignals(unittest.TestCase):
    """P54 — mirrors compass's cmd_watch_signals; must stay behaviourally in sync with it."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self._tmpdir.name)
        self._patcher = patch.object(_mod, "LOOP_DIR", self.loop_dir)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _write_jsonl(self, ns, filename, items):
        d = self.loop_dir / ns
        d.mkdir(parents=True, exist_ok=True)
        with open(d / filename, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def test_no_watches_returns_empty_without_touching_disk(self):
        result = _load_watch_signals(self.loop_dir / "me", {}, {})
        self.assertEqual(result, {"bootstrapped": False, "signals": [], "total_signals": 0, "empty": True})

    def test_watched_namespace_directory_missing_is_skipped(self):
        me = self.loop_dir / "me"
        me.mkdir()
        result = _load_watch_signals(me, {"watches": ["ghost"]}, {"last_close": ""})
        self.assertEqual(result["signals"], [])
        self.assertTrue(result["empty"])

    def test_bootstrapped_when_own_tag_freq_empty(self):
        me = self.loop_dir / "me"
        me.mkdir()  # no learnings.jsonl at all -> tag_freq empty
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": "x", "tags": ["tooling"], "weight": 1, "date": "2026-07-02T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        self.assertTrue(result["bootstrapped"])
        self.assertEqual(result["total_signals"], 1)
        self.assertEqual(result["signals"][0]["learnings"][0]["overlap_score"], 1)

    def test_weighted_overlap_scoring_and_sorting(self):
        me = self.loop_dir / "me"
        # my own top learnings establish a weighted tag_freq: tooling=3, debugging=1
        self._write_jsonl("me", "learnings.jsonl", [
            {"text": "a", "tags": ["tooling"], "weight": 3, "status": "active"},
            {"text": "b", "tags": ["debugging"], "weight": 1, "status": "active"},
        ])
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": "low overlap",  "tags": ["debugging"], "date": "2026-07-02T00:00:00Z", "status": "active"},
            {"text": "high overlap", "tags": ["tooling"],   "date": "2026-07-03T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        self.assertFalse(result["bootstrapped"])
        learnings = result["signals"][0]["learnings"]
        self.assertEqual(learnings[0]["text"], "high overlap")  # sorted desc by overlap_score
        self.assertEqual(learnings[0]["overlap_score"], 3)
        self.assertEqual(learnings[1]["overlap_score"], 1)

    def test_recency_filter_excludes_items_before_last_close(self):
        me = self.loop_dir / "me"
        self._write_jsonl("me", "learnings.jsonl", [{"text": "seed", "tags": ["tooling"], "weight": 1, "status": "active"}])
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": "old", "tags": ["tooling"], "date": "2026-06-01T00:00:00Z", "status": "active"},
            {"text": "new", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        texts = [l["text"] for l in result["signals"][0]["learnings"]]
        self.assertEqual(texts, ["new"])

    def test_superseded_and_archived_learnings_excluded(self):
        me = self.loop_dir / "me"
        self._write_jsonl("me", "learnings.jsonl", [{"text": "seed", "tags": ["tooling"], "weight": 1, "status": "active"}])
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": "archived", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "archived"},
            {"text": "superseded", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "superseded"},
            {"text": "active", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        texts = [l["text"] for l in result["signals"][0]["learnings"]]
        self.assertEqual(texts, ["active"])

    def test_caps_at_top_3_decisions_and_top_5_learnings_per_namespace(self):
        me = self.loop_dir / "me"
        self._write_jsonl("me", "learnings.jsonl", [{"text": "seed", "tags": ["tooling"], "weight": 1, "status": "active"}])
        self._write_jsonl("other", "decisions.jsonl", [
            {"decision": f"d{i}", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z"} for i in range(5)
        ])
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": f"l{i}", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "active"} for i in range(8)
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        self.assertEqual(len(result["signals"][0]["decisions"]), 3)
        self.assertEqual(len(result["signals"][0]["learnings"]), 5)
        self.assertEqual(result["total_signals"], 8)

    def test_items_with_zero_tag_overlap_dropped(self):
        me = self.loop_dir / "me"
        self._write_jsonl("me", "learnings.jsonl", [{"text": "seed", "tags": ["tooling"], "weight": 1, "status": "active"}])
        self._write_jsonl("other", "learnings.jsonl", [
            {"text": "unrelated", "tags": ["unrelated-tag"], "date": "2026-07-05T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["other"]}, {"last_close": "2026-07-01T00:00:00Z"})
        self.assertEqual(result["signals"][0]["learnings"], [])
        self.assertEqual(result["total_signals"], 0)
        self.assertTrue(result["empty"])

    def test_multiple_watched_namespaces_capped_independently(self):
        me = self.loop_dir / "me"
        self._write_jsonl("me", "learnings.jsonl", [{"text": "seed", "tags": ["tooling"], "weight": 1, "status": "active"}])
        self._write_jsonl("a", "learnings.jsonl", [
            {"text": "a1", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "active"},
        ])
        self._write_jsonl("b", "learnings.jsonl", [
            {"text": "b1", "tags": ["tooling"], "date": "2026-07-05T00:00:00Z", "status": "active"},
        ])
        result = _load_watch_signals(me, {"watches": ["a", "b"]}, {"last_close": "2026-07-01T00:00:00Z"})
        self.assertEqual(len(result["signals"]), 2)
        self.assertEqual(result["total_signals"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_confidence
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeConfidence(unittest.TestCase):

    def test_string_passthrough(self):
        self.assertEqual(_normalize_confidence("high"), "high")
        self.assertEqual(_normalize_confidence("medium"), "medium")

    def test_none_passthrough(self):
        self.assertIsNone(_normalize_confidence(None))

    def test_high_bucket(self):
        self.assertEqual(_normalize_confidence(0.95), "high")

    def test_medium_bucket(self):
        self.assertEqual(_normalize_confidence(0.7), "medium")

    def test_low_bucket(self):
        self.assertEqual(_normalize_confidence(0.3), "low")

    def test_boundary_085_is_high(self):
        self.assertEqual(_normalize_confidence(0.85), "high")

    def test_boundary_06_is_medium(self):
        self.assertEqual(_normalize_confidence(0.6), "medium")

    def test_int_confidence_coerced(self):
        self.assertEqual(_normalize_confidence(1), "high")


# ─────────────────────────────────────────────────────────────────────────────
# _zone_distribution (P56)
# ─────────────────────────────────────────────────────────────────────────────

class TestZoneDistribution(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(
            _zone_distribution([]),
            {"golden": 0, "warning": 0, "preference": 0, "unclassified": 0},
        )

    def test_mixed_zones(self):
        ls = [{"zone": "golden"}, {"zone": "golden"}, {"zone": "warning"}, {"zone": "preference"}, {}]
        self.assertEqual(
            _zone_distribution(ls),
            {"golden": 2, "warning": 1, "preference": 1, "unclassified": 1},
        )

    def test_unknown_zone_value_counts_as_unclassified(self):
        self.assertEqual(_zone_distribution([{"zone": "bogus"}])["unclassified"], 1)

    def test_counts_sum_to_total(self):
        ls = [{"zone": z} for z in ("golden", "warning", "preference")] + [{}] * 3
        d = _zone_distribution(ls)
        self.assertEqual(sum(d.values()), len(ls))


# ─────────────────────────────────────────────────────────────────────────────
# _compute_confidence_calibration (P59) — mirrors compass core's
# compass/learnings.py::_compute_confidence_calibration exactly (_MIN_RESOLVED_HYPOTHESES=8,
# _CONFIDENCE_ORDER=("low","medium","high"))
# ─────────────────────────────────────────────────────────────────────────────

def _hyp(confidence, result):
    return {"learning_type": "hypothesis", "confidence": confidence, "validation_result": result}


class TestConfidenceCalibration(unittest.TestCase):
    def test_below_sample_size_threshold(self):
        learnings = [_hyp("high", "confirmed")] * 7
        result = _compute_confidence_calibration(learnings)
        self.assertFalse(result["sufficient_sample"])
        self.assertEqual(result["resolved_count"], 7)
        self.assertEqual(result["min_required"], 8)
        self.assertEqual(result["buckets"], {})
        self.assertIsNone(result["miscalibrated"])

    def test_non_hypothesis_and_unresolved_learnings_excluded_from_count(self):
        learnings = (
            [_hyp("high", "confirmed")] * 7
            + [{"learning_type": "fact", "confidence": "high"}]
            + [_hyp("high", None)]
            + [{"learning_type": "hypothesis", "confidence": "high", "validation_result": "pending"}]
        )
        result = _compute_confidence_calibration(learnings)
        self.assertFalse(result["sufficient_sample"])
        self.assertEqual(result["resolved_count"], 7)

    def test_well_calibrated_monotonic_strong_discrimination(self):
        learnings = (
            [_hyp("low", "disproven")] * 3
            + [_hyp("medium", "confirmed")] * 2 + [_hyp("medium", "disproven")] * 2
            + [_hyp("high", "confirmed")] * 3
        )
        result = _compute_confidence_calibration(learnings)
        self.assertTrue(result["sufficient_sample"])
        self.assertEqual(result["resolved_count"], 10)
        self.assertEqual(result["buckets"]["low"], {"n": 3, "confirmed": 0, "confirm_rate": 0.0})
        self.assertEqual(result["buckets"]["medium"], {"n": 4, "confirmed": 2, "confirm_rate": 0.5})
        self.assertEqual(result["buckets"]["high"], {"n": 3, "confirmed": 3, "confirm_rate": 1.0})
        self.assertTrue(result["monotonic"])
        self.assertEqual(result["low_high_delta"], 1.0)
        self.assertFalse(result["miscalibrated"])

    def test_non_monotonic_is_miscalibrated(self):
        # high bucket confirms LESS often than low — inverted calibration
        learnings = (
            [_hyp("low", "confirmed")] * 4
            + [_hyp("medium", "confirmed")] * 2 + [_hyp("medium", "disproven")] * 2
            + [_hyp("high", "disproven")] * 4
        )
        result = _compute_confidence_calibration(learnings)
        self.assertTrue(result["sufficient_sample"])
        self.assertFalse(result["monotonic"])
        self.assertTrue(result["miscalibrated"])

    def test_monotonic_but_weak_discrimination_is_miscalibrated(self):
        # low=0.50, medium=0.60, high=0.60 — monotonic but delta 0.10 < 0.20 threshold
        learnings = (
            [_hyp("low", "confirmed")] * 2 + [_hyp("low", "disproven")] * 2
            + [_hyp("medium", "confirmed")] * 3 + [_hyp("medium", "disproven")] * 2
            + [_hyp("high", "confirmed")] * 3 + [_hyp("high", "disproven")] * 2
        )
        result = _compute_confidence_calibration(learnings)
        self.assertTrue(result["sufficient_sample"])
        self.assertEqual(result["buckets"]["low"]["confirm_rate"], 0.5)
        self.assertEqual(result["buckets"]["high"]["confirm_rate"], 0.6)
        self.assertTrue(result["monotonic"])
        self.assertTrue(result["miscalibrated"])

    def test_empty_bucket_confirm_rate_is_null_not_excluded_from_monotonic_check(self):
        # no "medium" entries at all; low/high still compared directly
        learnings = [_hyp("low", "disproven")] * 4 + [_hyp("high", "confirmed")] * 4
        result = _compute_confidence_calibration(learnings)
        self.assertTrue(result["sufficient_sample"])
        self.assertIsNone(result["buckets"]["medium"]["confirm_rate"])
        self.assertEqual(result["buckets"]["medium"]["n"], 0)
        self.assertTrue(result["monotonic"])
        self.assertEqual(result["low_high_delta"], 1.0)
        self.assertFalse(result["miscalibrated"])


# ─────────────────────────────────────────────────────────────────────────────
# _failure_dimension_distribution (P69) — dashboard-only aggregation; compass core
# only added the per-entry closed-enum field + a single-value filter, no grouping.
# ─────────────────────────────────────────────────────────────────────────────

class TestFailureDimensionDistribution(unittest.TestCase):
    def test_empty_feedback_returns_zero_total(self):
        result = _failure_dimension_distribution([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["counts"], {
            "cadence-timing": 0, "api-schema-gap": 0, "step-sequencing": 0,
            "cross-namespace-scope": 0, "unclassified": 0,
        })
        self.assertIsNone(result["dominant"])

    def test_counts_by_known_dimension(self):
        feedback = (
            [{"failure_dimension": "cadence-timing"}] * 3
            + [{"failure_dimension": "api-schema-gap"}] * 1
            + [{"failure_dimension": "step-sequencing"}] * 2
        )
        result = _failure_dimension_distribution(feedback)
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["counts"]["cadence-timing"], 3)
        self.assertEqual(result["counts"]["api-schema-gap"], 1)
        self.assertEqual(result["counts"]["step-sequencing"], 2)
        self.assertEqual(result["counts"]["cross-namespace-scope"], 0)
        self.assertEqual(result["dominant"], "cadence-timing")

    def test_missing_or_unknown_dimension_counted_as_unclassified(self):
        feedback = [
            {"text": "no dimension field"},
            {"failure_dimension": None},
            {"failure_dimension": "some-future-category-not-yet-in-the-enum"},
        ]
        result = _failure_dimension_distribution(feedback)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["counts"]["unclassified"], 3)
        self.assertEqual(result["dominant"], "unclassified")

    def test_tie_breaks_by_enum_order(self):
        # cadence-timing comes first in the closed enum — ties should favour it
        feedback = [{"failure_dimension": "cadence-timing"}, {"failure_dimension": "api-schema-gap"}]
        result = _failure_dimension_distribution(feedback)
        self.assertEqual(result["dominant"], "cadence-timing")


# ---------------------------------------------------------------------------
# Cadence mirrors of compass core (2026-09-30 drift audit)
# ---------------------------------------------------------------------------

class TestLadderDataFields(unittest.TestCase):
    """Inputs the maturity ladder needs that were not yet in NS: reality structure (mirrors
    core's reality._check_reality_structure), hasRepoPath, and a `typed` flag per session."""

    def test_reality_structure_complete(self):
        md = "# Reality\n## What exists and works\n- a\n## Backlog\n- b\n"
        self.assertEqual(_mod._check_reality_structure(md), [])

    def test_reality_structure_reports_each_missing_section(self):
        self.assertEqual(_mod._check_reality_structure("## What exists and works\n"),
                         ["Missing section: ## Backlog"])
        self.assertEqual(_mod._check_reality_structure(""),
                         ["Missing section: ## What exists and works",
                          "Missing section: ## Backlog"])

    def test_reality_structure_header_match_is_case_and_depth_insensitive(self):
        self.assertEqual(_mod._check_reality_structure("### what exists and works\n## BACKLOG"), [])

    def test_goal_type_by_session_marks_typed_sessions(self):
        state = {"goal_completions": {
            "2026-10-01T10:00:00Z": {"total_goals": 3},
            "2026-10-02T10:00:00Z": {"total_goals": 2, "types": ["exploit", "explore"]},
        }}
        rows = _mod._goal_type_by_session(state)
        self.assertEqual([r["typed"] for r in rows], [False, True])

    def test_js_data_carries_ladder_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns_dir = Path(tmp) / "demo"
            ns_dir.mkdir()
            (ns_dir / "state.json").write_text(json.dumps({"repo_path": "/somewhere"}))
            (ns_dir / "reality.md").write_text("## What exists and works\n- a\n")
            n = _mod.load_namespace(ns_dir)
            js = json.loads(_mod._js_data([n]))[0]
        self.assertIs(js["hasRepoPath"], True)
        self.assertEqual(js["realityStructureWarnings"], ["Missing section: ## Backlog"])
        self.assertNotIn("/somewhere", json.dumps(js.get("hasRepoPath")))


class TestGoalStatusBreakdown(unittest.TestCase):
    """goal_completions[].statuses as a per-status count plus the recent goals that did not
    complete (data-model audit Rank 6a). Counts sum to the total; unknown statuses go to other."""

    def test_none_without_completions(self):
        self.assertIsNone(_mod._goal_status_breakdown({}))

    def test_counts_every_status_and_sum_to_total(self):
        state = {"goal_completions": {
            "2026-10-01T10:00:00Z": {"statuses": ["completed", "abandoned", "weird"]},
            "2026-10-02T10:00:00Z": {"statuses": ["completed", "blocked", "skipped", "partial"]},
        }}
        b = _mod._goal_status_breakdown(state)
        self.assertEqual(b["counts"], {"completed": 2, "partial": 1, "skipped": 1, "blocked": 1,
                                       "abandoned": 1, "other": 1})
        self.assertEqual(b["total"], 7)
        self.assertEqual(b["sessions"], 2)

    def test_not_completed_newest_first_with_goal_text(self):
        state = {"goal_completions": {
            "2026-10-01T10:00:00Z": {"statuses": ["abandoned"], "planned_actions": ["Old goal"]},
            "2026-10-02T10:00:00Z": {"statuses": ["completed", "blocked"],
                                     "planned_actions": ["Done goal", "Blocked goal"]},
        }}
        b = _mod._goal_status_breakdown(state)
        self.assertEqual(b["not_completed"], [
            {"date": "2026-10-02", "status": "blocked", "goal": "Blocked goal", "reason": None},
            {"date": "2026-10-01", "status": "abandoned", "goal": "Old goal", "reason": None},
        ])

    def test_legacy_shapes(self):
        state = {"goal_completions": {
            "2026-06-01T10:00:00Z": ["completed", "abandoned"],
            "2026-06-02T10:00:00Z": {"statuses": [{"goal": "Dict goal", "status": "skipped"}]},
        }}
        b = _mod._goal_status_breakdown(state)
        self.assertEqual(b["counts"]["abandoned"], 1)
        self.assertEqual(b["not_completed"][0], {"date": "2026-06-02", "status": "skipped", "goal": "Dict goal", "reason": None})
        self.assertEqual(b["not_completed"][1]["goal"], None)

    def test_history_supplies_goal_text_and_reason(self):
        state = {"goal_completions": {
            "2026-05-13T07:10:51Z": {"statuses": ["completed", "completed", "abandoned"]},
        }}
        history = {"2026-05-13T07:10:51Z": {
            "planned": ["Reality correction", "Graph spike", "Bulk-delete article management UI"],
            "incomplete": ["Bulk-delete article management UI — deferred by agreement"],
        }}
        b = _mod._goal_status_breakdown(state, history)
        self.assertEqual(b["not_completed"], [{
            "date": "2026-05-13", "status": "abandoned", "goal": "Bulk-delete article management UI",
            "reason": "Bulk-delete article management UI — deferred by agreement"}])

    def test_reason_falls_back_to_order_when_counts_match(self):
        state = {"goal_completions": {"2026-05-13T07:10:51Z": {"statuses": ["blocked", "completed", "skipped"]}}}
        history = {"2026-05-13T07:10:51Z": {"planned": ["A goal", "B goal", "C goal"],
                                            "incomplete": ["first reworded — waiting on API", "third reworded"]}}
        b = _mod._goal_status_breakdown(state, history)
        self.assertEqual([g["reason"] for g in b["not_completed"]], ["third reworded", "first reworded — waiting on API"])

    def test_history_planned_ignored_when_lengths_differ(self):
        state = {"goal_completions": {"2026-05-13T07:10:51Z": {"statuses": ["completed", "abandoned"]}}}
        history = {"2026-05-13T07:10:51Z": {"planned": ["Only one"], "incomplete": []}}
        b = _mod._goal_status_breakdown(state, history)
        self.assertEqual(b["not_completed"][0]["goal"], None)
        self.assertEqual(b["not_completed"][0]["reason"], None)

    def test_not_completed_capped_at_ten(self):
        state = {"goal_completions": {f"2026-10-{d:02d}T10:00:00Z": {"statuses": ["abandoned"]}
                                      for d in range(1, 16)}}
        b = _mod._goal_status_breakdown(state)
        self.assertEqual(len(b["not_completed"]), 10)
        self.assertEqual(b["counts"]["abandoned"], 15)


class TestCheckDreamDue(unittest.TestCase):
    """Mirrors compass/dream.py::_check_dream_due -- sessions OR corpus_delta, both
    thresholds from config. There is no absolute corpus-size gate upstream."""

    def test_large_corpus_alone_is_not_due(self):
        due, _ = _mod._check_dream_due({"sessions_since_dream": 0, "corpus_delta": 0}, {})
        self.assertFalse(due)

    def test_sessions_gate(self):
        due, _ = _mod._check_dream_due({"sessions_since_dream": 5}, {})
        self.assertTrue(due)

    def test_corpus_delta_gate(self):
        due, _ = _mod._check_dream_due({"sessions_since_dream": 0, "corpus_delta": 10}, {})
        self.assertTrue(due)

    def test_thresholds_read_from_config(self):
        cfg = {"dream_interval_sessions": 8, "corpus_delta_threshold": 20}
        due, _ = _mod._check_dream_due({"sessions_since_dream": 7, "corpus_delta": 19}, cfg)
        self.assertFalse(due)
        due, _ = _mod._check_dream_due({"sessions_since_dream": 8, "corpus_delta": 0}, cfg)
        self.assertTrue(due)


class TestCheckClaudeReviewDue(unittest.TestCase):
    """Mirrors compass/orient.py::_check_claude_review_due + _resolve_claude_md_path:
    session cadence (default 15) OR, once >= 2 sessions have passed, the CLAUDE.md being
    over claude_md_size_budget_bytes (default 20000)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.ns_dir = self.repo / "ns"
        self.ns_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, size):
        (self.repo / "CLAUDE.md").write_text("x" * size)

    def test_cadence_gate(self):
        self._write(100)
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 15}, {}, str(self.repo))
        self.assertTrue(r["due"])
        self.assertFalse(r["pulled_forward_by_size"])

    def test_size_gate_pulls_forward(self):
        self._write(20_001)
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 2}, {}, str(self.repo))
        self.assertTrue(r["due"])
        self.assertTrue(r["pulled_forward_by_size"])
        self.assertEqual(r["claude_md_bytes"], 20_001)

    def test_size_gate_uses_largest_of_root_and_nested(self):
        self._write(4_000)
        nested = self.repo / "scripts"
        nested.mkdir()
        (nested / "CLAUDE.md").write_text("x" * 20_001)
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 2}, {}, str(self.repo))
        self.assertTrue(r["pulled_forward_by_size"])
        self.assertEqual(r["claude_md_bytes"], 20_001)
        self.assertEqual(r["claude_md_files"], {"CLAUDE.md": 4_000, "scripts/CLAUDE.md": 20_001})

    def test_convention_scan_counts_every_rules_file(self):
        # Mirrors core's orient._claude_md_files (2026-10-27): top-level <dir>/CLAUDE.md and
        # docs/claude/*.md count; hidden dirs and deeper nesting do not.
        self._write(4_000)
        for rel, size in (("tests/CLAUDE.md", 300), ("docs/claude/views.md", 20_001),
                          (".git/CLAUDE.md", 50_000), ("a/b/CLAUDE.md", 50_000)):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text("x" * size)
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 2}, {}, str(self.repo))
        self.assertTrue(r["pulled_forward_by_size"])
        self.assertEqual(r["claude_md_files"],
                         {"CLAUDE.md": 4_000, "docs/claude/views.md": 20_001, "tests/CLAUDE.md": 300})

    def test_size_gate_waits_for_min_sessions(self):
        self._write(50_000)
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 1}, {}, str(self.repo))
        self.assertFalse(r["due"])

    def test_size_budget_from_config(self):
        self._write(15_000)
        cfg = {"claude_md_size_budget_bytes": 10_000, "claude_review_size_min_sessions": 1}
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 1}, cfg, str(self.repo))
        self.assertTrue(r["pulled_forward_by_size"])

    def test_no_claude_md_never_due(self):
        r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 99}, {}, str(self.repo))
        self.assertFalse(r["due"])

    def test_repo_path_set_does_not_fall_back_to_skill_dir(self):
        # Core only falls back to ~/.claude/skills/<ns>/CLAUDE.md when repo_path is unset.
        with patch.object(_mod.Path, "home", return_value=self.repo):
            skill_dir = self.repo / ".claude" / "skills" / "ns"
            skill_dir.mkdir(parents=True)
            (skill_dir / "CLAUDE.md").write_text("x")
            r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 99}, {}, str(self.repo / "elsewhere"))
            self.assertFalse(r["due"])
            r = _mod._check_claude_review_due(self.ns_dir, {"sessions_since_claude_review": 99}, {}, "")
            self.assertTrue(r["due"])


class TestSkillOptInterval(unittest.TestCase):
    """compass/skillopt.py reads skill_opt_interval_sessions (default 10) from config."""

class TestPulseGitErrors(unittest.TestCase):
    """`_pulse_git` keeps core's {repo, ahead, dirty_files} and adds a dashboard-only
    `errors` map naming why a probe came back None."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_no_repo_path_is_none(self):
        self.assertIsNone(_mod._pulse_git(None))
        self.assertIsNone(_mod._pulse_git(""))

    def test_not_a_repo_records_exit_code_for_both_probes(self):
        g = _mod._pulse_git(str(self.dir))
        self.assertIsNone(g["ahead"])
        self.assertIsNone(g["dirty_files"])
        self.assertEqual(set(g["errors"]), {"ahead", "dirty_files"})
        self.assertTrue(g["errors"]["dirty_files"].startswith("exit 128"))

    def test_repo_without_upstream_only_fails_ahead(self):
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.dir)], check=True)
        (self.dir / "f.txt").write_text("x")
        g = _mod._pulse_git(str(self.dir))
        self.assertEqual(g["dirty_files"], 1)
        self.assertIsNone(g["ahead"])
        self.assertEqual(list(g["errors"]), ["ahead"])

    def test_timeout_is_named(self):
        import subprocess
        with patch.object(_mod.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 3)):
            g = _mod._pulse_git(str(self.dir))
        self.assertEqual(g["errors"], {"ahead": "timeout after 3s", "dirty_files": "timeout after 3s"})

    def test_missing_git_binary_is_named(self):
        with patch.object(_mod.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory")):
            g = _mod._pulse_git(str(self.dir))
        self.assertEqual(g["errors"]["ahead"], "git not runnable: No such file or directory")


_HISTORY_WITH_MATCH = """# Session 2026-10-22T0834 — demo

**Opened:** 2026-10-22T08:00:00Z
**Closed:** 2026-10-22T08:34:00Z
**Close mode:** bulk (close-all)
**Duration:** 34m

## Planned
- Ship A

## Completed
- ✓ Ship A

## Incomplete
- (none)

## Notes
A note.

## Backlog match
**Context:** shipped A

**Candidates:**
- [tactical, identifier, overlap 5, {h}] Build A properly
- [strategic, ratio, overlap 2, no-hash] Something vaguer

**Excluded (appended this session):**
- [tactical, rare, overlap 3, abcd1234] Appended today

## Future section
Kept verbatim.
"""


class TestHistoryParserSections(unittest.TestCase):
    """The parser models every section core's history.py writes and keeps unknown ones."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.hash = hashlib.sha256("Build A properly".encode()).hexdigest()[:8]
        self.f = self.dir / "2026-10-22T0834.md"
        self.f.write_text(_HISTORY_WITH_MATCH.replace("{h}", self.hash))

    def test_header_fields(self):
        r = _mod._parse_history_file(self.f)
        self.assertEqual(r["duration_minutes"], 34)
        self.assertEqual(r["close_mode"], "bulk (close-all)")
        self.assertEqual(r["completed"], ["Ship A"])
        self.assertEqual(r["notes"].strip(), "A note.")

    def test_backlog_match_candidates_and_excluded(self):
        bm = _mod._parse_history_file(self.f)["backlog_match"]
        self.assertEqual(bm["context"], "shipped A")
        self.assertEqual(bm["candidates"][0], {"section": "tactical", "match_basis": "identifier",
                                               "overlap": 5, "bullet_hash": self.hash,
                                               "text": "Build A properly"})
        self.assertIsNone(bm["candidates"][1]["bullet_hash"])
        self.assertEqual([c["text"] for c in bm["excluded"]], ["Appended today"])

    def test_unknown_section_is_kept_not_dropped(self):
        r = _mod._parse_history_file(self.f)
        self.assertEqual(r["other_sections"], {"Future section": "Kept verbatim.\n"})

    def test_file_without_new_sections_has_defaults(self):
        f = self.dir / "old.md"
        f.write_text("**Opened:** x\n\n## Planned\n- A\n")
        r = _mod._parse_history_file(f)
        self.assertIsNone(r["backlog_match"])
        self.assertIsNone(r["duration_minutes"])
        self.assertEqual((r["close_mode"], r["other_sections"]), ("", {}))

    def test_malformed_candidate_line_kept_as_text(self):
        c = _mod._parse_backlog_match_item("free text, no brackets")
        self.assertEqual((c["match_basis"], c["text"]), ("?", "free text, no brackets"))

    def test_summary_marks_still_open_against_reality(self):
        parsed = [_mod._parse_history_file(self.f)]
        reality = "## Backlog\n### Tactical\n- Build A properly\n"
        b = _mod._backlog_match_summary(parsed, reality)
        self.assertEqual((b["closes"], b["with_candidates"], b["offered"], b["still_open"], b["excluded"]),
                         (1, 1, 2, 1, 1))
        self.assertEqual(b["by_basis"], {"ratio": 1, "identifier": 1, "rare": 0, "other": 0})
        self.assertEqual([c["still_open"] for c in b["recent"][0]["candidates"]], [True, None])
        gone = _mod._backlog_match_summary(parsed, "")
        self.assertEqual(gone["still_open"], 0)

    def test_summary_none_without_match_sections(self):
        self.assertIsNone(_mod._backlog_match_summary([{"backlog_match": None}], ""))

    def test_load_namespace_parses_history_once(self):
        ns = self.dir / "demo"
        (ns / "history").mkdir(parents=True)
        (ns / "state.json").write_text("{}")
        for i in range(7):
            (ns / "history" / f"2026-10-{10 + i}T0900.md").write_text(f"**Opened:** t{i}\n\n## Planned\n- g{i}\n")
        calls = []
        real = _mod._parse_history_file
        with patch.object(_mod, "_parse_history_file", side_effect=lambda f: calls.append(f) or real(f)):
            n = _mod.load_namespace(ns)
        self.assertEqual(len(calls), 7)
        self.assertEqual([h["planned"] for h in n["history"]], [["g6"], ["g5"], ["g4"], ["g3"], ["g2"]])
        self.assertEqual(len(n["carry_forward_trend"]), 7)


class TestCadenceLastRunAndCooldown(unittest.TestCase):
    """Rank 6: cadence last-run timestamps and cooldown-violation overrides."""

    def test_last_run_reads_each_key_and_legacy_skillopt_spelling(self):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(days=18)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lr = _mod._cadence_last_run({"last_dream_at": ts, "last_skillopt_at": ts})
        self.assertEqual(lr["dream"], {"at": ts, "ago": "18d ago"})
        self.assertEqual(lr["skill_opt"]["at"], ts)
        self.assertEqual(lr["research"], {"at": None, "ago": "never"})
        self.assertEqual(set(lr), {"dream", "code_review", "research", "skill_opt",
                                   "claude_review"})

    def test_current_skillopt_key_wins_over_legacy(self):
        lr = _mod._cadence_last_run({"last_skill_opt_at": "2026-10-01T00:00:00Z",
                                     "last_skillopt_at": "2026-01-01T00:00:00Z"})
        self.assertEqual(lr["skill_opt"]["at"], "2026-10-01T00:00:00Z")

    def test_cooldown_summary(self):
        self.assertIsNone(_mod._cooldown_violation_summary([], 10))
        rows = [{"timestamp": f"2026-10-0{i}T00:00:00Z", "reason": f"r{i}"} for i in range(1, 8)]
        cv = _mod._cooldown_violation_summary(rows, 28)
        self.assertEqual((cv["count"], cv["rate"]), (7, 0.25))
        self.assertEqual([r["reason"] for r in cv["recent"]], ["r7", "r6", "r5", "r4", "r3"])
        self.assertIsNone(_mod._cooldown_violation_summary(rows, 0)["rate"])

    def test_load_namespace_wires_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = Path(tmp) / "demo"
            (ns / "history").mkdir(parents=True)
            (ns / "state.json").write_text('{"last_dream_at": "2026-10-01T00:00:00Z"}')
            (ns / "history" / "2026-10-01T0900.md").write_text("## Planned\n- a\n")
            (ns / "cooldown_violations.jsonl").write_text('{"timestamp": "2026-10-01T00:00:00Z", "reason": "x"}\n')
            n = _mod.load_namespace(ns)
            self.assertEqual(n["cadence_last_run"]["dream"]["at"], "2026-10-01T00:00:00Z")
            self.assertEqual((n["cooldown_violation_summary"]["count"],
                              n["cooldown_violation_summary"]["rate"]), (1, 1.0))
            js = _mod._js_data([n])
            self.assertIn('"cadenceLastRun"', js)
            self.assertIn('"cooldownViolationSummary"', js)


class TestReaderProblems(unittest.TestCase):
    """`_read_json`/`_read_jsonl` report corruption into `problems` instead of hiding it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_missing_files_are_not_problems(self):
        problems = []
        self.assertEqual(_mod._read_jsonl(self.dir / "nope.jsonl", problems), [])
        self.assertEqual(_mod._read_json(self.dir / "nope.json", problems), {})
        self.assertEqual(problems, [])

    def test_jsonl_counts_bad_and_non_object_lines_once_per_file(self):
        f = self.dir / "learnings.jsonl"
        f.write_text('{"a": 1}\n\n{broken\n[1, 2]\n{"b": 2}\n')
        problems = []
        self.assertEqual(_mod._read_jsonl(f, problems), [{"a": 1}, {"b": 2}])
        self.assertEqual(problems, [{"file": "learnings.jsonl",
                                     "issue": "2 malformed lines dropped (first: line 3)"}])

    def test_jsonl_without_problems_list_still_drops_silently(self):
        f = self.dir / "x.jsonl"
        f.write_text('{broken\n{"ok": 1}\n')
        self.assertEqual(_mod._read_jsonl(f), [{"ok": 1}])

    def test_json_corrupt_and_non_object(self):
        bad, arr = self.dir / "state.json", self.dir / "config.json"
        bad.write_text('{"a":')
        arr.write_text('[1]')
        problems = []
        self.assertEqual(_mod._read_json(bad, problems), {})
        self.assertEqual(_mod._read_json(arr, problems), {})
        self.assertEqual([p["file"] for p in problems], ["state.json", "config.json"])
        self.assertTrue(problems[0]["issue"].startswith("invalid JSON at line 1"))
        self.assertEqual(problems[1]["issue"], "not a JSON object (list)")

    def test_load_namespace_surfaces_data_problems(self):
        ns = self.dir / "demo"
        ns.mkdir()
        (ns / "state.json").write_text("{}")
        (ns / "learnings.jsonl").write_text('{"text": "ok"}\nnot json\n')
        (ns / "decisions.jsonl").write_text('{oops\n')
        n = _mod.load_namespace(ns)
        self.assertEqual(sorted(p["file"] for p in n["data_problems"]),
                         ["decisions.jsonl", "learnings.jsonl"])
        js = _mod._js_data([n])
        self.assertIn('"dataProblems"', js)


class TestGitHelper(unittest.TestCase):
    """`_git` is the one git runner: (stdout, None) or (None, reason)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_success_returns_stdout(self):
        import subprocess
        subprocess.run(["git", "init", "-q", str(self.dir)], check=True)
        out, err = _mod._git(str(self.dir), "status", "--porcelain", timeout=5)
        self.assertEqual((out, err), ("", None))

    def test_failure_names_exit_code(self):
        out, err = _mod._git(str(self.dir), "status", timeout=5)
        self.assertIsNone(out)
        self.assertTrue(err.startswith("exit 128"))

    def test_timeout_names_the_limit(self):
        import subprocess
        with patch.object(_mod.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 7)):
            self.assertEqual(_mod._git(str(self.dir), "log", timeout=7), (None, "timeout after 7s"))

    def test_uses_no_optional_locks(self):
        with patch.object(_mod.subprocess, "run") as run:
            run.return_value.returncode, run.return_value.stdout = 0, "x"
            _mod._git("~/r", "log", timeout=1)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["git", "--no-optional-locks", "-C", str(Path("~/r").expanduser())])


class TestReviewComplexitySignalErrors(unittest.TestCase):
    """A failed git probe zeroes the signal but names why, instead of looking quiet."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_no_repo_path_has_empty_errors(self):
        sig = _mod._review_complexity_signal(self.dir, {}, {})
        self.assertEqual(sig["errors"], {})
        self.assertFalse(sig["high"])

    def test_not_a_repo_names_both_probes(self):
        sig = _mod._review_complexity_signal(self.dir, {"repo_path": str(self.dir)}, {})
        self.assertEqual(set(sig["errors"]), {"lines_changed", "new_files"})
        self.assertEqual(sig["score"], 0.0)

    def test_healthy_repo_has_empty_errors(self):
        import subprocess
        git = ["git", "-C", str(self.dir), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(self.dir)], check=True)
        (self.dir / "f.txt").write_text("x\n")
        subprocess.run([*git, "add", "f.txt"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        sig = _mod._review_complexity_signal(self.dir, {"repo_path": str(self.dir)}, {})
        self.assertEqual(sig["errors"], {})


class TestDiscoverNamespacesConcurrent(unittest.TestCase):
    """The thread-pooled loader returns exactly what loading each namespace serially would."""

    def test_matches_serial_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = Path(tmp)
            for i, name in enumerate(["alpha", "beta", "gamma", "_community", ".hidden"]):
                d = loop / name
                d.mkdir()
                (d / "state.json").write_text(json.dumps(
                    {"open_session": False, "last_close": f"2026-10-0{i + 1}T09:00:00Z"}))
            (loop / "no-state").mkdir()
            with patch.object(_mod, "LOOP_DIR", loop):
                got = _mod.discover_namespaces()
                serial = [_mod.load_namespace(loop / n) for n in ("gamma", "beta", "alpha")]
        strip = lambda ns: [{k: v for k, v in n.items() if k != "pulse"} for n in ns]
        self.assertEqual([n["namespace"] for n in got], ["gamma", "beta", "alpha"])
        self.assertEqual(strip(got), strip(serial))


if __name__ == "__main__":
    unittest.main()
