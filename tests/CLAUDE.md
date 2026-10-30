# Compass Dashboard — tests/ rules

Loads when Claude reads a file in `tests/`. Root `CLAUDE.md` holds the upkeep rules and budget.

## Tests

Run `python3 -m pytest tests/ -q` **and** `node --test tests/js/` before calling work done.

| File | What it covers |
|------|----------------|
| `test_data_loading.py` | Pure data-layer helpers (completeness, corpus health, goal stats, zones, calibration, failure dimensions…) plus a few tempdir `load_namespace()` cases |
| `test_generate.py` | `generate()` smoke tests — structural markers, `const NS = [` embedding, script-tag escaping, feature wiring |
| `test_integration_pipeline.py` | End-to-end: on-disk synthetic namespace → `load_namespace()` → `_js_data()`/`generate()` |
| `test_claude_md_budget.py` | Each rules file (root, `scripts/`, `tests/` CLAUDE.md, `docs/claude/views.md`) under 20KB; every pre-split section in exactly one file; root links each nested file; `scripts/CLAUDE.md` points to `views.md` |
| `test_core_parity.py` | Imports compass core; asserts every dashboard mirror matches it on all live namespaces (skips when absent) |
| `test_surface_inventory.py` | Every state key, history/learning entry key and loop file core writes (from core source + live data) is read by the dashboard or in `IGNORED` with a reason (skips when absent) |
| `js/dashboard_helpers.test.mjs` | Pure JS helpers extracted from `template.html` by brace-matching (`extractFunction()` — mind its default-parameter gotcha); add new pure helpers to `PURE_HELPERS` |
| `js/render_smoke.test.mjs` | Runs the whole `<script>` IIFE in `node:vm` against a hand-rolled DOM stub and `js/fixtures/dashboard_fixture.json`; calls every view/sub-tab entrypoint and asserts "does not throw" |

**Testing rules:**
- **Regenerate the JS fixture** with `python3 tests/js/fixtures/generate_fixture.py` — it builds
  from real `load_namespace()`/`_js_data()` shapes. Compute derived expectations by calling the
  real function, not by hand-typing numbers.
- **The DOM stub doesn't parse `innerHTML` into child nodes.** A nested element written by a
  parent's `innerHTML` is invisible to `getElementById`/`querySelectorAll`. Assert content only
  on elements whose `innerHTML` is set directly; otherwise assert "does not throw" and verify by
  hand in a real browser.
- **Agent browsers can't open `file://`.** Neither the desktop app's built-in browser pane nor
  Claude in Chrome loads a `file://` page, so a `file://` check (e.g. `--watch` reload) needs the
  user to open the page; serving it over http is a substitute, but it doesn't test `file://`.
- **New `_js_data()` fields use `n.get("field")`, never `n["field"]`** — fixture dicts don't
  carry every key.
- **Assert on rendered content, not CSS class names** — a class name appears in the `<style>`
  block whether or not any element uses it.
- **Verify pipeline refactors by comparing parsed objects:** `json.loads()` the old and new
  `const NS = [...]` and compare for equality. A raw-text diff flags harmless key reordering.

**`docs/backlog/`** — scoped, unshipped write-ups with implementation breadcrumbs and effort
estimates. Not auto-discovered; linked from reality.md's backlog section.
