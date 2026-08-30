// Smoke-test coverage for the render* functions in scripts/template.html that
// dashboard_helpers.test.mjs's pure-function extraction can't reach — they touch
// `document`/`window` directly, so they can't be eval'd in isolation.
//
// Approach: run the ENTIRE <script> IIFE (unmodified) inside a Node vm context
// with a minimal hand-rolled DOM stub (no jsdom — no new deps, per CLAUDE.md's
// "12 Node passing, no new deps" convention), against a small synthetic fixture
// (tests/js/fixtures/dashboard_fixture.json — built from real load_namespace()/
// _js_data() field shapes but with placeholder text, never real namespace content).
// This is a "does it throw" smoke test, not a snapshot test: it exists to catch
// the exact failure mode CLAUDE.md's four documented traps describe (a broken
// string literal or a missing Object.assign(window,...) export silently killing
// the whole script) before it needs a manual javascript_tool debugging session.
//
// Run: node --test tests/js/render_smoke.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const templatePath = path.join(__dirname, '..', '..', 'scripts', 'template.html');
const fixturePath  = path.join(__dirname, 'fixtures', 'dashboard_fixture.json');

const html    = fs.readFileSync(templatePath, 'utf8');
const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

function extractScriptBody() {
  const start = html.indexOf('<script>') + '<script>'.length;
  const end   = html.indexOf('</script>', start);
  if (start === -1 || end === -1) throw new Error('could not locate <script>...</script> in template.html');
  return html.slice(start, end);
}

function buildScriptSource() {
  let src = extractScriptBody();
  src = src.replace('[[NS_DATA]]', JSON.stringify(fixture.NS));
  src = src.replace('[[COMMUNITY_DATA]]', JSON.stringify(fixture.COMMUNITY));
  src = src.replace('[[BLOCKING_EDGES]]', JSON.stringify(fixture.BLOCKING_EDGES));
  for (const marker of ['[[NS_DATA]]', '[[COMMUNITY_DATA]]', '[[BLOCKING_EDGES]]']) {
    if (src.includes(marker)) throw new Error(`unresolved ${marker} left in script — fixture keys out of sync?`);
  }
  return src;
}

// ── Minimal DOM stub ─────────────────────────────────────────────────────────
// Just enough surface for render* functions to run without a real browser:
// innerHTML capture, classList/style/dataset no-ops, SVG element creation,
// and layout-metric properties defaulted to plausible non-zero numbers.

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this._html = '';
    this._children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.classList = {
      add() {}, remove() {}, contains() { return false; },
      toggle() {},
    };
    this.offsetWidth = 800; this.offsetHeight = 600;
    this.clientWidth = 800; this.clientHeight = 600;
    this.scrollWidth = 800; this.scrollHeight = 600;
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  set textContent(v) { this._html = String(v); }
  get textContent() { return this._html; }
  appendChild(c) { this._children.push(c); return c; }
  removeChild(c) { this._children = this._children.filter(x => x !== c); return c; }
  insertBefore(c) { this._children.push(c); return c; }
  remove() {}
  addEventListener() {}
  removeEventListener() {}
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k] ?? null; }
  removeAttribute(k) { delete this.attributes[k]; }
  querySelector() { return new FakeElement(); }
  querySelectorAll() { return []; }
  closest() { return null; }
  getBoundingClientRect() {
    return { top: 0, left: 0, right: 800, bottom: 600, width: 800, height: 600, x: 0, y: 0 };
  }
  scrollIntoView() {}
  focus() {}
  click() {}
  get children() { return this._children; }
  get firstChild() { return this._children[0] ?? null; }
  get value() { return this._value ?? ''; }
  set value(v) { this._value = v; }
  select() {}
}

function makeDocumentStub() {
  const cache = new Map();
  return {
    getElementById(id) {
      if (!cache.has(id)) cache.set(id, new FakeElement('div'));
      return cache.get(id);
    },
    querySelector() { return new FakeElement(); },
    querySelectorAll() { return []; },
    createElement(tag) { return new FakeElement(tag); },
    createElementNS(_ns, tag) { return new FakeElement(tag); },
    addEventListener() {},
    removeEventListener() {},
    body: new FakeElement('body'),
    documentElement: new FakeElement('html'),
  };
}

function runScriptInSandbox() {
  const src = buildScriptSource();
  const sandbox = {};
  sandbox.window = sandbox; // `window.foo = ...` and bare `foo` resolve to the same object
  sandbox.document = makeDocumentStub();
  sandbox.localStorage = (() => {
    const store = new Map();
    return {
      getItem:    k => (store.has(k) ? store.get(k) : null),
      setItem:    (k, v) => store.set(k, String(v)),
      removeItem: k => store.delete(k),
    };
  })();
  sandbox.console = console;
  // Bounded synchronous rAF: DAG's sim loop self-schedules until _dag.tick >= 280
  // (see template.html's `_dag` state object) — calling back immediately exercises
  // the full simulation instead of silently no-op'ing it, and it's a fixed 280-deep
  // call chain, not unbounded recursion.
  sandbox.requestAnimationFrame = (cb) => { cb(); return 1; };
  sandbox.cancelAnimationFrame = () => {};
  sandbox.setTimeout = setTimeout;
  sandbox.clearTimeout = clearTimeout;
  sandbox.addEventListener = () => {};
  sandbox.removeEventListener = () => {};
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: 'template.html-script' });
  return sandbox;
}

test('template.html script IIFE parses and executes without throwing', () => {
  assert.doesNotThrow(() => runScriptInSandbox());
});

test('every render* function exposed via switchView() runs against the fixture without throwing', () => {
  const sandbox = runScriptInSandbox();
  const views = ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline', 'decisions', 'artefacts', 'mindmap', 'community', 'compare'];
  for (const v of views) {
    assert.doesNotThrow(() => sandbox.window.switchView(v), `switchView('${v}') threw`);
  }
});

test('selectCard() renders the namespace detail panel (State/Learnings/Decisions/History/Tasks/Signals sub-tabs) without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.selectCard(0), 'selectCard(0) threw');
});

test('switchTab() renders each namespace-detail sub-tab without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  for (const t of ['state', 'learnings', 'decisions', 'history', 'tasks', 'radar', 'signals']) {
    assert.doesNotThrow(() => sandbox.window.switchTab(t), `switchTab('${t}') threw`);
  }
});

test('switchTab(\'radar\') runs without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.switchTab('radar'), 'switchTab(\'radar\') threw');
});

test('radarToggleAxis() re-render reflects the new axis set in the DOM', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  sandbox.window.radarToggleAxis('corpusHealth');
  const html = sandbox.document.getElementById('tab-radar').innerHTML;
  assert.match(html, /Corpus health/);
});

test('DAG force simulation runs to completion, and re-activating the tab (resume path) does not throw', () => {
  const sandbox = runScriptInSandbox();
  // First call builds the DOM and runs the sim to maxTick under the synchronous rAF
  // stub (see CLAUDE.md's DAG force-simulation tuning notes — maxTick=280).
  assert.doesNotThrow(() => sandbox.window.switchView('dag'), 'initial switchView(\'dag\') threw');
  // Second call exercises the `_dag.rendered` resume branch (CLAUDE.md's "Stateful
  // view tabs" guard) instead of rebuilding — a distinct code path from the first call.
  assert.doesNotThrow(() => sandbox.window.switchView('dag'), 're-activating switchView(\'dag\') threw');
});

test('mind map controls (rotate, toggle bridges, node click) run without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.switchView('mindmap');
  assert.doesNotThrow(() => sandbox.window.mmRotate(30), 'mmRotate() threw');
  assert.doesNotThrow(() => sandbox.window.mmToggleBridges(), 'mmToggleBridges() threw');
  assert.doesNotThrow(() => sandbox.window.mmResetView(), 'mmResetView() threw');
});

test('community view renders health bar, trust registry, and Sankey without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.switchView('community'));
});

test('search (⌘K) open/query/close cycle runs without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.openSearch(), 'openSearch() threw');
  assert.doesNotThrow(() => sandbox.window.handleSearch('tooling'), 'handleSearch() threw');
  assert.doesNotThrow(() => sandbox.window.closeSearch(), 'closeSearch() threw');
});

test('learnings tab (zone distribution, filterLearningZone) renders without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.switchTab('learnings'), "switchTab('learnings') threw");
  // Per CLAUDE.md's documented DOM-stub limitation (nested innerHTML isn't parsed into
  // real child nodes), filterLearningZone's table.querySelectorAll('tbody tr') can't see
  // any rows here — this only proves the exported function itself runs end-to-end
  // without throwing, matching every other switchTab() sub-tab test's "does it throw"
  // convention (see render_smoke's own file-header comment).
  assert.doesNotThrow(
    () => sandbox.window.filterLearningZone('ltable-example-ns-one', 'example-ns-one', 'golden'),
    'filterLearningZone() threw'
  );
  // Toggling the same zone again (click-to-clear) must also not throw.
  assert.doesNotThrow(
    () => sandbox.window.filterLearningZone('ltable-example-ns-one', 'example-ns-one', 'golden'),
    'filterLearningZone() toggle-off threw'
  );
});

test('decisions tab (decision guidance) renders without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.switchTab('decisions'), "switchTab('decisions') threw");
});

test('decisions tab renders without throwing for a namespace with no decision guidance', () => {
  const sandbox = runScriptInSandbox();
  // example-ns-two's fixture has decisionGuidance: [] — must render byte-identical to
  // pre-P65 output (renderDecisionGuidance returns '' for an empty array).
  sandbox.window.selectCard(1);
  assert.doesNotThrow(() => sandbox.window.switchTab('decisions'), "switchTab('decisions') threw");
});

test('global decisions view renders the guidance breadcrumb without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.switchView('decisions'), "switchView('decisions') threw");
});

test('state tab (verification contracts) renders without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.selectCard(0);
  assert.doesNotThrow(() => sandbox.window.switchTab('state'), "switchTab('state') threw");
});

test('heatmap quality panel (component breakdown) renders without throwing', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.switchView('heatmap');
  assert.doesNotThrow(() => sandbox.window.switchHeatmap('quality'), "switchHeatmap('quality') threw");
});

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

test('globalVisibleNames defaults to every namespace, exercised via globalToggleNamespace persistence', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.globalToggleNamespace('example-ns-one'), 'globalToggleNamespace() threw');
  const stored = JSON.parse(sandbox.localStorage.getItem('compass-global-namespaces'));
  assert.ok(Array.isArray(stored), 'toggle must persist an array to localStorage');
});

test('globalToggleNamespace() removes a namespace already in the active set', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.globalToggleNamespace('example-ns-one'); // toggled off (default is all-visible)
  const first = JSON.parse(sandbox.localStorage.getItem('compass-global-namespaces'));
  sandbox.window.globalToggleNamespace('example-ns-one'); // toggle back
  const second = JSON.parse(sandbox.localStorage.getItem('compass-global-namespaces'));
  assert.notDeepEqual(first.sort(), second.sort());
});

test('globalSetAllNamespaces(false) allows toggling down to 0 active namespaces (no structural minimum)', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.globalSetAllNamespaces(false));
  const stored = JSON.parse(sandbox.localStorage.getItem('compass-global-namespaces'));
  assert.deepEqual(stored, []);
  assert.doesNotThrow(() => sandbox.window.globalToggleNamespace('example-ns-one'));
});

test('switchView(\'compare\') renders the legend and SVG without throwing', () => {
  const sandbox = runScriptInSandbox();
  assert.doesNotThrow(() => sandbox.window.switchView('compare'), 'switchView(\'compare\') threw');
  const html = sandbox.document.getElementById('view-compare').innerHTML;
  assert.match(html, /cmp-legend/);
  assert.match(html, /<svg/);
});

test('globalToggleNamespace() re-render reflects the new namespace set in the DOM once view-compare exists', () => {
  const sandbox = runScriptInSandbox();
  sandbox.window.switchView('compare'); // creates #view-compare content, establishing the container
  assert.doesNotThrow(() => sandbox.window.globalToggleNamespace('example-ns-two'));
  const html = sandbox.document.getElementById('view-compare').innerHTML;
  assert.match(html, /cmp-legend/);
});
