# Per-namespace Radar Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable radar (spider) chart as a new "Radar" sub-tab in the namespace detail panel, showing one namespace's health across a user-toggleable set of up to 10 axes.

**Architecture:** Pure frontend addition to `scripts/template.html`'s existing IIFE-wrapped `<script>` block. No Python/data-model changes — every axis reads a field the data layer already produces. A pure `radarAxisValue(ns, key)` helper computes each axis's 0–100 value; `renderRadar(ns)` renders the SVG + checkbox picker; axis selection lives in a module-level `Set` mirrored to `localStorage['compass-radar-axes']` so it persists across namespace switches and page reloads.

**Tech Stack:** Vanilla JS (no D3, no charting library — hand-rolled SVG, per CLAUDE.md's library constraint), hand-rolled Node smoke tests (`node --test`, no new deps).

## Global Constraints

- No new npm/Python dependencies — this repo has zero JS libraries and stdlib-only Python (per CLAUDE.md "Libraries" section).
- Every function invoked from an inline `onclick`/`onchange` HTML attribute must be added to the `Object.assign(window, {...})` list at the end of the `<script>` block (`scripts/template.html:4419`), or it throws `ReferenceError` at click time (CLAUDE.md's fourth documented `<script>`-IIFE trap).
- Any string built with JS template literals containing single quotes must use backticks for the outer string, never single-quoted JS strings (CLAUDE.md's second documented trap).
- User-controlled strings going into `innerHTML` must pass through `esc()` — axis keys/labels/tips here are static config, not user data, so `esc()` on them is precautionary rather than required, but namespace names (`ns.namespace`) already flow through `esc()` elsewhere and must continue to if referenced.
- Run both test suites before considering any task done: `python3 -m pytest tests/ -q` and `node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`.
- Axis selection is **global** (one shared `Set`, not per-namespace) — confirmed in the design spec after explicit brainstorming trade-off discussion.
- Minimum 3 active axes enforced at all times; no maximum (all 10 may be active).

---

### Task 1: Pure axis-value helper, hoisted `healthColor`, and axis config constants

**Files:**
- Modify: `scripts/template.html:2773-2814` (insert new section before `// ── Scorecard ─────`; remove the local `healthColor` declaration at `scripts/template.html:2812-2814` since it becomes module-level)
- Test: `tests/js/dashboard_helpers.test.mjs`

**Interfaces:**
- Produces: `RADAR_AXIS_DEFS` — array of `{ key, label, tip }`, 10 entries, in fixed display order.
- Produces: `RADAR_DEFAULT_AXES` — array of 5 axis keys: `['recency', 'discipline', 'maturity', 'learning', 'focus']`.
- Produces: `radarAxisValue(ns, key)` — pure function, returns `{ value: number (0-100), fallback: boolean }`. `fallback: true` means the underlying data was missing and `value` is the neutral midpoint (50).
- Produces: `healthColor(h)` — pure function (hoisted from inside `renderScorecard()` to module scope), returns a hex colour string for a 0-100 health score. Signature and behaviour unchanged from its current nested form.
- Consumes: `_daysSince(timeAgoStr)` (already defined at `scripts/template.html:1662`).

- [ ] **Step 1: Write the failing unit tests**

Add to `tests/js/dashboard_helpers.test.mjs`, extending the existing `PURE_HELPERS` array and adding new `test()` blocks. Change the array declaration:

```js
const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue'];
```

Then append these tests at the end of the file:

```js
test('healthColor() thresholds match Scorecard bands', () => {
  assert.equal(helpers.healthColor(80), '#3fb950');
  assert.equal(helpers.healthColor(68), '#3fb950');
  assert.equal(helpers.healthColor(50), '#d29922');
  assert.equal(helpers.healthColor(40), '#d29922');
  assert.equal(helpers.healthColor(10), '#f85149');
});

test('radarAxisValue() computes recency from days since last session', () => {
  const ns = { open: false, lastClose: '5d ago' };
  const r = helpers.radarAxisValue(ns, 'recency');
  assert.equal(r.fallback, false);
  // 100 - 5 * (100/30) = ~83.33
  assert.ok(Math.abs(r.value - 83.33) < 0.1);
});

test('radarAxisValue() falls back to 50 with fallback:true when discipline/maturity data is missing', () => {
  const ns = { goalRate: null, realityCompletenessScore: null };
  const discipline = helpers.radarAxisValue(ns, 'discipline');
  const maturity = helpers.radarAxisValue(ns, 'maturity');
  assert.deepEqual(discipline, { value: 50, fallback: true });
  assert.deepEqual(maturity, { value: 50, fallback: true });
});

test('radarAxisValue() uses real discipline/maturity values when present, fallback:false', () => {
  const ns = { goalRate: 72, realityCompletenessScore: 61 };
  assert.deepEqual(helpers.radarAxisValue(ns, 'discipline'), { value: 72, fallback: false });
  assert.deepEqual(helpers.radarAxisValue(ns, 'maturity'), { value: 61, fallback: false });
});

test('radarAxisValue() caps learning at 2 learnings/session = 100%', () => {
  const ns = { sessionCount: 2, learnings: [1, 2, 3, 4] }; // 2/session
  assert.deepEqual(helpers.radarAxisValue(ns, 'learning'), { value: 100, fallback: false });
  const nsZero = { sessionCount: 0, learnings: [] };
  assert.deepEqual(helpers.radarAxisValue(nsZero, 'learning'), { value: 0, fallback: false });
});

test('radarAxisValue() focus approaches 100 with zero deferred items, drops as deferred grows', () => {
  assert.deepEqual(helpers.radarAxisValue({ deferred: [] }, 'focus'), { value: 100, fallback: false });
  const withThree = helpers.radarAxisValue({ deferred: [1, 2, 3] }, 'focus');
  assert.ok(withThree.value < 30 && withThree.value > 20); // 1/(1+3)*100 = 25
});

test('radarAxisValue() corpus health and exploration ratio fall back when null', () => {
  const ns = { corpusHealth: null, explorationRatio: null };
  assert.deepEqual(helpers.radarAxisValue(ns, 'corpusHealth'), { value: 50, fallback: true });
  assert.deepEqual(helpers.radarAxisValue(ns, 'explorationRatio'), { value: 50, fallback: true });
});

test('radarAxisValue() corpus health and exploration ratio read the .score/.ratio field when present', () => {
  const ns = { corpusHealth: { score: 88 }, explorationRatio: { ratio: 30.5 } };
  assert.deepEqual(helpers.radarAxisValue(ns, 'corpusHealth'), { value: 88, fallback: false });
  assert.deepEqual(helpers.radarAxisValue(ns, 'explorationRatio'), { value: 30.5, fallback: false });
});

test('radarAxisValue() quality trend is % of high-quality sessions, 50 when no sessions classified', () => {
  const ns = { qualityDist: { high: 3, neutral: 1, poor: 0 } };
  assert.deepEqual(helpers.radarAxisValue(ns, 'qualityTrend'), { value: 75, fallback: false });
  const nsEmpty = { qualityDist: { high: 0, neutral: 0, poor: 0 } };
  assert.deepEqual(helpers.radarAxisValue(nsEmpty, 'qualityTrend'), { value: 50, fallback: true });
});

test('radarAxisValue() cadence pressure inverts the count of due flags out of 3', () => {
  const nsNoneDue = { researchDue: false, codeReviewDue: false, dreamDue: false };
  assert.deepEqual(helpers.radarAxisValue(nsNoneDue, 'cadencePressure'), { value: 100, fallback: false });
  const nsAllDue = { researchDue: true, codeReviewDue: true, dreamDue: true };
  assert.deepEqual(helpers.radarAxisValue(nsAllDue, 'cadencePressure'), { value: 0, fallback: false });
});

test('radarAxisValue() retrieval freshness drops 10 points per stale-surfacing learning, floors at 0', () => {
  assert.deepEqual(helpers.radarAxisValue({ retrievalStaleCount: 0 }, 'retrievalFreshness'), { value: 100, fallback: false });
  assert.deepEqual(helpers.radarAxisValue({ retrievalStaleCount: 15 }, 'retrievalFreshness'), { value: 0, fallback: false });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/js/dashboard_helpers.test.mjs`
Expected: FAIL with `function healthColor() not found in template.html` (thrown by `extractFunction()` before any `test()` block even runs, since `PURE_HELPERS.map(extractFunction)` runs at module load).

- [ ] **Step 3: Insert the new section into `template.html`**

In `scripts/template.html`, insert this new section immediately before the existing `// ── Scorecard ─────────────────────────────────────────────────────────────────` comment at line 2773:

```js
// ── Radar chart (namespace detail) ────────────────────────────────────────────

function healthColor(h) {
  return h >= 68 ? '#3fb950' : h >= 40 ? '#d29922' : '#f85149';
}

const RADAR_AXIS_DEFS = [
  { key: 'recency',            label: 'Recency',            tip: 'Days since last session (recent = high)' },
  { key: 'discipline',         label: 'Discipline',         tip: 'Avg goal completion %' },
  { key: 'maturity',           label: 'Maturity',           tip: 'Reality completeness score (% of bullets marked done)' },
  { key: 'learning',           label: 'Learning',           tip: 'Learnings per session' },
  { key: 'focus',              label: 'Focus',              tip: 'Low deferred items (fewer = high)' },
  { key: 'corpusHealth',       label: 'Corpus health',      tip: 'Learnings corpus quality score (needs ≥ 3 active learnings)' },
  { key: 'explorationRatio',   label: 'Exploration ratio',  tip: 'Explore vs exploit balance across sessions (needs ≥ 2 typed sessions)' },
  { key: 'qualityTrend',       label: 'Quality trend',      tip: '% of recent sessions classified high-quality' },
  { key: 'cadencePressure',    label: 'Cadence pressure',   tip: 'Inverted — high score means nothing overdue (review/research/dream)' },
  { key: 'retrievalFreshness', label: 'Retrieval freshness', tip: 'Inverted — high score means few stale-but-still-surfacing learnings' },
];

const RADAR_DEFAULT_AXES = ['recency', 'discipline', 'maturity', 'learning', 'focus'];

const _radar = { warning: '' };

function radarAxisValue(ns, key) {
  switch (key) {
    case 'recency': {
      const days = _daysSince(ns.open ? ns.lastOpen : ns.lastClose);
      return { value: Math.max(0, Math.min(100, 100 - days * (100 / 30))), fallback: false };
    }
    case 'discipline':
      return { value: ns.goalRate != null ? ns.goalRate : 50, fallback: ns.goalRate == null };
    case 'maturity':
      return { value: ns.realityCompletenessScore != null ? ns.realityCompletenessScore : 50, fallback: ns.realityCompletenessScore == null };
    case 'learning': {
      const perSession = ns.sessionCount > 0 ? (ns.learnings || []).length / ns.sessionCount : 0;
      return { value: Math.min(100, perSession / 2 * 100), fallback: false };
    }
    case 'focus':
      return { value: (1 / (1 + (ns.deferred || []).length)) * 100, fallback: false };
    case 'corpusHealth':
      return { value: ns.corpusHealth ? ns.corpusHealth.score : 50, fallback: !ns.corpusHealth };
    case 'explorationRatio':
      return { value: ns.explorationRatio ? ns.explorationRatio.ratio : 50, fallback: !ns.explorationRatio };
    case 'qualityTrend': {
      const qd = ns.qualityDist || {};
      const total = (qd.high || 0) + (qd.neutral || 0) + (qd.poor || 0);
      return { value: total > 0 ? (qd.high || 0) / total * 100 : 50, fallback: total === 0 };
    }
    case 'cadencePressure': {
      const dueCount = [ns.researchDue, ns.codeReviewDue, ns.dreamDue].filter(Boolean).length;
      return { value: 100 - (dueCount / 3 * 100), fallback: false };
    }
    case 'retrievalFreshness': {
      const stale = ns.retrievalStaleCount || 0;
      return { value: 100 - Math.min(100, stale * 10), fallback: false };
    }
    default:
      return { value: 50, fallback: true };
  }
}

```

Then remove the now-duplicate local declaration inside `renderScorecard()` (originally at line 2812-2814, now shifted later by the insertion — search for the exact text):

```js
  function healthColor(h) {
    return h >= 68 ? '#3fb950' : h >= 40 ? '#d29922' : '#f85149';
  }

```

Delete that whole block (including the blank line after it) from inside `renderScorecard()`. Its call site `healthColor(r.health)` a few lines below is unchanged — it now resolves to the module-level function via closure.

- [ ] **Step 4: Run tests to verify they pass**

Run: `node --test tests/js/dashboard_helpers.test.mjs`
Expected: PASS, all tests including the new ones.

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS (Scorecard's own rendering is unaffected — same formula, now resolved from an outer scope instead of a local declaration).

- [ ] **Step 6: Commit**

```bash
git add scripts/template.html tests/js/dashboard_helpers.test.mjs
git commit -m "feat(dashboard): add radar axis-value helper and hoist healthColor for reuse"
```

---

### Task 2: Axis-selection state — `radarActiveAxes()` / `radarToggleAxis()`

**Files:**
- Modify: `scripts/template.html` (add functions immediately after the `radarAxisValue` function inserted in Task 1)
- Modify: `scripts/template.html:4419-4425` (`Object.assign(window, {...})` — add `radarToggleAxis`)
- Modify: `tests/js/render_smoke.test.mjs` (add `localStorage` stub to the sandbox; add new tests)

**Interfaces:**
- Consumes: `RADAR_AXIS_DEFS`, `RADAR_DEFAULT_AXES`, `_radar` (from Task 1).
- Consumes: global `NS` array, global `Search` object (`Search.selected`), global `document` (all pre-existing).
- Produces: `radarActiveAxes()` — returns a `Set<string>` of currently active axis keys, reading from `localStorage['compass-radar-axes']` with fallback to `RADAR_DEFAULT_AXES` when unset/invalid/fewer than 3 keys.
- Produces: `radarToggleAxis(key)` — toggles `key`'s membership in the active set (blocked if it would drop below 3 active axes, setting `_radar.warning` instead), persists to `localStorage`, and re-renders `#tab-radar` if a namespace is currently selected. Exposed on `window` for its inline `onchange` handler.

- [ ] **Step 1: Add the `localStorage` stub to the render_smoke sandbox**

In `tests/js/render_smoke.test.mjs`, inside `runScriptInSandbox()`, add the stub alongside the other sandbox globals (right after the `sandbox.document = makeDocumentStub();` line):

```js
  sandbox.localStorage = (() => {
    const store = new Map();
    return {
      getItem:    k => (store.has(k) ? store.get(k) : null),
      setItem:    (k, v) => store.set(k, String(v)),
      removeItem: k => store.delete(k),
    };
  })();
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/js/render_smoke.test.mjs`. These test `radarActiveAxes()`'s default-set behaviour indirectly through `radarToggleAxis()`'s persisted output, since `radarActiveAxes()` itself is intentionally not exported to `window` (only the checkbox's `onchange` handler, `radarToggleAxis`, needs to be):

```js
test('radarToggleAxis() starting from defaults adds a new axis to the persisted set', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.radarToggleAxis('corpusHealth'), 'radarToggleAxis() threw');
  const stored = JSON.parse(sandbox.localStorage.getItem('compass-radar-axes'));
  assert.deepEqual(stored.slice().sort(), ['corpusHealth', 'discipline', 'focus', 'learning', 'maturity', 'recency'].sort());
});

test('radarToggleAxis() removes a default axis when more than 3 remain active', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  sandbox.window.radarToggleAxis('learning');
  const stored = JSON.parse(sandbox.localStorage.getItem('compass-radar-axes'));
  assert.deepEqual(stored.slice().sort(), ['discipline', 'focus', 'maturity', 'recency'].sort());
});

test('radarToggleAxis() refuses to drop below 3 active axes', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  // Default is 5 axes; remove down to 3, the 3rd removal attempt must be a no-op.
  sandbox.window.radarToggleAxis('learning');
  sandbox.window.radarToggleAxis('focus');
  const before = sandbox.localStorage.getItem('compass-radar-axes');
  sandbox.window.radarToggleAxis('maturity'); // would drop to 2 — must be blocked
  const after = sandbox.localStorage.getItem('compass-radar-axes');
  assert.equal(before, after, 'axis set must be unchanged when the minimum would be violated');
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: FAIL — `radarToggleAxis is not a function` (not yet defined/exported).

- [ ] **Step 4: Implement `radarActiveAxes()` and `radarToggleAxis()`**

In `scripts/template.html`, immediately after the `radarAxisValue` function body from Task 1, add:

```js
function radarActiveAxes() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem('compass-radar-axes')); } catch (e) { stored = null; }
  const validKeys = RADAR_AXIS_DEFS.map(a => a.key);
  const keys = Array.isArray(stored) ? stored.filter(k => validKeys.includes(k)) : [];
  return new Set(keys.length >= 3 ? keys : RADAR_DEFAULT_AXES);
}

function radarToggleAxis(key) {
  const active = radarActiveAxes();
  if (active.has(key)) {
    if (active.size <= 3) {
      _radar.warning = 'At least 3 axes needed — pick another before removing this one.';
    } else {
      active.delete(key);
      _radar.warning = '';
    }
  } else {
    active.add(key);
    _radar.warning = '';
  }
  localStorage.setItem('compass-radar-axes', JSON.stringify([...active]));
  if (Search.selected >= 0) {
    const tabEl = document.getElementById('tab-radar');
    if (tabEl) tabEl.innerHTML = renderRadar(NS[Search.selected]);
  }
}
```

(`renderRadar` doesn't exist yet — it's added in Task 3. This will not compile-error since JS function declarations are call-order independent within the same scope, but `radarToggleAxis` can't be *exercised* end-to-end until Task 3 lands. That's fine: Step 3's failure mode above is about the function not existing at all, and Step 5 below only asserts the persistence/blocking behavior, not the re-render — `renderRadar` is referenced but not called unless `Search.selected >= 0`, and even then, since Task 3 hasn't landed, calling `radarToggleAxis` after `selectCard(0)` WILL throw `ReferenceError: renderRadar is not defined`. To keep this task independently testable, temporarily stub `renderRadar` as a no-op at the bottom of this same inserted block:)

```js
function renderRadar(ns) { return '<div class="empty-state">Radar chart coming in Task 3.</div>'; }
```

(Task 3 will replace this stub with the real implementation — same function name and signature, so nothing else in this task changes.)

- [ ] **Step 5: Add `radarToggleAxis` to the `Object.assign(window, {...})` export list**

In `scripts/template.html:4419-4425`, change:

```js
Object.assign(window, {
  switchView, switchTab, switchHeatmap, selectCard, setFilter,
  toggleSession, filterLearningType,
  openSearch, closeSearch, closeSearchIfBackdrop, handleSearch, handleSearchKey, handleResultClick,
  toggleDAGSystem, resetDAGLayout, clearDAGFocus,
  mmNodeClick, mmResetView, mmSelectNs, mmToggleBridges, mmRotate,
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
  radarToggleAxis,
});
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: PASS, all three new tests. Note these tests don't touch `#tab-radar`'s rendered content at all — that DOM wiring doesn't land until Task 3, and these tests only assert on `radarToggleAxis()`'s `localStorage` side effect, which is fully implemented by this task's Step 4.

- [ ] **Step 7: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/template.html tests/js/render_smoke.test.mjs
git commit -m "feat(dashboard): add radar axis-selection state with localStorage persistence"
```

---

### Task 3: `renderRadar()` SVG render, CSS, and wiring into the namespace detail panel

**Files:**
- Modify: `scripts/template.html:772-773` (add `.radar-*` CSS rules before `</style>`)
- Modify: `scripts/template.html` (replace the Task 2 stub `renderRadar` with the real implementation)
- Modify: `scripts/template.html:929-988` (`renderDetail()` tabs/labels, `renderTab()` dispatch)
- Modify: `tests/js/render_smoke.test.mjs` (extend the sub-tab list, add radar-specific content assertions)

**Interfaces:**
- Consumes: `RADAR_AXIS_DEFS`, `radarActiveAxes()`, `radarAxisValue(ns, key)`, `healthColor(h)`, `_radar` (all from Tasks 1–2).
- Produces: `renderRadar(ns)` — returns an HTML string for the full `#tab-radar` content (axis checkboxes + SVG or an empty-state message if fewer than 3 axes are somehow active).
- Modifies: `renderDetail(ns)`'s `tabs`/`labels` to include `'radar'` → `'Radar'`; `renderTab(tab, ns)` to dispatch `'radar'` to `renderRadar(ns)`.

- [ ] **Step 1: Add the CSS**

In `scripts/template.html`, insert before the `</style>` tag at line 773 (right after the existing `.scard-bar-fg` rule):

```css
    /* ── Radar chart ── */
    .radar-wrap { padding: .25rem 0; }
    .radar-controls { display: flex; flex-wrap: wrap; gap: .5rem .9rem; margin-bottom: .75rem; }
    .radar-axis-label {
      font-size: .74rem; color: var(--muted); display: flex; align-items: center;
      gap: .35rem; cursor: pointer; user-select: none;
    }
    .radar-axis-label input { cursor: pointer; }
    .radar-warning { font-size: .74rem; color: #f85149; margin-bottom: .6rem; }
```

- [ ] **Step 2: Write the failing render_smoke test**

Append to `tests/js/render_smoke.test.mjs`:

```js
test('switchTab(\'radar\') renders the axis picker and SVG without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.switchTab('radar'), 'switchTab(\'radar\') threw');
  const html = sandbox.document.getElementById('tab-radar').innerHTML;
  assert.match(html, /radar-controls/);
  assert.match(html, /<svg/);
  assert.match(html, /Recency/);
});

test('radarToggleAxis() re-render reflects the new axis set in the DOM', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  sandbox.window.radarToggleAxis('corpusHealth');
  const html = sandbox.document.getElementById('tab-radar').innerHTML;
  assert.match(html, /Corpus health/);
});
```

Also update the existing `switchTab()` sub-tab test (from before this feature existed) to include `'radar'`:

```js
test('switchTab() renders each namespace-detail sub-tab without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  for (const t of ['state', 'learnings', 'decisions', 'history', 'tasks', 'radar', 'signals']) {
    assert.doesNotThrow(() => sandbox.window.switchTab(t), `switchTab('${t}') threw`);
  }
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: FAIL — `switchTab('radar')` throws because `renderTab()` doesn't dispatch `'radar'` yet (returns `''`, then `document.getElementById('tab-radar')` returns `null` in the stub since that id was never created, so `.innerHTML` access throws or the regex match fails).

- [ ] **Step 4: Replace the Task 2 stub with the real `renderRadar()` implementation**

In `scripts/template.html`, find the stub added in Task 2 Step 4:

```js
function renderRadar(ns) { return '<div class="empty-state">Radar chart coming in Task 3.</div>'; }
```

Replace it entirely with:

```js
function renderRadar(ns) {
  const active = radarActiveAxes();
  const axes = RADAR_AXIS_DEFS.filter(ax => active.has(ax.key));
  const N = axes.length;

  const pickerHtml = RADAR_AXIS_DEFS.map(ax => {
    const checked = active.has(ax.key) ? ' checked' : '';
    return `<label class="radar-axis-label" title="${esc(ax.tip)}">
      <input type="checkbox"${checked} onchange="radarToggleAxis('${ax.key}')">${esc(ax.label)}
    </label>`;
  }).join('');

  const warningHtml = _radar.warning ? `<div class="radar-warning">${esc(_radar.warning)}</div>` : '';

  if (N < 3) {
    return `<div class="radar-wrap">
      <div class="radar-controls">${pickerHtml}</div>
      ${warningHtml}
      <div class="empty-state">Select at least 3 axes to draw the radar.</div>
    </div>`;
  }

  const cx = 210, cy = 200, R = 150;
  const ringFracs = [0.25, 0.5, 0.75, 1];

  function pt(i, frac) {
    const angle = i * 2 * Math.PI / N - Math.PI / 2;
    return { x: cx + Math.cos(angle) * R * frac, y: cy + Math.sin(angle) * R * frac };
  }

  let svg = `<svg width="420" height="400" viewBox="0 0 420 400" style="display:block;overflow:visible">`;

  ringFracs.forEach(frac => {
    const ringPts = axes.map((_, i) => { const p = pt(i, frac); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(' ');
    const dash = frac === 1 ? '' : ' stroke-dasharray="2,2"';
    svg += `<polygon points="${ringPts}" fill="none" stroke="var(--border)" stroke-width="1"${dash}/>`;
  });

  axes.forEach((ax, i) => {
    const edge = pt(i, 1);
    svg += `<line x1="${cx}" y1="${cy}" x2="${edge.x.toFixed(1)}" y2="${edge.y.toFixed(1)}" stroke="var(--border)" stroke-width="1"/>`;
    const label = pt(i, 1.16);
    svg += `<text x="${label.x.toFixed(1)}" y="${label.y.toFixed(1)}" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="monospace" font-weight="600"><title>${esc(ax.tip)}</title>${esc(ax.label)}</text>`;
  });

  const values = axes.map(ax => radarAxisValue(ns, ax.key));
  const mean = values.reduce((s, v) => s + v.value, 0) / values.length;
  const col = healthColor(mean);
  const dataPts = values.map((v, i) => {
    const frac = Math.max(0, Math.min(100, v.value)) / 100;
    const p = pt(i, frac);
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(' ');
  svg += `<polygon points="${dataPts}" fill="${col}" fill-opacity="0.22" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>`;

  values.forEach((v, i) => {
    const frac = Math.max(0, Math.min(100, v.value)) / 100;
    const p = pt(i, frac);
    if (v.fallback) {
      svg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="none" stroke="${col}" stroke-width="1.5" stroke-dasharray="2,2"><title>${esc(axes[i].label)}: insufficient data, showing neutral midpoint</title></circle>`;
    } else {
      svg += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="${col}"><title>${esc(axes[i].label)}: ${Math.round(v.value)}%</title></circle>`;
    }
  });

  svg += '</svg>';

  return `<div class="radar-wrap">
    <div class="radar-controls">${pickerHtml}</div>
    ${warningHtml}
    ${svg}
  </div>`;
}
```

- [ ] **Step 5: Wire `radar` into `renderDetail()` and `renderTab()`**

In `scripts/template.html:929-936`, change:

```js
  const tabs   = [...baseTabs, 'tasks', ...(hasSignals ? ['signals'] : [])];
  const labels = {
    state:     'State',
    learnings: `Learnings (${ns.learnings.length})`,
    decisions: `Decisions (${(ns.decisions || []).length})`,
    history:   `History (${ns.sessionCount})`,
    tasks:     derivedTasks.length ? `Tasks (${derivedTasks.length})` : 'Tasks',
    signals:   `Signals (${(ns.externalSignals || []).length})`,
  };
```

to:

```js
  const tabs   = [...baseTabs, 'tasks', 'radar', ...(hasSignals ? ['signals'] : [])];
  const labels = {
    state:     'State',
    learnings: `Learnings (${ns.learnings.length})`,
    decisions: `Decisions (${(ns.decisions || []).length})`,
    history:   `History (${ns.sessionCount})`,
    tasks:     derivedTasks.length ? `Tasks (${derivedTasks.length})` : 'Tasks',
    radar:     'Radar',
    signals:   `Signals (${(ns.externalSignals || []).length})`,
  };
```

In `scripts/template.html:980-988`, change:

```js
function renderTab(tab, ns) {
  if (tab === 'state')     return renderState(ns);
  if (tab === 'learnings') return renderLearnings(ns);
  if (tab === 'decisions') return renderDecisions(ns);
  if (tab === 'history')   return renderHistory(ns);
  if (tab === 'tasks')     return renderTasks(ns);
  if (tab === 'signals')   return renderExternalSignals(ns);
  return '';
}
```

to:

```js
function renderTab(tab, ns) {
  if (tab === 'state')     return renderState(ns);
  if (tab === 'learnings') return renderLearnings(ns);
  if (tab === 'decisions') return renderDecisions(ns);
  if (tab === 'history')   return renderHistory(ns);
  if (tab === 'tasks')     return renderTasks(ns);
  if (tab === 'radar')     return renderRadar(ns);
  if (tab === 'signals')   return renderExternalSignals(ns);
  return '';
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `node --test tests/js/render_smoke.test.mjs`
Expected: PASS, all tests including the new radar ones.

- [ ] **Step 7: Run the full test suite to confirm no regression**

Run: `python3 -m pytest tests/ -q && node --test tests/js/dashboard_helpers.test.mjs tests/js/render_smoke.test.mjs`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/template.html tests/js/render_smoke.test.mjs
git commit -m "feat(dashboard): render per-namespace radar chart, wire into detail panel"
```

---

### Task 4: Documentation and manual browser verification

**Files:**
- Modify: `CLAUDE.md` (this skill's own project instructions — "Tab system" section's namespace detail sub-tabs list, and a dated note in the style of the existing DAG/Mind Map sections documenting the new feature and any gotchas hit during implementation)
- No new source files — verification only, using the generated HTML output

**Interfaces:** None (docs + verification only).

- [ ] **Step 1: Update CLAUDE.md's "Tab system" section**

In `CLAUDE.md`, find:

```
**Namespace detail sub-tabs** (`.tab-btn`, `switchTab(t)`) — panels within a selected namespace:
`state`, `learnings`, `decisions`, `history`, `tasks`
```

Change to:

```
**Namespace detail sub-tabs** (`.tab-btn`, `switchTab(t)`) — panels within a selected namespace:
`state`, `learnings`, `decisions`, `history`, `tasks`, `radar` (added 2026-08-14; `signals` also
exists conditionally when `externalSignals` is non-empty — `renderDetail()`'s `tabs` array in
`template.html` is the authoritative list)
```

- [ ] **Step 2: Add a dated section documenting the feature**

Append a new section to `CLAUDE.md`, following the style of the existing "Mind Map view" and "DAG force-simulation tuning" sections (before the "Security" section):

```markdown
---

## Per-namespace Radar chart (2026-08-14)

New `radar` sub-tab in the namespace detail panel (`renderRadar(ns)`, `template.html`) shows
one namespace's health as a configurable radar/spider chart — distinct from the existing
cross-namespace Scorecard tab (parallel coordinates across all namespaces), which is
untouched by this feature.

Ten toggleable axes (`RADAR_AXIS_DEFS`): Scorecard's original 5 (recency, discipline,
maturity, learning, focus — on by default) plus 5 richer per-namespace health signals
(corpus health, exploration ratio, quality trend, cadence pressure, retrieval freshness).
Each axis is normalised to 0–100 independently per namespace via `radarAxisValue(ns, key)` —
unlike Scorecard, there's no cross-namespace min-max normalisation here, since only one
polygon is ever drawn. Axis selection is global (not per-namespace), persisted to
`localStorage['compass-radar-axes']`, enforced at a minimum of 3 active axes.

Null/insufficient-data axes (corpus health needs ≥3 learnings, exploration ratio needs ≥2
typed sessions, quality trend needs ≥1 classified session) render as a dashed/hollow point at
the neutral midpoint (50) rather than being dropped — keeps the polygon shape stable across
namespace switches, with a tooltip explaining why.

`healthColor()` was hoisted out of `renderScorecard()`'s closure to module scope so both
Scorecard and the radar chart can share the same ≥68 green / ≥40 amber / red thresholds —
if retuning those thresholds, only one definition needs to change now.
```

(If any additional gotcha was hit during implementation that isn't captured above — e.g. a
different string-literal trap, an unexpected null shape — add it here before committing.)

- [ ] **Step 3: Regenerate the dashboard**

Run: `python3 scripts/compass-dashboard.py`
Expected: Succeeds, writes `~/Downloads/compass-dashboard.html`.

- [ ] **Step 4: Open the generated dashboard in the Browser tool and verify visually**

Use `mcp__Claude_Browser__preview_start` with `{url: "file://<path to ~/Downloads/compass-dashboard.html>"}`, then:
1. Click a namespace card to open its detail panel.
2. Click the "Radar" sub-tab — verify the SVG renders with 5 default axes and a filled polygon.
3. Toggle on "Corpus health" — verify the polygon recalculates to 6 points and the label appears.
4. Toggle off axes down to 3, then attempt a 4th removal — verify the warning message appears and the axis stays checked.
5. Take a screenshot (`computer` tool, `action: "screenshot"`) of the Radar tab for the record.
6. Check `read_console_messages` for any errors during these interactions.

- [ ] **Step 5: Commit the documentation update**

```bash
git add CLAUDE.md
git commit -m "docs(dashboard): document per-namespace radar chart sub-tab"
```
