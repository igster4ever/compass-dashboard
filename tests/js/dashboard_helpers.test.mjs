// Node-based smoke test for pure JS helpers embedded in scripts/template.html.
//
// template.html is a static HTML file, not a JS module — its <script> block is
// wrapped in an IIFE (see CLAUDE.md "Module map") so functions aren't reachable
// via import. Instead we extract individual named function sources directly
// from the file text (brace-matched) and eval just those, in isolation, with
// no DOM. This only works for pure functions with no `document`/`window`
// dependency — exactly the set the code review flagged for coverage.
//
// Run: node --test tests/js/dashboard_helpers.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const templatePath = path.join(__dirname, '..', '..', 'scripts', 'template.html');
const html = fs.readFileSync(templatePath, 'utf8');

function extractFunction(name) {
  const marker = `function ${name}(`;
  const start = html.indexOf(marker);
  if (start === -1) throw new Error(`function ${name}() not found in template.html — has it been renamed?`);

  // Skip past the parameter list first — a default param like `opts = {}`
  // contains its own brace pair, which would otherwise fool a naive scan
  // for the function body's opening brace into stopping immediately.
  const parenStart = html.indexOf('(', start);
  let pdepth = 0, j = parenStart;
  for (; j < html.length; j++) {
    if (html[j] === '(') pdepth++;
    else if (html[j] === ')') { pdepth--; if (pdepth === 0) break; }
  }
  const braceStart = html.indexOf('{', j);

  let depth = 0, i = braceStart;
  for (; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) break; }
  }
  if (depth !== 0) throw new Error(`unbalanced braces extracting ${name}()`);
  return html.slice(start, i + 1);
}

function extractConst(name) {
  const marker = `const ${name} = `;
  const start = html.indexOf(marker);
  if (start === -1) throw new Error(`const ${name} not found in template.html — has it been renamed?`);
  let depth = 0, i = start + marker.length;
  for (; i < html.length; i++) {
    const c = html[i];
    if (c === '[' || c === '{' || c === '(') depth++;
    else if (c === ']' || c === '}' || c === ')') depth--;
    else if (c === ';' && depth === 0) break;
  }
  return html.slice(start, i + 1);
}

const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue', 'radarActiveAxes', 'renderRadar', 'nsColor', 'compareAxisValue', '_compareCentralityByNsIndex', 'compareActiveNamespaces', 'renderCompare', 'deriveTasks'];
const CONSTS = ['RADAR_AXIS_DEFS', 'RADAR_DEFAULT_AXES', 'NS_PALETTE', 'COMPARE_AXIS_DEFS'];
// A minimal in-memory localStorage — radarActiveAxes() reads it; no test here
// relies on cross-call persistence, so a single shared instance is fine.
const localStorageShim = `
  let localStorage = (() => {
    const store = new Map();
    return {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: k => store.delete(k),
    };
  })();
`;
// Minimal NS fixture — nsColor()/compareAxisValue()/_compareCentralityByNsIndex() all
// read the global NS array, which isn't defined by any extracted function itself.
const nsFixtureShim = `
  let NS = [
    { namespace: 'ns-a', learnings: [{}], decisions: [{}, {}], externalSignals: [], realityCompletenessScore: 60, goalByMonth: { '2026-06': 70, '2026-07': 80 }, plannedActions: [], reality: '', topTags: [], open: false },
    { namespace: 'ns-b', learnings: [], decisions: [], externalSignals: [{}, {}], realityCompletenessScore: null, goalByMonth: {}, plannedActions: ['depends on ns-a'], reality: '', topTags: [], open: false },
  ];
  let BLOCKING_EDGES = [];
  let SYSTEM_NS = new Set(['global', 'compass']);
`;
const source = localStorageShim + nsFixtureShim + CONSTS.map(extractConst).join('\n\n') + '\n\n' + ['_addEdge', 'computeAllEdges', ...PURE_HELPERS].map(extractFunction).join('\n\n');
// `source` is read only from this repo's own scripts/template.html (never from
// user input, network, or CLI args) — there is no untrusted-string injection
// surface here, just an in-repo test harness for embedded functions.
const helpers = new Function(`${source}\nreturn { ${PURE_HELPERS.join(', ')}, localStorage };`)();

test('esc() escapes HTML-significant characters', () => {
  assert.equal(helpers.esc('<script>&"'), '&lt;script&gt;&amp;&quot;');
  assert.equal(helpers.esc('plain text'), 'plain text');
  assert.equal(helpers.esc(42), '42');
});

test('fmtYM() formats a YYYY-MM period as e.g. Jul’26', () => {
  assert.equal(helpers.fmtYM('2026-07'), 'Jul’26');
  assert.equal(helpers.fmtYM('2025-12'), 'Dec’25');
});

test('_daysSince() parses time-ago strings, not ISO dates', () => {
  assert.equal(helpers._daysSince('never'), 999);
  assert.equal(helpers._daysSince(''), 999);
  assert.equal(helpers._daysSince('5d ago'), 5);
  assert.equal(helpers._daysSince('12h ago'), 0.5);
  assert.equal(helpers._daysSince('3m ago'), 0);
  assert.equal(helpers._daysSince('garbage'), 0);
});

test('urgencyScore() sums weighted signals for an at-risk namespace', () => {
  const ns = {
    open: true, lastOpen: '20d ago',
    goalRate: 40, dreamDue: true,
    deferred: [{}, {}, {}], plannedActions: ['a'],
    realityCompletenessScore: 20,
  };
  // 30 (open) + 25 (days>14) + 20 (goalRate<50) + 12 (dreamDue) + 12 (3 deferred, capped 20) + 8 (planned) + 8 (low completeness)
  assert.equal(helpers.urgencyScore(ns), 115);
});

test('urgencyScore() is near-zero for a healthy, recently-closed namespace', () => {
  const ns = {
    open: false, lastClose: '3d ago',
    goalRate: 80, dreamDue: false,
    deferred: [], plannedActions: [],
    realityCompletenessScore: 60,
  };
  assert.equal(helpers.urgencyScore(ns), 0);
});

test('urgencyScore() caps the deferred-count contribution at 20', () => {
  const ns = { open: false, lastClose: 'never', deferred: Array(10).fill({}) };
  // days=999>14 => +25; deferred 10*4=40 capped to 20
  assert.equal(helpers.urgencyScore(ns), 25 + 20);
});

test('scoreItem() ranks exact match > prefix > word boundary > substring > no match', () => {
  const q = 'kafka';
  assert.equal(helpers.scoreItem({ text: 'kafka' }, q), 100);
  assert.equal(helpers.scoreItem({ text: 'kafka retries' }, q), 80);
  assert.equal(helpers.scoreItem({ text: 'debugging kafka issues' }, q), 60);
  assert.equal(helpers.scoreItem({ text: 'ourkafkacluster' }, q), 40);
  assert.equal(helpers.scoreItem({ text: 'redis' }, q), 0);
});

test('scoreItem() adds the bonus field on top of the base score', () => {
  assert.equal(helpers.scoreItem({ text: 'kafka', bonus: 5 }, 'kafka'), 105);
});

test('scaleLinear() maps value/domainMax proportionally into [0, rangeMax]', () => {
  assert.equal(helpers.scaleLinear(50, 100, 80), 40);
  assert.equal(helpers.scaleLinear(0, 100, 80), 0);
  assert.equal(helpers.scaleLinear(100, 100, 80), 80);
});

test('scaleLinear() invert=true flips the output for y-axes (0 -> bottom, max -> top)', () => {
  assert.equal(helpers.scaleLinear(0, 100, 80, true), 80);
  assert.equal(helpers.scaleLinear(100, 100, 80, true), 0);
  assert.equal(helpers.scaleLinear(50, 100, 80, true), 40);
});

test('scaleLinear() guards against a zero domainMax instead of dividing by zero', () => {
  assert.equal(helpers.scaleLinear(5, 0, 80), 0);
});

test('renderYAxisGridlines() emits one line+label pair per tick, honoring dash', () => {
  const svg = helpers.renderYAxisGridlines(10, 90, 5, 60, 100, [
    { value: 0 }, { value: 50, dash: true }, { value: 100 },
  ]);
  assert.equal((svg.match(/<line/g) || []).length, 3);
  assert.equal((svg.match(/<text/g) || []).length, 3);
  assert.match(svg, /stroke-dasharray="3,3"/);
  // value 0 sits at the bottom of the chart area (chartTop + chartH)
  assert.match(svg, /y1="65\.0"/);
  // value 100 sits at the top of the chart area (chartTop)
  assert.match(svg, /y1="5\.0"/);
});

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

test('renderRadar() warning is a per-call parameter, not persistent module state — a namespace switch must never inherit a stale warning from a prior blocked toggle elsewhere', () => {
  const ns = { open: false, lastClose: '5d ago', goalRate: 80, realityCompletenessScore: 60, sessionCount: 3, learnings: [], deferred: [] };
  const withWarning = helpers.renderRadar(ns, 'At least 3 axes needed — pick another before removing this one.');
  assert.match(withWarning, /At least 3 axes needed/);
  const freshRenderNoWarningArg = helpers.renderRadar(ns);
  assert.doesNotMatch(freshRenderNoWarningArg, /At least 3 axes needed/);
});

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

test('deriveTasks() surfaces "## Backlog" > "### Tactical"/"### Strategic" bullets as tactical/strategic tasks', () => {
  const ns = {
    history: [],
    reality: [
      '## Backlog',
      '### Tactical',
      '- wire up the missing retry metric',
      '### Strategic',
      '- explore a federated learnings index',
    ].join('\n'),
    plannedActions: [],
    deferred: [],
  };
  const tasks = helpers.deriveTasks(ns);
  const tactical = tasks.find(t => t.text === 'wire up the missing retry metric');
  const strategic = tasks.find(t => t.text === 'explore a federated learnings index');
  assert.equal(tactical.src, 'backlog-tactical');
  assert.equal(strategic.src, 'backlog-strategic');
  assert.ok(tactical.score > strategic.score, 'tactical items should outrank strategic items by default');
});

test('deriveTasks() stops attributing bullets to a backlog bucket once a new heading is reached', () => {
  const ns = {
    history: [],
    reality: [
      '## Backlog',
      '### Tactical',
      '- fix the flaky heatmap test',
      '## Something else',
      '- unrelated bullet should not be a task',
    ].join('\n'),
    plannedActions: [],
    deferred: [],
  };
  const tasks = helpers.deriveTasks(ns);
  assert.ok(tasks.some(t => t.text === 'fix the flaky heatmap test'));
  assert.ok(!tasks.some(t => t.text === 'unrelated bullet should not be a task'));
});
