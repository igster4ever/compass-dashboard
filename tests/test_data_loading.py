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
_stale_bullet_count    = _mod._stale_bullet_count
_retrieval_stale_texts = _mod._retrieval_stale_texts
_load_watch_signals    = _mod._load_watch_signals
_normalize_confidence  = _mod._normalize_confidence
_zone_distribution     = _mod._zone_distribution
_contract_coverage     = _mod._contract_coverage
_parse_goal_contracts  = _mod._parse_goal_contracts


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


class TestLoadCommunity(unittest.TestCase):
    """P40 Phase 2 (compass core, 2026-07-29) — feed.jsonl now dedupes on
    (learning_id, event_type) so a retraction tombstone survives as its own row
    alongside the original publish record. load_community() must filter those
    tombstones out of "feed" — every dashboard consumer treats a feed row as
    "currently shared"."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.loop_dir = Path(self._tmpdir.name)
        self._patcher = patch.object(_mod, "LOOP_DIR", self.loop_dir)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _write_jsonl(self, filename, items):
        d = self.loop_dir / "_community"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / filename, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def test_disabled_when_no_community_dir(self):
        result = _mod.load_community()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["feed"], [])

    def test_retraction_tombstone_excluded_from_feed(self):
        self._write_jsonl("feed.jsonl", [
            {"learning_id": "l1", "source_loop_id": "ns-a", "event_type": "community.learning_published", "text": "a"},
            {"learning_id": "l1", "source_loop_id": "ns-a", "event_type": "community.learning_retracted", "text": "a"},
            {"learning_id": "l2", "source_loop_id": "ns-b", "event_type": "community.learning_published", "text": "b"},
        ])
        result = _mod.load_community()
        self.assertTrue(result["enabled"])
        self.assertEqual(len(result["feed"]), 2)
        self.assertEqual({e["learning_id"] for e in result["feed"]}, {"l1", "l2"})

    def test_legacy_entries_without_event_type_are_kept(self):
        self._write_jsonl("feed.jsonl", [
            {"learning_id": "l1", "source_loop_id": "ns-a", "text": "pre-P40-Phase-2 entry"},
        ])
        result = _mod.load_community()
        self.assertEqual(len(result["feed"]), 1)


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
# _contract_coverage / _parse_goal_contracts (P55)
# ─────────────────────────────────────────────────────────────────────────────

def _contract(goal_text, criteria, verified_criteria=None, verified_at=None, created_at="2026-08-01T00:00:00Z"):
    return {
        "goal_text": goal_text,
        "criteria": criteria,
        "verified_criteria": verified_criteria or [],
        "unmet_criteria": [c for c in criteria if c not in (verified_criteria or [])],
        "evidence_type": "document",
        "stopping_condition": "n/a",
        "created_at": created_at,
        "verified_at": verified_at,
    }


class TestContractCoverage(unittest.TestCase):

    def test_below_gate_returns_none(self):
        state = {"goal_contracts": {f"h{i}": _contract(f"g{i}", ["a"]) for i in range(4)}}
        self.assertEqual(
            _contract_coverage(state),
            {"contract_coverage": None, "criteria_hit_rate": None},
        )

    def test_at_gate_with_no_relevant_completions_returns_none(self):
        state = {
            "goal_contracts": {f"h{i}": _contract(f"g{i}", ["a"]) for i in range(5)},
            "goal_completions": {},
        }
        self.assertEqual(
            _contract_coverage(state),
            {"contract_coverage": None, "criteria_hit_rate": None},
        )

    def test_full_round_trip_matches_expected_output(self):
        # 5 contracts, all verified with all criteria met, all linked via goal_completions —
        # mirrors the real `compass` namespace's live shape (7 contracts, coverage=1.0,
        # criteria_hit_rate=1.0), reduced to the minimum sample size for a fast unit test.
        contracts = {
            f"h{i}": _contract(f"g{i}", ["a", "b"], verified_criteria=["a", "b"], verified_at="2026-08-02T00:00:00Z")
            for i in range(5)
        }
        state = {
            "goal_contracts": contracts,
            "goal_completions": {
                "2026-08-02": {"completed_hashes": list(contracts.keys())},
            },
        }
        self.assertEqual(
            _contract_coverage(state),
            {"contract_coverage": 1.0, "criteria_hit_rate": 1.0},
        )


class TestParseGoalContracts(unittest.TestCase):

    def test_empty_dict_returns_empty_list(self):
        self.assertEqual(_parse_goal_contracts({"goal_contracts": {}}), [])

    def test_unverified_contract_is_pending(self):
        state = {"goal_contracts": {"h1": _contract("g1", ["a", "b"])}}
        out = _parse_goal_contracts(state)
        self.assertEqual(out[0]["status"], "pending")
        self.assertIsNone(out[0]["criteria_hit_rate"])
        self.assertEqual(out[0]["criteria"], [{"text": "a", "met": False}, {"text": "b", "met": False}])

    def test_partially_verified_contract(self):
        state = {"goal_contracts": {
            "h1": _contract("g1", ["a", "b"], verified_criteria=["a"], verified_at="2026-08-02T00:00:00Z"),
        }}
        out = _parse_goal_contracts(state)
        self.assertEqual(out[0]["status"], "partially_verified")
        self.assertEqual(out[0]["criteria_hit_rate"], 0.5)
        self.assertEqual(out[0]["criteria"], [{"text": "a", "met": True}, {"text": "b", "met": False}])

    def test_fully_verified_contract(self):
        state = {"goal_contracts": {
            "h1": _contract("g1", ["a"], verified_criteria=["a"], verified_at="2026-08-02T00:00:00Z"),
        }}
        out = _parse_goal_contracts(state)
        self.assertEqual(out[0]["status"], "verified")
        self.assertEqual(out[0]["criteria_hit_rate"], 1.0)

    def test_sorted_newest_created_first(self):
        state = {"goal_contracts": {
            "h1": _contract("g1", ["a"], created_at="2026-08-01T00:00:00Z"),
            "h2": _contract("g2", ["a"], created_at="2026-08-05T00:00:00Z"),
        }}
        out = _parse_goal_contracts(state)
        self.assertEqual([c["goal_text"] for c in out], ["g2", "g1"])


# ─────────────────────────────────────────────────────────────────────────────
# load_namespace() — decision_guidance (P65) retired-entry filtering
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadNamespaceDecisionGuidance(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.ns_dir = Path(self._tmpdir.name) / "myns"
        self.ns_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_jsonl(self, filename, items):
        with open(self.ns_dir / filename, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def test_no_file_returns_empty_list(self):
        result = _mod.load_namespace(self.ns_dir)
        self.assertEqual(result["decision_guidance"], [])

    def test_retired_entries_filtered_out(self):
        self._write_jsonl("decision_guidance.jsonl", [
            {"guidance_id": "g1", "status": "active", "preferred_decision_text": "A"},
            {"guidance_id": "g2", "status": "retired", "preferred_decision_text": "B"},
        ])
        result = _mod.load_namespace(self.ns_dir)
        self.assertEqual(len(result["decision_guidance"]), 1)
        self.assertEqual(result["decision_guidance"][0]["guidance_id"], "g1")


if __name__ == "__main__":
    unittest.main()
