"""
Smoke test for generate().

Checks:
  1. Output contains the expected JS data marker `const NS = [`
  2. User-controlled strings containing </script> are safely escaped in the output
  3. HTML comment injection (<!--) is escaped
  4. Basic structural markers are present (<!DOCTYPE, </html>)

No filesystem access — uses an in-memory minimal namespace fixture.
"""
import importlib.util
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "compass-dashboard.py"
_spec = importlib.util.spec_from_file_location("compass_dashboard", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

render_html = _mod.generate


def _minimal_ns(overrides=None):
    """Return a minimal namespace dict accepted by generate / _js_data."""
    ns = {
        "namespace":                "test-ns",
        "open_session":             False,
        "last_close":               None,
        "last_open":                None,
        "planned_actions":          [],
        "deferred":                 {},
        "intent":                   "Test intent",
        "intent_summary":           "Test intent",
        "reality":                  "## What exists\n- Something live\n",
        "learnings":                [],
        "superseded_count":         0,
        "decisions":                [],
        "code_context":             "",
        "history":                  [],
        "session_dates":            [],
        "goal_rate":                None,
        "goal_dots":                [],
        "goal_by_month":            {},
        "top_tags":                 [],
        "session_count":            0,
        "cycle_history":            [],
        "last_cycle_minutes":       None,
        "sessions_since_dream":     0,
        "dream_due":                False,
        "reality_completeness_score": None,
        "suggested_goal_count":     {"count": 4, "basis": "default"},
        "research_due":             False,
        "code_review_due":          False,
        "intent_version":           1,
        "stale_bullet_count":       0,
        "back_refs_by_text":        {},
        "conflicts_by_text":        {},
        "intent_history":           [],
        "corpus_health":            None,
        "retrieval_stale_count":    0,
        "external_signals":         [],
        "exploration_ratio":        None,
        "last_reality_score":       None,
        "goal_type_by_session":     [],
        "carry_forward_trend":      [],
        "quality_dist":             {"high": 0, "neutral": 0, "poor": 0},
        "decay_history":            [],
        "code_review_defer_count":  0,
        "research_defer_count":     0,
        "artefacts":                [],
        "all_incomplete_items":     [],
        "skill_feedback":           [],
        "sessions_since_skill_opt": 0,
        "skill_opt_due":            False,
        "quality_history":          [],
        "skillopt_holdout_frozen":  False,
        "skillopt_holdout_mean":    None,
        "skillopt_rounds_completed": 0,
        "skillopt_rwi":             0,
    }
    if overrides:
        ns.update(overrides)
    return ns


class TestRenderHtml(unittest.TestCase):

    def setUp(self):
        self.html = render_html([_minimal_ns()])

    # ── Structural markers ───────────────────────────────────────────────────

    def test_output_is_string(self):
        self.assertIsInstance(self.html, str)

    def test_output_is_non_empty(self):
        self.assertGreater(len(self.html), 1000)

    def test_doctype_present(self):
        self.assertIn("<!DOCTYPE html>", self.html)

    def test_closing_html_tag_present(self):
        self.assertIn("</html>", self.html)

    # ── JS data embedding ────────────────────────────────────────────────────

    def test_ns_data_marker_present(self):
        self.assertIn("const NS = [", self.html)

    def test_namespace_name_embedded(self):
        self.assertIn('"test-ns"', self.html)

    # ── Script-tag injection prevention ──────────────────────────────────────

    def test_script_tag_in_intent_is_escaped(self):
        ns = _minimal_ns({"intent": "Evil </script><script>alert(1)</script>"})
        html = render_html([ns])
        # Raw </script> must NOT appear inside the const NS = [...] data block —
        # it should be escaped to <\/script>
        ns_block_start = html.index("const NS = [")
        ns_block_end   = html.index(";", ns_block_start)
        ns_block = html[ns_block_start:ns_block_end]
        self.assertNotIn("</script>", ns_block)
        self.assertIn(r"<\/script>", ns_block)

    def test_script_tag_in_learning_text_is_escaped(self):
        ns = _minimal_ns({"learnings": [{"text": "Beware </script>", "weight": 1, "tags": []}]})
        html = render_html([ns])
        ns_block_start = html.index("const NS = [")
        ns_block_end   = html.index(";", ns_block_start)
        ns_block = html[ns_block_start:ns_block_end]
        self.assertNotIn("</script>", ns_block)

    def test_html_comment_injection_is_escaped(self):
        ns = _minimal_ns({"intent": "Start <!-- danger --> end"})
        html = render_html([ns])
        ns_block_start = html.index("const NS = [")
        ns_block_end   = html.index(";", ns_block_start)
        ns_block = html[ns_block_start:ns_block_end]
        self.assertNotIn("<!--", ns_block)

    # ── Multi-namespace ───────────────────────────────────────────────────────

    def test_multiple_namespaces_both_embedded(self):
        ns1 = _minimal_ns({"namespace": "ns-one"})
        ns2 = _minimal_ns({"namespace": "ns-two"})
        html = render_html([ns1, ns2])
        self.assertIn('"ns-one"', html)
        self.assertIn('"ns-two"', html)

    def test_empty_namespace_list_still_renders(self):
        html = render_html([])
        self.assertIn("const NS = [", html)
        self.assertIn("const NS = []", html)

    # ── Header stats substitution ─────────────────────────────────────────────

    def test_placeholder_markers_all_replaced(self):
        for placeholder in ("[[GENERATED_AT]]", "[[N_NS]]", "[[N_OPEN]]",
                            "[[N_LEARNINGS]]", "[[N_SESSIONS]]", "[[CARDS]]",
                            "[[NS_DATA]]", "[[BLOCKING_EDGES]]"):
            self.assertNotIn(placeholder, self.html,
                             msg=f"Unreplaced placeholder found: {placeholder}")


class TestArtefacts(unittest.TestCase):

    def _ns_block(self, html):
        start = html.index("const NS = [")
        end   = html.index(";", start)
        return html[start:end]

    def test_empty_artefacts_embedded_as_empty_array(self):
        html = render_html([_minimal_ns()])
        ns_block = self._ns_block(html)
        self.assertIn('"artefacts": []', ns_block)

    def test_artefacts_entries_embedded(self):
        artefacts = [{"artefact_id": "abc", "title": "My Chart", "type": "svg",
                      "file": "artefacts/my-chart-2026-06-20.svg", "tags": ["tooling"],
                      "description": "A test chart", "created_at": "2026-06-20T10:00:00Z",
                      "session_id": None, "linked_decision_id": None}]
        html = render_html([_minimal_ns({"artefacts": artefacts})])
        ns_block = self._ns_block(html)
        self.assertIn("My Chart", ns_block)
        self.assertIn("tooling", ns_block)

    def test_artefact_script_tag_injection_escaped(self):
        artefacts = [{"artefact_id": "x", "title": "Evil </script>", "type": "svg",
                      "file": "artefacts/evil-2026-06-20.svg", "tags": [],
                      "description": "", "created_at": "2026-06-20T10:00:00Z",
                      "session_id": None, "linked_decision_id": None}]
        html = render_html([_minimal_ns({"artefacts": artefacts})])
        ns_block = self._ns_block(html)
        self.assertNotIn("</script>", ns_block)
        self.assertIn(r"<\/script>", ns_block)

    def test_missing_artefacts_key_defaults_gracefully(self):
        ns = _minimal_ns()
        del ns["artefacts"]
        # _js_data uses n["artefacts"] — should raise cleanly, not silently corrupt
        with self.assertRaises(KeyError):
            render_html([ns])


class TestTemplateFile(unittest.TestCase):

    def setUp(self):
        self._template = Path(__file__).parent.parent / "scripts" / "template.html"

    def test_template_file_exists(self):
        self.assertTrue(self._template.exists(), "scripts/template.html not found")

    def test_template_contains_all_placeholders(self):
        content = self._template.read_text(encoding="utf-8")
        for marker in ("[[GENERATED_AT]]", "[[N_NS]]", "[[N_OPEN]]",
                       "[[N_LEARNINGS]]", "[[N_SESSIONS]]", "[[CARDS]]",
                       "[[NS_DATA]]", "[[BLOCKING_EDGES]]"):
            self.assertIn(marker, content, msg=f"Missing placeholder in template.html: {marker}")


class TestBlockingEdges(unittest.TestCase):

    _extract = staticmethod(_mod._extract_blocking_edges)

    def _ns(self, name, incomplete=None):
        ns = _minimal_ns({"namespace": name})
        ns["all_incomplete_items"] = incomplete or []
        return ns

    def test_no_blocked_annotations_returns_empty(self):
        namespaces = [self._ns("alpha"), self._ns("beta")]
        self.assertEqual(self._extract(namespaces), [])

    def test_basic_blocking_edge_detected(self):
        namespaces = [
            self._ns("alpha", ["Do thing [: blocked: beta not shipped yet]"]),
            self._ns("beta"),
        ]
        edges = self._extract(namespaces)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["source"], "alpha")
        self.assertEqual(edges[0]["target"], "beta")
        self.assertIn("beta not shipped yet", edges[0]["reason"])

    def test_blocking_without_leading_colon(self):
        namespaces = [
            self._ns("alpha", ["Do thing [blocked: beta missing]"]),
            self._ns("beta"),
        ]
        edges = self._extract(namespaces)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["target"], "beta")

    def test_self_reference_not_emitted(self):
        namespaces = [
            self._ns("alpha", ["Do thing [: blocked: alpha issue]"]),
        ]
        self.assertEqual(self._extract(namespaces), [])

    def test_unknown_namespace_in_reason_not_emitted(self):
        namespaces = [
            self._ns("alpha", ["Do thing [: blocked: external-api not ready]"]),
            self._ns("beta"),
        ]
        self.assertEqual(self._extract(namespaces), [])

    def test_pcodes_extracted(self):
        namespaces = [
            self._ns("alpha", ["P40-D Phase 2 [: blocked: beta P40 Phase 2 not shipped]"]),
            self._ns("beta"),
        ]
        edges = self._extract(namespaces)
        self.assertIn("P40", edges[0]["pcodes"])

    def test_longer_name_matched_before_prefix(self):
        # "compass-dashboard" should NOT match when reason says "compass" only.
        namespaces = [
            self._ns("compass-dashboard", ["Thing [: blocked: compass script missing]"]),
            self._ns("compass"),
        ]
        edges = self._extract(namespaces)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["target"], "compass")

    def test_blocking_edges_embedded_in_html(self):
        namespaces = [
            self._ns("alpha", ["Do thing [: blocked: beta not shipped]"]),
            self._ns("beta"),
        ]
        html = render_html(namespaces)
        self.assertIn("const BLOCKING_EDGES = [", html)
        self.assertIn('"source": "alpha"', html)
        self.assertIn('"target": "beta"', html)

    def test_empty_blocking_edges_in_html(self):
        html = render_html([_minimal_ns()])
        self.assertIn("const BLOCKING_EDGES = []", html)


class TestCommunityChips(unittest.TestCase):
    """P40-D Phase 2 — community health chip rendering."""

    _card_html = staticmethod(_mod._card_html)

    def _ns(self, name="test-ns"):
        return _minimal_ns({"namespace": name})

    # ── _card_html() unit tests (no filesystem) ──────────────────────────────

    def test_chip_present_when_namespace_has_published(self):
        html = self._card_html(self._ns("compass"), 0, {"compass": 2})
        self.assertIn("community-chip", html)
        self.assertIn("2 shared", html)

    def test_chip_absent_when_namespace_not_in_published(self):
        html = self._card_html(self._ns("test-ns"), 0, {"other-ns": 3})
        self.assertNotIn("community-chip", html)

    def test_chip_absent_when_community_published_is_none(self):
        html = self._card_html(self._ns("test-ns"), 0, None)
        self.assertNotIn("community-chip", html)

    def test_chip_count_reflects_published_value(self):
        html = self._card_html(self._ns("my-ns"), 0, {"my-ns": 5})
        self.assertIn("5 shared", html)

    # ── generate() integration — patched load_community ──────────────────────

    def test_chip_rendered_in_full_html_when_community_enabled(self):
        from unittest.mock import patch
        community = {
            "enabled": True,
            "feed": [{"source_loop_id": "test-ns", "text": "a learning"}],
            "inbox": [], "adoptions": [], "subscriptions": [], "trust_registry": [],
        }
        with patch.object(_mod, "load_community", return_value=community):
            html = render_html([_minimal_ns({"namespace": "test-ns"})])
        self.assertIn("community-chip", html)
        self.assertIn("1 shared", html)

    def test_no_chip_in_html_when_community_disabled(self):
        from unittest.mock import patch
        community = {
            "enabled": False,
            "feed": [], "inbox": [], "adoptions": [], "subscriptions": [], "trust_registry": [],
        }
        with patch.object(_mod, "load_community", return_value=community):
            html = render_html([_minimal_ns()])
        self.assertNotIn("shared</span>", html)

    def test_community_chip_css_present_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn(".community-chip", template)

    def test_community_inbox_signal_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("community learning", template)


class TestZoneAndRetrievalStale(unittest.TestCase):
    """P56 — zone classification + P58 — retrieval-stale signal."""

    def test_zone_field_passed_through_in_ns_json(self):
        ns = _minimal_ns({
            "learnings": [{"text": "a", "weight": 1, "zone": "golden", "learning_type": "fact"}],
        })
        html = render_html([ns])
        self.assertIn('"zone"', html)
        self.assertIn('"golden"', html)

    def test_retrieval_stale_count_embedded_in_ns_json(self):
        ns = _minimal_ns({"retrieval_stale_count": 4})
        html = render_html([ns])
        self.assertIn("retrievalStaleCount", html)
        self.assertIn('"retrievalStaleCount": 4', html.replace("'", '"'))

    def test_zone_badge_css_present_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn(".zone-golden", template)
        self.assertIn(".zone-warning", template)
        self.assertIn(".zone-preference", template)

    def test_zone_column_header_present_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("<th>Zone</th>", template)

    def test_retrieval_stale_filter_button_present_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("Retrieval-stale (", template)
        self.assertIn("lfbtn-stale-", template)

    def test_filter_learning_type_handles_stale(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("row.dataset.stale === 'true'", template)


class TestMindMap(unittest.TestCase):
    """E25b — Mind Map tab wiring and data layer."""

    def _html(self, overrides=None):
        return render_html([_minimal_ns(overrides or {})])

    # ── Template structure ─────────────────────────────────────────────────

    def test_vtab_mindmap_button_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn('id="vtab-mindmap"', template)

    def test_view_mindmap_div_in_template(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn('id="view-mindmap"', template)

    def test_switchview_includes_mindmap(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("'mindmap'", template)
        self.assertIn("renderMindMap", template)

    def test_mm_state_object_defined(self):
        template = (Path(__file__).parent.parent / "scripts" / "template.html").read_text()
        self.assertIn("const _mm =", template)

    # ── Data layer — mindmap field embedded in NS ──────────────────────────

    def test_mindmap_field_present_in_ns(self):
        html = self._html()
        self.assertIn('"mindmap":', html)

    def test_mindmap_root_label_is_namespace_name(self):
        html = self._html({"namespace": "my-test-ns"})
        # root node label should be the namespace name
        self.assertIn('"label": "my-test-ns"', html)

    def test_mindmap_learnings_branch_present(self):
        html = self._html({"learnings": [
            {"text": "A test learning", "tags": ["tooling"], "weight": 1}
        ]})
        self.assertIn('"id": "learnings"', html)

    def test_mindmap_learnings_cluster_by_tag(self):
        html = self._html({"learnings": [
            {"text": "A test learning", "tags": ["tooling"], "weight": 1},
            {"text": "Another", "tags": ["tooling"], "weight": 2},
        ]})
        # tag cluster label includes count
        self.assertIn("tooling (2)", html)

    def test_mindmap_decisions_branch_present(self):
        html = self._html({"decisions": [
            {"decision": "We chose X", "rationale": "because Y", "date": "2026-01-01"}
        ]})
        self.assertIn('"id": "decisions"', html)

    def test_mindmap_goals_branch_present(self):
        html = self._html()
        self.assertIn('"id": "goals"', html)

    def test_mindmap_reality_branch_present(self):
        html = self._html()
        self.assertIn('"id": "reality"', html)

    def test_mindmap_artefacts_branch_present(self):
        html = self._html()
        self.assertIn('"id": "artefacts"', html)

    def test_mindmap_leaf_text_truncated_at_60(self):
        long_text = "X" * 80
        html = self._html({"learnings": [
            {"text": long_text, "tags": ["tooling"], "weight": 1}
        ]})
        # leaf label is truncated; full_text is preserved in meta
        self.assertIn("…", html)
        self.assertIn(long_text, html)  # full text in meta.full_text

    def test_mindmap_script_tag_injection_escaped(self):
        html = self._html({"namespace": "evil</script><script>alert(1)</script>"})
        self.assertNotIn("</script><script>", html)


if __name__ == "__main__":
    unittest.main()
