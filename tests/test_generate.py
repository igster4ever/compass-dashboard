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
        "external_signals":         [],
        "exploration_ratio":        None,
        "last_reality_score":       None,
        "goal_type_by_session":     [],
        "carry_forward_trend":      [],
        "quality_dist":             {"high": 0, "neutral": 0, "poor": 0},
        "decay_history":            [],
        "code_review_defer_count":  0,
        "research_defer_count":     0,
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
                            "[[N_LEARNINGS]]", "[[N_SESSIONS]]", "[[CARDS]]", "[[DATA_JSON]]"):
            self.assertNotIn(placeholder, self.html,
                             msg=f"Unreplaced placeholder found: {placeholder}")


if __name__ == "__main__":
    unittest.main()
