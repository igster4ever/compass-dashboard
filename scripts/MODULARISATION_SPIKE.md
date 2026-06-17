# Monolith Modularisation — Spike Assessment

**Date:** 2026-06-17  
**Goal:** Extract `HTML_TEMPLATE` string into `template.html` + `dashboard.js`; confirm viability.

---

## Current structure

| Part | Lines |
|---|---|
| Python data layer (helpers, load_namespace, etc.) | ~688 |
| `HTML_TEMPLATE` — HTML structure | ~81 |
| `HTML_TEMPLATE` — CSS `<style>` | ~665 |
| `HTML_TEMPLATE` — JS `<script>` | ~2,190 |
| `render_html()` + `main()` | ~68 |
| **Total** | **3,695** |

---

## Proposed split

```
scripts/
  compass-dashboard.py   — data layer + render_html() + main()   (~756 lines)
  template.html          — HTML + <style> + <script>              (~2,939 lines)
```

`render_html()` change is two lines:

```python
# Before
html = HTML_TEMPLATE

# After
html = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
```

Single-file HTML output is unchanged — the generator still writes one `.html` file.  
`Path.read_text()` is stdlib. No pip installs required.

---

## Key findings

### Win: escaping traps disappear entirely

Currently the JS inside `HTML_TEMPLATE` must use `\\n`, `\\u2014`, `\\u00b7` etc.  
because Python interprets `\n` inside the triple-quoted string.  
There are **36** such escape sequences scattered across the JS.

In `template.html` they become `\n`, `—`, `·` directly — the entire  
CLAUDE.md "critical gotcha" section about double-backslash escaping becomes irrelevant.

### Placeholder rename opportunity

`render_html()` currently uses `[[DATA_JSON]]` but CLAUDE.md documents `[[NS_DATA]]`.  
Renaming during extraction is a clean, one-off fix.

### Template literal backticks

The JS uses 358 backtick characters for template literals.  
Currently safe in a triple-quoted Python string; will be equally safe in a real `.html` file.

### Tests

`test_generate.py` calls `render_html([ns])` which will read from disk  
(`Path(__file__).parent / "template.html"`).  
Tests pass as-is since the template file is co-located with the script.  
Add one smoke test: assert `template.html` exists and all 7 placeholder markers are present.

---

## Effort estimate

| Task | Effort |
|---|---|
| Extract `HTML_TEMPLATE` to `template.html` (copy + unescape 36 sequences) | ~1.5h |
| Rename `[[DATA_JSON]]` → `[[NS_DATA]]` in template + `render_html()` | ~15m |
| Update `render_html()` to read from file | ~15m |
| Add `template.html` existence test | ~15m |
| Update CLAUDE.md module map | ~15m |
| **Total** | **~2.5h** |

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| 36 escape sequences need manual translation | Low | Mechanical find-replace; smoke test catches missed ones |
| `template.html` not found if script moved without template | Low | Use `Path(__file__).parent / "template.html"` — co-location contract |
| `[[DATA_JSON]]` rename breaks nothing internal | None | Template is internal; no external consumers |
| Generated HTML output contract unchanged | None | Single-file HTML output is identical |

---

## Verdict

**Viable and low-risk.** Main benefit: eliminates the JS-in-Python-string escaping  
trap (36 sequences, documented gotcha in CLAUDE.md). Secondary benefit: JS is now  
editable in a real `.js`-syntax-highlighted file.

Recommended next session goal: implement extraction (task should take one 30-min session).
