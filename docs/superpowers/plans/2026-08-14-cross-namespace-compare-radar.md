# Cross-namespace Compare Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new top-level "Compare" view tab overlaying multiple namespaces as radar polygons on 6 fixed macro axes, with a namespace on/off toggle that recalibrates the min-max normalisation live.

**Architecture:** Pure frontend addition to `scripts/template.html`'s IIFE. A pure `compareAxisValue(ns, key)` helper (mirroring `radarAxisValue`) computes each of 6 macro axes; a shared `nsColor(namespace)` function (hoisted out of two existing duplicated closures) assigns each namespace a stable colour; `renderCompare()` renders the SVG + namespace picker; toggle state lives in a `Set` mirrored to `localStorage['compass-compare-namespaces']`.

**Tech Stack:** Vanilla JS (no libraries), hand-rolled Node smoke tests (`node --test`, no new deps) — same stack as the per-namespace radar this plan follows on from.

## Global Constraints

- No new npm/Python dependencies.
- Every function invoked from an inline `onclick`/`onchange` attribute must be added to the `Object.assign(window, {...})` list at `scripts/template.html:4587` (currently ends `radarToggleAxis,\n});`), or it throws `ReferenceError` at click time.
- Axes on this view are **fixed** (6 macro axes) — no per-axis toggle, unlike the per-namespace radar.
- Namespace toggle has no structural minimum, but 0 active namespaces must show an empty-state message, not a degenerate SVG.
- Centrality is computed over the **full** namespace graph regardless of toggle state; only the **min-max normalisation** is scoped to the active namespace set.
- Run both test suites before considering any task done: `python3 -m pytest tests/ -q` and `node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`.
- **Discovered during planning (supersedes the spec's wording):** the namespace→colour palette is actually duplicated at **three** sites once Compare is added, not two — `renderDecisionsView()` (`scripts/template.html:2221-2226`) and `renderArtefactsView()` (`scripts/template.html:2330-2332`) both already have their own copy. Task 1 hoists all three into one `nsColor()`.

---

### Task 1: `nsColor()` hoist + `COMPARE_AXIS_DEFS` + `compareAxisValue()` + centrality helper

**Files:**
- Modify: `scripts/template.html:2221-2226` (remove `renderDecisionsView()`'s local `nsBadgeColour` closure; use `nsColor()` instead)
- Modify: `scripts/template.html:2251` (`renderDecisionsView()`'s usage site)
- Modify: `scripts/template.html:2330-2332` (remove `renderArtefactsView()`'s local `nsBadgeColour` build; use `nsColor()` instead)
- Modify: `scripts/template.html:2358` (`renderArtefactsView()`'s usage site)
- Modify: `scripts/template.html:2944` (insert new `// ── Compare (cross-namespace) ──` section before `// ── Scorecard`)
- Test: `tests/js/dashboard_helpers.test.mjs`

**Interfaces:**
- Produces: `nsColor(namespace)` — pure function, returns a hex colour string for a namespace name, stable across calls (palette indexed by position in the global `NS` array, wraps past 8 namespaces). Returns `'#888'` for a name not found in `NS`.
- Produces: `COMPARE_AXIS_DEFS` — array of `{ key, label, tip }`, 6 entries, fixed display order.
- Produces: `compareAxisValue(ns, key)` — pure function, returns `{ value: number, fallback: boolean }`. `value` is the **raw** (not yet normalised) axis value; `fallback: true` means the underlying data was missing and `value` is the neutral raw midpoint (50).
- Produces: `_compareCentralityByNsIndex()` — pure function, returns an array indexed by `NS`-array position, `degree[i]` = weighted-edge count touching `NS[i]`, using `computeAllEdges(true)` and the same `DEGREE_WEIGHT` map DAG uses (`dep`/`blocking`: 3, `conflict`: 2, `shared`/`concurrent`: 1).
- Consumes: `computeAllEdges(includeSystem)` (already defined at `scripts/template.html`, confirmed to return edges with `.source`/`.target` as raw `NS`-array indices and `.type`).
- Consumes: global `NS` array (already exists).

- [ ] **Step 1: Write the failing unit tests**

In `tests/js/dashboard_helpers.test.mjs`, change the `PURE_HELPERS`/`CONSTS` declarations to (note: `renderCompare` is deliberately **not** in this list yet — it's added in Task 3, once it exists; this task only needs `nsColor`, `compareAxisValue`, and `_compareCentralityByNsIndex`):

```js
const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue', 'radarActiveAxes', 'renderRadar', 'nsColor', 'compareAxisValue', '_compareCentralityByNsIndex'];
const CONSTS = ['RADAR_AXIS_DEFS', 'RADAR_DEFAULT_AXES', 'COMPARE_AXIS_DEFS'];
```

`_compareCentralityByNsIndex()` and `nsColor()` both need the global `NS` array to be defined in the extraction scope — it already is not (the extraction harness only defines `localStorage` and the listed consts/functions). Add a minimal `NS` fixture directly in the test file, since `compareAxisValue`'s and `_compareCentralityByNsIndex`'s tests need namespaces to score against:

```js
const nsFixtureShim = `
  let NS = [
    { namespace: 'ns-a', learnings: [{}], decisions: [{}, {}], externalSignals: [], realityCompletenessScore: 60, goalByMonth: { '2026-06': 70, '2026-07': 80 }, plannedActions: [], reality: '', topTags: [], open: false },
    { namespace: 'ns-b', learnings: [], decisions: [], externalSignals: [{}, {}], realityCompletenessScore: null, goalByMonth: {}, plannedActions: ['depends on ns-a'], reality: '', topTags: [], open: false },
  ];
  let BLOCKING_EDGES = [];
  let SYSTEM_NS = new Set(['global', 'compass']);
`;
```

Update the `source` assembly to include this shim and `computeAllEdges`/`_addEdge` (needed by `_compareCentralityByNsIndex`):

```js
const source = localStorageShim + nsFixtureShim + CONSTS.map(extractConst).join('\n\n') + '\n\n' + ['_addEdge', 'computeAllEdges', ...PURE_HELPERS].map(extractFunction).join('\n\n');
const helpers = new Function(`${source}\nreturn { ${PURE_HELPERS.join(', ')} };`)();
```

Then append these tests at the end of the file:

```js
test('nsColor() assigns a stable colour per namespace, indexed by NS array position', () => {
  assert.equal(helpers.nsColor('ns-a'), '#6366f1');
  assert.equal(helpers.nsColor('ns-b'), '#0ea5e9');
});

test('nsColor() falls back to grey for an unknown namespace name', () => {
  assert.equal(helpers.nsColor('does-not-exist'), '#888');
});

test('compareAxisValue() maturity reads realityCompletenessScore, falls back to raw 50 when null', () => {
  assert.deepEqual(helpers.compareAxisValue({ realityCompletenessScore: 72 }, 'maturity'), { value: 72, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({ realityCompletenessScore: null }, 'maturity'), { value: 50, fallback: true });
});

test('compareAxisValue() learnings/decisions/signals are raw counts, always defined', () => {
  assert.deepEqual(helpers.compareAxisValue({ learnings: [{}, {}, {}] }, 'learnings'), { value: 3, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({ decisions: [] }, 'decisions'), { value: 0, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({ externalSignals: [{}] }, 'signals'), { value: 1, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({}, 'learnings'), { value: 0, fallback: false });
});

test('compareAxisValue() long-run discipline averages goalByMonth, falls back to raw 50 when empty', () => {
  assert.deepEqual(helpers.compareAxisValue({ goalByMonth: { '2026-06': 60, '2026-07': 80 } }, 'longRunDiscipline'), { value: 70, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({ goalByMonth: {} }, 'longRunDiscipline'), { value: 50, fallback: true });
});

test('compareAxisValue() centrality reads the precomputed degree array, always defined', () => {
  const degree = [5, 12];
  assert.deepEqual(helpers.compareAxisValue({ _nsIdx: 0 }, 'centrality', degree), { value: 5, fallback: false });
  assert.deepEqual(helpers.compareAxisValue({ _nsIdx: 1 }, 'centrality', degree), { value: 12, fallback: false });
});

test('_compareCentralityByNsIndex() derives weighted degree from computeAllEdges, indexed by NS position', () => {
  // ns-b's plannedActions text is "depends on ns-a" — computeAllEdges() matches "ns-a" as a
  // substring of ns-b's planned-work text, producing one 'dep' edge {source: 1, target: 0}
  // (weight 3), so both degree[0] and degree[1] end up nonzero.
  const degree = helpers._compareCentralityByNsIndex();
  assert.equal(degree.length, 2);
  assert.ok(degree[0] > 0 || degree[1] > 0, 'at least one namespace should have nonzero centrality from the dep edge');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/dashboard_helpers.test.mjs`
Expected: FAIL with `const COMPARE_AXIS_DEFS not found in template.html` (thrown at module load, before any `test()` runs).

- [ ] **Step 3: Insert the new section into `template.html`**

In `scripts/template.html`, insert this new section immediately before the existing `// ── Scorecard ─────────────────────────────────────────────────────────────────` comment at line 2944 (note: this is the same insertion point used for the per-namespace radar's own section, so this new section now sits between that one and Scorecard):

```js
// ── Compare (cross-namespace) ─────────────────────────────────────────────────

const NS_PALETTE = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6'];

function nsColor(namespace) {
  const i = NS.findIndex(n => n.namespace === namespace);
  return i === -1 ? '#888' : NS_PALETTE[i % NS_PALETTE.length];
}

const COMPARE_AXIS_DEFS = [
  { key: 'maturity',          label: 'Maturity',           tip: 'Reality completeness score' },
  { key: 'learnings',         label: 'Learnings',          tip: 'Active learnings count' },
  { key: 'decisions',         label: 'Decisions',          tip: 'Decisions logged count' },
  { key: 'signals',           label: 'Signals',            tip: 'External research signals count' },
  { key: 'longRunDiscipline', label: 'Long-run discipline', tip: 'Avg goal hit-rate across all history (goalByMonth)' },
  { key: 'centrality',        label: 'Centrality',         tip: 'Weighted dependency/relationship degree vs other namespaces' },
];

function compareAxisValue(ns, key, degreeArr) {
  switch (key) {
    case 'maturity':
      return { value: ns.realityCompletenessScore != null ? ns.realityCompletenessScore : 50, fallback: ns.realityCompletenessScore == null };
    case 'learnings':
      return { value: (ns.learnings || []).length, fallback: false };
    case 'decisions':
      return { value: (ns.decisions || []).length, fallback: false };
    case 'signals':
      return { value: (ns.externalSignals || []).length, fallback: false };
    case 'longRunDiscipline': {
      const months = Object.values(ns.goalByMonth || {});
      const avg = months.length ? months.reduce((s, v) => s + v, 0) / months.length : null;
      return { value: avg != null ? avg : 50, fallback: avg == null };
    }
    case 'centrality': {
      const idx = ns._nsIdx;
      const v = degreeArr && idx != null ? (degreeArr[idx] || 0) : 0;
      return { value: v, fallback: false };
    }
    default:
      return { value: 50, fallback: true };
  }
}

function _compareCentralityByNsIndex() {
  const DEGREE_WEIGHT = { dep: 3, blocking: 3, conflict: 2, shared: 1, concurrent: 1 };
  const degree = new Array(NS.length).fill(0);
  computeAllEdges(true).forEach(e => {
    const w = DEGREE_WEIGHT[e.type] || 1;
    degree[e.source] += w;
    degree[e.target] += w;
  });
  return degree;
}

// ── Scorecard ─────────────────────────────────────────────────────────────────
```

- [ ] **Step 4: Hoist the two duplicated `nsBadgeColour` closures**

In `scripts/template.html`, inside `renderDecisionsView()`, remove:

```js
    const nsBadgeColour = (() => {
      const palette = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6'];
      const map = {};
      NS.forEach((ns, i) => { map[ns.namespace] = palette[i % palette.length]; });
      return map;
    })();

```

(delete the whole block, including the blank line after it). Then change its usage site:

```js
      const bg = nsBadgeColour[d.namespace] || '#888';
```

to:

```js
      const bg = nsColor(d.namespace);
```

In `renderArtefactsView()`, remove:

```js
  const palette = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6'];
  const nsBadgeColour = {};
  NS.forEach((ns, i) => { nsBadgeColour[ns.namespace] = palette[i % palette.length]; });

```

(delete the whole block, including the blank line after it). Then change its usage site:

```js
      const bg       = nsBadgeColour[a.namespace] || '#888';
```

to:

```js
      const bg       = nsColor(a.namespace);
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test tests/js/dashboard_helpers.test.mjs`
Expected: PASS, all tests including the new ones.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS (Decisions/Artefacts namespace badge colours are visually unchanged — same palette, same indexing, now resolved via a shared function).

- [ ] **Step 7: Commit**

```bash
git add scripts/template.html tests/js/dashboard_helpers.test.mjs
git commit -m "feat(dashboard): add Compare macro-axis helper, hoist nsColor from 3 duplicate sites"
```

---

### Task 2: Namespace toggle state — `compareActiveNamespaces()` / `compareToggleNamespace()`

**Files:**
- Modify: `scripts/template.html` (add functions immediately after `_compareCentralityByNsIndex` inserted in Task 1)
- Modify: `scripts/template.html:4587-4594` (`Object.assign(window, {...})` — add `compareToggleNamespace`)
- Modify: `tests/js/render_smoke.test.mjs`

**Interfaces:**
- Consumes: `NS_PALETTE`, `nsColor`, `COMPARE_AXIS_DEFS`, `compareAxisValue`, `_compareCentralityByNsIndex` (Task 1); `urgencyScore(ns)` (already exists, `scripts/template.html:1639`); global `NS`, `document` (pre-existing).
- Produces: `compareActiveNamespaces()` — returns a `Set<string>` of currently active namespace names, reading from `localStorage['compass-compare-namespaces']`, falling back to the **top 5 by `urgencyScore(ns)`** when unset/invalid/empty.
- Produces: `compareToggleNamespace(namespace)` — toggles `namespace`'s membership in the active set (no structural minimum), persists to `localStorage`, and re-renders `#view-compare` if that view exists. Exposed on `window` for its inline `onchange` handler.

- [ ] **Step 1: Write the failing tests**

Append to `tests/js/render_smoke.test.mjs` (the `localStorage` stub already exists in `runScriptInSandbox()` from the per-namespace radar work — reused as-is):

```js
test('compareActiveNamespaces defaults to top 5 by urgencyScore, exercised via compareToggleNamespace persistence', () => {
  const sandbox = runScriptInSandbox();
  const nsNames = sandbox.window.NS ? null : null; // NS is module-private; assert indirectly below
  assert.doesNotThrow(() => sandbox.window.compareToggleNamespace('example-ns-one'), 'compareToggleNamespace() threw');
  const stored = JSON.parse(sandbox.localStorage.getItem('compass-compare-namespaces'));
  assert.ok(Array.isArray(stored), 'toggle must persist an array to localStorage');
});

test('compareToggleNamespace() removes a namespace already in the active set', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.compareToggleNamespace('example-ns-one'); // toggled off if it was a default, or on otherwise
  const first = JSON.parse(sandbox.localStorage.getItem('compass-compare-namespaces'));
  sandbox.window.compareToggleNamespace('example-ns-one'); // toggle back
  const second = JSON.parse(sandbox.localStorage.getItem('compass-compare-namespaces'));
  assert.notDeepEqual(first.sort(), second.sort());
});

test('compareToggleNamespace() allows toggling down to 0 active namespaces (no structural minimum)', () => {
  const sandbox = runScriptInSandbox();
  // The fixture has 2 namespaces (example-ns-one, example-ns-two) — toggle both off from
  // whatever the default (top-5-by-urgency, capped at fixture size) leaves active.
  sandbox.window.compareToggleNamespace('example-ns-one');
  sandbox.window.compareToggleNamespace('example-ns-two');
  assert.doesNotThrow(() => sandbox.window.compareToggleNamespace('example-ns-one'));
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: FAIL — `compareToggleNamespace is not a function`.

- [ ] **Step 3: Implement `compareActiveNamespaces()` and `compareToggleNamespace()`, with a stub `renderCompare()`**

In `scripts/template.html`, immediately after `_compareCentralityByNsIndex`'s closing brace from Task 1, add:

```js
function compareActiveNamespaces() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem('compass-compare-namespaces')); } catch (e) { stored = null; }
  const validNames = NS.map(n => n.namespace);
  if (Array.isArray(stored)) {
    return new Set(stored.filter(n => validNames.includes(n)));
  }
  const top5 = NS.slice().sort((a, b) => urgencyScore(b) - urgencyScore(a)).slice(0, 5).map(n => n.namespace);
  return new Set(top5);
}

function compareToggleNamespace(namespace) {
  const active = compareActiveNamespaces();
  if (active.has(namespace)) active.delete(namespace);
  else active.add(namespace);
  localStorage.setItem('compass-compare-namespaces', JSON.stringify([...active]));
  const container = document.getElementById('view-compare');
  if (container) container.innerHTML = renderCompare();
}

function renderCompare() { return '<div class="empty-state">Compare chart coming in Task 3.</div>'; }
```

(Task 3 replaces this stub `renderCompare` with the real implementation — same function name and no-argument signature, so nothing else in this task changes. Note `renderCompare()` here takes no arguments, unlike `renderRadar(ns, warning)` — Compare has no single "current namespace" context; it always reads `compareActiveNamespaces()` internally.)

- [ ] **Step 4: Add `compareToggleNamespace` to the `Object.assign(window, {...})` export list**

In `scripts/template.html:4587-4594`, change:

```js
Object.assign(window, {
  switchView, switchTab, switchHeatmap, selectCard, setFilter,
  toggleSession, filterLearningType,
  openSearch, closeSearch, closeSearchIfBackdrop, handleSearch, handleSearchKey, handleResultClick,
  toggleDAGSystem, resetDAGLayout, clearDAGFocus,
  mmNodeClick, mmResetView, mmSelectNs, mmToggleBridges, mmRotate,
  radarToggleAxis,
});
```

to:

```js
Object.assign(window, {
  switchView, switchTab, switchHeatmap, selectCard, setFilter,
  toggleSession, filterLearningType,
  openSearch, closeSearch, closeSearchIfBackdrop, handleSearch, handleSearchKey, handleResultClick,
  toggleDAGSystem, resetDAGLayout, clearDAGFocus,
  mmNodeClick, mmResetView, mmSelectNs, mmToggleBridges, mmRotate,
  radarToggleAxis, compareToggleNamespace,
});
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: PASS, all three new tests. `container` will be `null` in these tests (no `view-compare` element exists in the DOM yet, since `switchView('compare')` isn't wired until Task 3) — `compareToggleNamespace()`'s `if (container)` guard means the re-render is simply skipped, and only the `localStorage` persistence (which these tests assert on) is exercised.

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/template.html tests/js/render_smoke.test.mjs
git commit -m "feat(dashboard): add Compare namespace-toggle state with localStorage persistence"
```

---

### Task 3: `renderCompare()` SVG render, nav/view wiring, CSS

**Files:**
- Modify: `scripts/template.html:782` (add `.cmp-*` CSS rules after `.radar-warning`)
- Modify: `scripts/template.html:818` (add `<button class="view-tab" id="vtab-compare" onclick="switchView('compare')">Compare</button>` after the Community nav button)
- Modify: `scripts/template.html:839` (add `<div id="view-compare" style="display:none"></div>` after `view-community`)
- Modify: `scripts/template.html:1622` (`switchView()`'s tab array — add `'compare'`)
- Modify: `scripts/template.html:1634` (`switchView()`'s dispatch — add `if (v === 'compare') renderCompare();`)
- Modify: `scripts/template.html` (replace the Task 2 stub `renderCompare` with the real implementation)
- Modify: `tests/js/render_smoke.test.mjs` (extend the all-tabs test; add Compare-specific tests)
- Modify: `tests/js/dashboard_helpers.test.mjs` (add `renderCompare` to `PURE_HELPERS`, add render-content tests)
- Modify: `tests/test_generate.py` (add one assertion for `vtab-compare`, matching the existing `vtab-mindmap` check style at line 464)

**Interfaces:**
- Consumes: `NS_PALETTE`, `nsColor`, `COMPARE_AXIS_DEFS`, `compareAxisValue`, `_compareCentralityByNsIndex`, `compareActiveNamespaces`, `esc` (all from Tasks 1-2).
- Produces: `renderCompare()` — returns an HTML string for the full `#view-compare` content (namespace checkboxes + legend + SVG, or an empty-state message if 0 namespaces are active).
- Modifies: `switchView(v)`'s tab array and dispatch; nav/view HTML scaffolding.

- [ ] **Step 1: Add the CSS**

In `scripts/template.html`, insert after the existing `.radar-warning { font-size: .74rem; color: #f85149; margin-bottom: .6rem; }` rule at line 782:

```css

    /* ── Compare (cross-namespace) ── */
    .cmp-wrap { padding: .5rem 0; }
    .cmp-controls { display: flex; flex-wrap: wrap; gap: .5rem .9rem; margin-bottom: .75rem; }
    .cmp-ns-label {
      font-size: .74rem; color: var(--muted); display: flex; align-items: center;
      gap: .4rem; cursor: pointer; user-select: none;
    }
    .cmp-ns-label input { cursor: pointer; }
    .cmp-swatch { width: .65rem; height: .65rem; border-radius: 2px; display: inline-block; flex-shrink: 0; }
    .cmp-legend { display: flex; flex-wrap: wrap; gap: .5rem 1rem; margin-bottom: .75rem; font-size: .74rem; color: var(--muted); }
```

- [ ] **Step 2: Add nav button and view div**

In `scripts/template.html`, change:

```html
    <button class="view-tab"        id="vtab-community"     onclick="switchView('community')">Community</button>
  </nav>
```

to:

```html
    <button class="view-tab"        id="vtab-community"     onclick="switchView('community')">Community</button>
    <button class="view-tab"        id="vtab-compare"       onclick="switchView('compare')">Compare</button>
  </nav>
```

Change:

```html
  <div id="view-community"   style="display:none"></div>
  <div id="heatmap-tooltip" class="heatmap-tooltip"></div>
```

to:

```html
  <div id="view-community"   style="display:none"></div>
  <div id="view-compare"     style="display:none"></div>
  <div id="heatmap-tooltip" class="heatmap-tooltip"></div>
```

- [ ] **Step 3: Wire `switchView()`**

In `scripts/template.html`, change:

```js
function switchView(v) {
  if (v !== 'dag' && _dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }
  ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline', 'decisions', 'artefacts', 'mindmap', 'community'].forEach(id => {
    document.getElementById('view-' + id).style.display = id === v ? '' : 'none';
    document.getElementById('vtab-' + id).classList.toggle('active', id === v);
  });
  if (v === 'priorities') renderPriorities();
  if (v === 'scorecard')  renderScorecard();
  if (v === 'dag')        renderDAG();
  if (v === 'heatmap')    renderHeatmap();
  if (v === 'timeline')   renderLearningTimeline();
  if (v === 'decisions')  renderDecisionsView();
  if (v === 'artefacts')  renderArtefactsView();
  if (v === 'mindmap')    renderMindMap();
  if (v === 'community')  renderCommunityView();
}
```

to:

```js
function switchView(v) {
  if (v !== 'dag' && _dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }
  ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline', 'decisions', 'artefacts', 'mindmap', 'community', 'compare'].forEach(id => {
    document.getElementById('view-' + id).style.display = id === v ? '' : 'none';
    document.getElementById('vtab-' + id).classList.toggle('active', id === v);
  });
  if (v === 'priorities') renderPriorities();
  if (v === 'scorecard')  renderScorecard();
  if (v === 'dag')        renderDAG();
  if (v === 'heatmap')    renderHeatmap();
  if (v === 'timeline')   renderLearningTimeline();
  if (v === 'decisions')  renderDecisionsView();
  if (v === 'artefacts')  renderArtefactsView();
  if (v === 'mindmap')    renderMindMap();
  if (v === 'community')  renderCommunityView();
  if (v === 'compare')    document.getElementById('view-compare').innerHTML = renderCompare();
}
```

Note the `compare` dispatch sets `innerHTML` directly, unlike the other views which call a `render*()` function that finds its own container — this matches `renderCompare()`'s no-argument, no-DOM-touching signature (it returns a string, same shape as `renderRadar()`), keeping `renderCompare()` itself pure/testable via the `dashboard_helpers.test.mjs` extraction approach rather than DOM-coupled like `renderScorecard()`.

- [ ] **Step 4: Write the failing tests**

In `tests/js/render_smoke.test.mjs`, change:

```js
  const views = ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline', 'decisions', 'artefacts', 'mindmap', 'community'];
```

to:

```js
  const views = ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline', 'decisions', 'artefacts', 'mindmap', 'community', 'compare'];
```

Append:

```js
test('switchView(\'compare\') renders the namespace picker, legend, and SVG without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.switchView('compare'), 'switchView(\'compare\') threw');
  const html = sandbox.document.getElementById('view-compare').innerHTML;
  assert.match(html, /cmp-controls/);
  assert.match(html, /<svg/);
});

test('compareToggleNamespace() re-render reflects the new namespace set in the DOM once view-compare exists', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.switchView('compare'); // creates #view-compare content, establishing the container
  assert.doesNotThrow(() => sandbox.window.compareToggleNamespace('example-ns-two'));
  const html = sandbox.document.getElementById('view-compare').innerHTML;
  assert.match(html, /cmp-controls/);
});
```

In `tests/js/dashboard_helpers.test.mjs`, add `'renderCompare'` to `PURE_HELPERS`:

```js
const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue', 'radarActiveAxes', 'renderRadar', 'nsColor', 'compareAxisValue', '_compareCentralityByNsIndex', 'renderCompare'];
```

Append:

```js
test('renderCompare() shows an empty-state message when 0 namespaces are active', () => {
  helpers.localStorage.setItem('compass-compare-namespaces', JSON.stringify([]));
  const html = helpers.renderCompare();
  assert.match(html, /select at least 1 namespace/i);
});

test('renderCompare() draws one polygon per active namespace, coloured by nsColor()', () => {
  helpers.localStorage.setItem('compass-compare-namespaces', JSON.stringify(['ns-a', 'ns-b']));
  const html = helpers.renderCompare();
  assert.equal((html.match(/<polygon/g) || []).length >= 2, true, 'expected at least one data polygon per active namespace plus grid rings');
  assert.match(html, new RegExp(helpers.nsColor('ns-a').replace('#', '#')));
});
```

For the second test to work, `helpers.localStorage` must be reachable from the test file — expose it from the `new Function` return statement:

```js
const helpers = new Function(`${source}\nreturn { ${PURE_HELPERS.join(', ')}, localStorage };`)();
```

In `tests/test_generate.py`, near the existing `self.assertIn('id="vtab-mindmap"', template)` at line 464, add:

```python
        self.assertIn('id="vtab-compare"', template)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: FAIL — the render_smoke tests fail because `switchView('compare')` throws (`renderCompare` is still Task 2's stub, which returns valid HTML but without `cmp-controls`/`<svg>`); the dashboard_helpers tests fail because `renderCompare` isn't yet exported from the extraction harness with real content.

Run: `python3 -m pytest tests/test_generate.py -q`
Expected: FAIL — `vtab-compare` not yet in the generated template.

- [ ] **Step 6: Replace the Task 2 stub with the real `renderCompare()` implementation**

In `scripts/template.html`, find the stub added in Task 2 Step 3:

```js
function renderCompare() { return '<div class="empty-state">Compare chart coming in Task 3.</div>'; }
```

Replace it entirely with:

```js
function renderCompare() {
  const active = compareActiveNamespaces();
  const activeNs = NS.filter(ns => active.has(ns.namespace));

  const pickerHtml = NS.slice().sort((a, b) => a.namespace.localeCompare(b.namespace)).map(ns => {
    const checked = active.has(ns.namespace) ? ' checked' : '';
    const col = nsColor(ns.namespace);
    return `<label class="cmp-ns-label">
      <input type="checkbox"${checked} onchange="compareToggleNamespace('${ns.namespace}')">
      <span class="cmp-swatch" style="background:${col}"></span>${esc(ns.namespace)}
    </label>`;
  }).join('');

  if (activeNs.length === 0) {
    return `<div class="cmp-wrap">
      <div class="cmp-controls">${pickerHtml}</div>
      <div class="empty-state">Select at least 1 namespace to compare.</div>
    </div>`;
  }

  const legendHtml = activeNs.map(ns =>
    `<span><span class="cmp-swatch" style="background:${nsColor(ns.namespace)}"></span> ${esc(ns.namespace)}</span>`
  ).join('');

  const degreeArr = _compareCentralityByNsIndex();
  const nsIdxByName = new Map(NS.map((ns, i) => [ns.namespace, i]));
  activeNs.forEach(ns => { ns._nsIdx = nsIdxByName.get(ns.namespace); });

  const N = COMPARE_AXIS_DEFS.length;
  const cx = 210, cy = 200, R = 150;
  const ringFracs = [0.25, 0.5, 0.75, 1];

  function pt(i, frac) {
    const angle = i * 2 * Math.PI / N - Math.PI / 2;
    return { x: cx + Math.cos(angle) * R * frac, y: cy + Math.sin(angle) * R * frac };
  }

  // Raw values per namespace per axis, then min-max normalise each axis across activeNs only.
  const rawByNs = activeNs.map(ns => COMPARE_AXIS_DEFS.map(ax => compareAxisValue(ns, ax.key, degreeArr)));
  const normByNs = rawByNs.map(row => row.slice());
  COMPARE_AXIS_DEFS.forEach((ax, axIdx) => {
    const vals = rawByNs.map(row => row[axIdx].value);
    const min = Math.min(...vals), max = Math.max(...vals), range = max - min;
    normByNs.forEach((row, nsIdx) => {
      row[axIdx] = { value: range === 0 ? 100 : (rawByNs[nsIdx][axIdx].value - min) / range * 100, fallback: rawByNs[nsIdx][axIdx].fallback };
    });
  });

  let svg = `<svg width="420" height="400" viewBox="0 0 420 400" style="display:block;overflow:visible">`;

  ringFracs.forEach(frac => {
    const ringPts = COMPARE_AXIS_DEFS.map((_, i) => { const p = pt(i, frac); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(' ');
    const dash = frac === 1 ? '' : ' stroke-dasharray="2,2"';
    svg += `<polygon points="${ringPts}" fill="none" stroke="var(--border)" stroke-width="1"${dash}/>`;
  });

  COMPARE_AXIS_DEFS.forEach((ax, i) => {
    const edge = pt(i, 1);
    svg += `<line x1="${cx}" y1="${cy}" x2="${edge.x.toFixed(1)}" y2="${edge.y.toFixed(1)}" stroke="var(--border)" stroke-width="1"/>`;
    const label = pt(i, 1.16);
    svg += `<text x="${label.x.toFixed(1)}" y="${label.y.toFixed(1)}" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="monospace" font-weight="600"><title>${esc(ax.tip)}</title>${esc(ax.label)}</text>`;
  });

  activeNs.forEach((ns, nsIdx) => {
    const col = nsColor(ns.namespace);
    const dataPts = normByNs[nsIdx].map((v, i) => {
      const frac = Math.max(0, Math.min(100, v.value)) / 100;
      const p = pt(i, frac);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(' ');
    svg += `<polygon points="${dataPts}" fill="${col}" fill-opacity="0.12" stroke="${col}" stroke-width="2" stroke-linejoin="round"><title>${esc(ns.namespace)}</title></polygon>`;
    normByNs[nsIdx].forEach((v, i) => {
      const frac = Math.max(0, Math.min(100, v.value)) / 100;
      const p = pt(i, frac);
      const dash = v.fallback ? ' stroke-dasharray="2,2"' : '';
      const fillAttr = v.fallback ? 'fill="none" stroke="' + col + '" stroke-width="1.5"' : `fill="${col}"`;
      svg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${v.fallback ? 4 : 3}" ${fillAttr}${dash}><title>${esc(ns.namespace)} — ${esc(COMPARE_AXIS_DEFS[i].label)}: ${v.fallback ? 'insufficient data' : Math.round(rawByNs[nsIdx][i].value) + (['learnings','decisions','signals'].includes(COMPARE_AXIS_DEFS[i].key) ? '' : '%')}</title></circle>`;
    });
  });

  svg += '</svg>';

  return `<div class="cmp-wrap">
    <div class="cmp-controls">${pickerHtml}</div>
    <div class="cmp-legend">${legendHtml}</div>
    ${svg}
  </div>`;
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS, all tests including the new Compare ones.

Run: `python3 -m pytest tests/test_generate.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/template.html tests/js/render_smoke.test.mjs tests/js/dashboard_helpers.test.mjs tests/test_generate.py
git commit -m "feat(dashboard): render cross-namespace Compare radar, wire nav/view/switchView"
```

---

### Task 4: Documentation and manual browser verification

**Files:**
- Modify: `CLAUDE.md` (the "Tab system" section's top-level view tabs list, and a dated section documenting the feature)
- No new source files — verification only

**Interfaces:** None (docs + verification only).

- [ ] **Step 1: Update CLAUDE.md's "Tab system" section**

In `CLAUDE.md`, find the top-level view tabs bullet list (the one starting `- \`overview\` — card grid + namespace detail panel`) and its closing item `- \`community\` — cross-namespace federation feed health + trust registry + adoption Sankey`. Add a new bullet immediately after it:

```
- `compare` — cross-namespace radar comparison: overlaid polygons on 6 fixed macro axes
  (Maturity, Learnings, Decisions, Signals, Long-run discipline, Centrality), namespace
  on/off toggle recalibrates min-max normalisation live; distinct from the per-namespace
  `radar` sub-tab's toggleable micro axes
```

- [ ] **Step 2: Add a dated section documenting the feature**

Append a new section to `CLAUDE.md`, following the style of the "Per-namespace Radar chart (2026-08-14)" section already present (before the "Security" section):

```markdown
---

## Cross-namespace Compare radar chart (2026-08-14)

New top-level `compare` view tab (`renderCompare()`, `template.html`) overlays multiple
namespaces as radar polygons on 6 fixed macro axes — distinct from the per-namespace radar's
10 toggleable micro axes. Surface (2) from that feature's own deferred scope, now built on
explicit request.

Six fixed axes (`COMPARE_AXIS_DEFS`): Maturity (reality completeness), Learnings/Decisions/
Signals (raw counts), Long-run discipline (average of `goalByMonth`, distinct from the
per-namespace radar's "Discipline" axis which only reads the latest session's `goalRate`),
and Centrality (weighted dependency degree from `computeAllEdges(true)`, reusing DAG's own
`DEGREE_WEIGHT` map). No axis picker on this view — the 6 axes are fixed by design.

Namespace toggle state persists to `localStorage['compass-compare-namespaces']` (separate
key from the per-namespace radar's `compass-radar-axes`), defaulting to the top 5 namespaces
by `urgencyScore()` (the same pure function Priorities already uses). Centrality is computed
over the full namespace graph regardless of toggle state — it's an intrinsic relationship
property — but min-max normalisation for every axis is scoped to only the currently active
namespace set, so toggling visibly recalibrates every polygon's shape, not just the newly
added/removed one.

`nsColor(namespace)` was hoisted out of **three** independently-duplicated closures
(`renderDecisionsView()`, `renderArtefactsView()`, and this feature's own first draft) into
one shared function — same palette, same `NS`-array-position indexing as before, now with one
definition instead of three to keep in sync.
```

- [ ] **Step 3: Regenerate the dashboard**

Run: `python3 scripts/compass-dashboard.py`
Expected: Succeeds, writes `~/Downloads/compass-dashboard.html`.

- [ ] **Step 4: Open the generated dashboard in the Browser tool and verify visually**

Serve `~/Downloads/compass-dashboard.html` over local HTTP (the Browser pane's sandbox blocks `file://` — copy it to a scratch directory and use `preview_start` with a `.claude/launch.json` config pointing `python3 -m http.server` at that directory, same approach used for the per-namespace radar's own verification), then:
1. Click the new "Compare" nav tab — verify it shows a namespace checkbox picker, a colour legend, and an SVG with polygons for the default top-5-by-urgency namespaces.
2. Toggle a namespace off — verify the polygon count drops and the remaining polygons visibly reshape (recalibration).
3. Toggle a namespace back on — verify its colour matches its swatch in the picker and legend, and that colour is unchanged from before (stable per-namespace colour).
4. Toggle down to a single namespace — verify it renders as a flat/maxed-out shape (every axis normalises to 100% when there's only one namespace, per the `range === 0 ? 100` branch) rather than throwing or looking broken.
5. Toggle every namespace off — verify the empty-state message appears instead of a broken SVG.
6. Check `read_console_messages` for any errors throughout.
7. Cross-check: open the Decisions and Artefacts tabs and confirm namespace badge colours are visually unchanged from before this session's refactor (same colours, since `nsColor()` preserves the exact same palette and indexing).

- [ ] **Step 5: Commit the documentation update**

```bash
git add CLAUDE.md
git commit -m "docs(dashboard): document cross-namespace Compare radar chart"
```
