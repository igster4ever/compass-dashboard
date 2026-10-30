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

const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue', 'radarActiveAxes', 'renderRadar', 'nsColor', 'compareAxisValue', '_compareCentralityByNsIndex', 'globalVisibleNames', 'visibleNS', 'renderCompare', 'deriveTasks', 'renderDecisionGuidance', 'renderDecisions', 'detailTabs', 'decisionsTabLabel', 'ladderLevel', 'renderStateSection_GoalStatuses', 'goalStatusHeadline', '_complexityProbeErrors', 'renderStateSection_DataProblems', 'renderStateSection_BacklogMatch', 'backlogMatchHeadline', '_cadenceLastRun', '_cooldownOverrides'];
const CONSTS = ['RADAR_AXIS_DEFS', 'RADAR_DEFAULT_AXES', 'NS_PALETTE', 'COMPARE_AXIS_DEFS', 'GLOBAL_NS_KEY', 'ZONE_SHIP_DATE', 'LADDER', 'CADENCE_LAST_RUN_LABELS'];
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
  helpers.localStorage.setItem('compass-global-namespaces', JSON.stringify([]));
  const html = helpers.renderCompare();
  assert.match(html, /no namespaces selected/i);
});

test('renderCompare() draws one polygon per active namespace, coloured by nsColor()', () => {
  helpers.localStorage.setItem('compass-global-namespaces', JSON.stringify(['ns-a', 'ns-b']));
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

test('renderDecisionGuidance() renders a card per pair, signed deltas, no pill without evidence, escaped text', () => {
  // Synthetic shapes from the 2026-10-23 P65 browser check (docs/backlog/p65-decision-guidance-ui-findings.md).
  const html = helpers.renderDecisionGuidance({ decisionGuidance: [
    { preferredDecisionText: 'Mirror core', avoidedDecisionText: 'Re-derive', qualityDelta: 0.17,
      contextSummary: 'Surfacing a metric', createdAt: '2026-10-20T10:00:00Z' },
    { preferredDecisionText: 'One commit', avoidedDecisionText: 'Four commits', qualityDelta: -0.12 },
    { preferredDecisionText: 'Probe first', avoidedDecisionText: 'Trust docs', qualityDelta: null },
    { preferredDecisionText: '<b>bold?</b>', avoidedDecisionText: '</script><script>x()</script>' },
  ]});
  assert.equal((html.match(/class="guidance-item"/g) || []).length, 4);
  // P65 findings 3-6 (2026-10-27): heading with pair count, pp unit, amber pill for a negative delta, context first.
  assert.ok(html.includes('Guidance (4)'));
  assert.ok(html.includes('Δ+17pp</span>'));
  assert.ok(html.includes('Δ-12pp</span>'));
  assert.ok(!html.includes('%</span>'));
  assert.equal((html.match(/class="guidance-delta( neg)?"/g) || []).length, 2, 'null/absent qualityDelta renders no pill');
  assert.equal((html.match(/class="guidance-delta neg"/g) || []).length, 1, 'only the negative delta is amber');
  assert.ok(html.includes('avoided option scored higher'));
  const first = html.slice(html.indexOf('guidance-item'));
  assert.ok(first.indexOf('Surfacing a metric') < first.indexOf('Mirror core'), 'context line renders before the pair');
  assert.ok(html.includes('&lt;b&gt;bold?&lt;/b&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('2026-10-20</span>'));
  assert.equal(helpers.renderDecisionGuidance({ decisionGuidance: [] }), '');
});

test('detailTabs() shows the Decisions sub-tab for decisions or guidance, not for neither', () => {
  // P65 finding 2 (2026-10-23): a guidance-only namespace had no Decisions tab, so its pairs were unreachable.
  const g = [{ preferredDecisionText: 'p', avoidedDecisionText: 'a' }];
  assert.ok(helpers.detailTabs({ decisions: [{ decision: 'd' }] }).includes('decisions'));
  assert.ok(helpers.detailTabs({ decisions: [], decisionGuidance: g }).includes('decisions'));
  assert.ok(!helpers.detailTabs({ decisions: [], decisionGuidance: [] }).includes('decisions'));
  assert.ok(!helpers.detailTabs({}).includes('decisions'));
  assert.deepEqual(helpers.detailTabs({ externalSignals: ['s'] }),
    ['state', 'learnings', 'history', 'tasks', 'radar', 'signals']);
});

test('decisionsTabLabel() counts guidance pairs alongside decisions', () => {
  // Tab labels use non-breaking spaces so a label never wraps inside its button.
  const g = [{ preferredDecisionText: 'p', avoidedDecisionText: 'a' }];
  assert.equal(helpers.decisionsTabLabel({ decisions: [{}, {}] }), 'Decisions\u00a0(2)');
  assert.equal(helpers.decisionsTabLabel({ decisions: [{}], decisionGuidance: g }), 'Decisions\u00a0(1\u00a0·\u00a01\u00a0guidance)');
  assert.equal(helpers.decisionsTabLabel({ decisionGuidance: [...g, ...g] }), 'Decisions\u00a0(0\u00a0·\u00a02\u00a0guidance)');
});

test('renderDecisions() heads the decision list only when guidance sits above it', () => {
  const g = [{ preferredDecisionText: 'p', avoidedDecisionText: 'a' }];
  const both = helpers.renderDecisions({ decisions: [{ decision: 'd1' }], decisionGuidance: g });
  assert.ok(both.includes('Decisions (1)</div>'));
  assert.ok(both.indexOf('Guidance (1)') < both.indexOf('Decisions (1)</div>'));
  const plain = helpers.renderDecisions({ decisions: [{ decision: 'd1' }] });
  assert.ok(!plain.includes('guidance-heading'));
});

test('renderDecisions() still renders guidance when there are no decisions', () => {
  const g = [{ preferredDecisionText: 'Guidance only pair', avoidedDecisionText: 'a' }];
  const html = helpers.renderDecisions({ decisions: [], decisionGuidance: g });
  assert.ok(html.includes('Guidance only pair'));
  assert.ok(html.includes('No decisions logged for this namespace yet.'));
  assert.ok(html.indexOf('Guidance only pair') < html.indexOf('No decisions logged'));
  const none = helpers.renderDecisions({ decisions: [] });
  assert.ok(!none.includes('guidance-item'));
});

// ── Maturity ladder (docs/backlog/maturity-ladder-scorecard-design-note.md) ──

function matureNs(over = {}) {
  return {
    namespace: 'ns-x',
    intent: '# Intent\nDo the thing',
    reality: '## What exists and works\n- a\n## Backlog\n- b',
    realityStructureWarnings: [],
    sessionCount: 6,
    hasRepoPath: true,
    claudeReviewStatus: { claude_md_files: { 'CLAUDE.md': 1200 } },
    codeContext: '## Last updated: 2026-10-01',
    learnings: [
      { tags: ['a'], date: '2026-08-01T00:00:00Z', zone: 'golden' },
      { tags: ['b'], date: '2026-09-01T00:00:00Z' },
      { tags: ['c'], date: '2026-05-01T00:00:00Z' },
    ],
    goalTypeBySession: [1, 2, 3, 4, 5].map(i => ({ date: `2026-10-0${i}`, typed: true })),
    decisions: [{}],
    contracts: [{}, {}, {}, {}, {}],
    outcomeRate: 0.5,
    staleBulletCount: 0,
    ...over,
  };
}

const failing = r => r.checks.filter(c => c.status === 'fail').map(c => c.id);

test('ladderLevel(): a namespace passing every check is L4 at 100%', () => {
  const r = helpers.ladderLevel(matureNs());
  assert.equal(r.level, 4);
  assert.equal(r.completeness, 100);
  assert.deepEqual(r.next, []);
});

test('ladderLevel(): an empty namespace is L0, and no data fails with a reason, never N/A', () => {
  const r = helpers.ladderLevel({ namespace: 'empty' });
  assert.equal(r.level, 0);
  assert.equal(r.checks.filter(c => c.status === 'na').length, 0);
  const zone = r.checks.find(c => c.id === 'zone');
  assert.equal(zone.status, 'fail');
  assert.match(zone.reason, /no learnings since 2026-07-05/);
  assert.equal(r.checks.find(c => c.id === 'outcome').status, 'fail');
});

test('ladderLevel(): level is the highest tier with every lower tier passing; completeness counts all tiers', () => {
  const r = helpers.ladderLevel(matureNs({ codeContext: '' }));
  assert.equal(r.level, 1);
  assert.deepEqual(failing(r), ['code_context']);
  assert.equal(r.completeness, Math.round((r.applicable - 1) / r.applicable * 100));
  assert.deepEqual(r.next.map(c => c.id), ['code_context']);
});

test('ladderLevel(): next lists only the failing checks one tier up', () => {
  const r = helpers.ladderLevel(matureNs({ decisions: [], contracts: [] }));
  assert.equal(r.level, 2);
  assert.deepEqual(r.next.map(c => c.id), ['decision']);
});

test('ladderLevel(): global has the session-count check N/A, and its repo checks still apply', () => {
  const r = helpers.ladderLevel(matureNs({ namespace: 'global', sessionCount: 1, hasRepoPath: false }));
  assert.equal(r.checks.find(c => c.id === 'sessions').status, 'na');
  assert.equal(r.checks.find(c => c.id === 'repo_path').status, 'fail');
  assert.equal(r.applicable, r.checks.length - 1);
});

test('ladderLevel(): zone counts only learnings dated on or after the ship date', () => {
  // 1 of 2 post-ship learnings is zoned = 50%: passes. The pre-ship one is ignored.
  assert.equal(helpers.ladderLevel(matureNs()).checks.find(c => c.id === 'zone').status, 'pass');
  const r = helpers.ladderLevel(matureNs({ learnings: [
    { tags: ['a'], date: '2026-08-01T00:00:00Z' },
    { tags: ['b'], date: '2026-09-01T00:00:00Z' },
    { tags: ['c'], date: '2026-05-01T00:00:00Z', zone: 'golden' },
  ] }));
  const zone = r.checks.find(c => c.id === 'zone');
  assert.equal(zone.status, 'fail');
  assert.match(zone.reason, /0 of 2/);
});

test('ladderLevel(): untagged learnings fail at L3 and reality structure warnings at L2, with reasons', () => {
  const r = helpers.ladderLevel(matureNs({
    learnings: [{ tags: [], date: '2026-08-01', zone: 'golden' }, { tags: ['x'], date: '2026-08-01', zone: 'golden' }],
    realityStructureWarnings: ['Missing section: ## Backlog'],
  }));
  assert.match(r.checks.find(c => c.id === 'tagged').reason, /1 of 2 untagged/);
  assert.equal(r.checks.find(c => c.id === 'reality').status, 'pass');
  assert.match(r.checks.find(c => c.id === 'reality_sections').reason, /Missing section: ## Backlog/);
  assert.equal(r.level, 1);
});

test('ladderLevel(): goal types need 3 of the last 5 sessions typed', () => {
  const gt = flags => flags.map((typed, i) => ({ date: `2026-10-0${i + 1}`, typed }));
  const status = flags => helpers.ladderLevel(matureNs({ goalTypeBySession: gt(flags) }))
    .checks.find(c => c.id === 'goal_types').status;
  assert.equal(status([true, true, true, false, false, false, false, false]), 'fail');
  assert.equal(status([false, false, true, true, true]), 'pass');
  assert.equal(status([true, true]), 'fail');
  assert.match(helpers.ladderLevel(matureNs({ goalTypeBySession: [] })).checks.find(c => c.id === 'goal_types').reason, /no goal records/);
});

test('ladderLevel(): outcome rate and stale bullets gate L4', () => {
  assert.match(helpers.ladderLevel(matureNs({ outcomeRate: null })).checks.find(c => c.id === 'outcome').reason,
    /no goal-outcome links/);
  assert.equal(helpers.ladderLevel(matureNs({ outcomeRate: 0.29 })).level, 3);
  assert.equal(helpers.ladderLevel(matureNs({ staleBulletCount: 2 })).level, 3);
});

// ── Goal status breakdown (data-model audit Rank 6a) ──

const gsb = {
  counts: { completed: 8, partial: 0, skipped: 1, blocked: 0, abandoned: 1, other: 0 },
  total: 10, sessions: 3,
  not_completed: [
    { date: '2026-10-02', status: 'abandoned', goal: 'Ship <b>it</b>', reason: 'Ship <b>it</b> — waiting on <API>' },
    { date: '2026-10-01', status: 'skipped', goal: null, reason: null },
    { date: '2026-09-30', status: 'blocked', goal: 'Other goal', reason: 'Reworded entirely' },
  ],
};

test('renderStateSection_GoalStatuses(): empty without data', () => {
  assert.equal(helpers.renderStateSection_GoalStatuses({}), '');
  assert.equal(helpers.renderStateSection_GoalStatuses({ goalStatusBreakdown: { ...gsb, total: 0 } }), '');
});

test('renderStateSection_GoalStatuses(): shows each non-zero status and the recent non-completed goals, escaped', () => {
  const html = helpers.renderStateSection_GoalStatuses({ goalStatusBreakdown: gsb });
  assert.match(html, /8 completed/);
  assert.match(html, /1 abandoned/);
  assert.match(html, /1 skipped/);
  assert.doesNotMatch(html, /0 blocked/);
  assert.match(html, /Ship &lt;b&gt;it&lt;\/b&gt;/);
  assert.match(html, /goal text not recorded/);
  // The restated goal is stripped from the reason; a reworded reason is shown whole.
  assert.match(html, /<div class="gs-why">waiting on &lt;API&gt;<\/div>/);
  assert.match(html, /<div class="gs-why">Reworded entirely<\/div>/);
  // A shortened restatement before the dash still counts as the goal.
  const short = helpers.renderStateSection_GoalStatuses({ goalStatusBreakdown: { ...gsb, not_completed: [
    { date: '2026-09-29', status: 'abandoned', goal: 'Bulk-delete UI — panel for deleting articles', reason: 'Bulk-delete UI — deferred by agreement' },
    { date: '2026-09-28', status: 'abandoned', goal: 'Exact goal', reason: 'Exact goal' },
    { date: '2026-09-27', status: 'skipped', goal: 'Session H — Freshness strip', reason: 'Freshness strip' },
  ] } });
  assert.match(short, /<div class="gs-why">deferred by agreement<\/div>/);
  assert.equal((short.match(/gs-why/g) || []).length, 1);
});

test('goalStatusHeadline(): counts goals that did not complete', () => {
  assert.equal(helpers.goalStatusHeadline({ goalStatusBreakdown: gsb }), '2 of 10 goals not completed');
  assert.equal(helpers.goalStatusHeadline({ goalStatusBreakdown: { ...gsb, counts: { completed: 10 }, total: 10 } }), 'all 10 goals completed');
  assert.equal(helpers.goalStatusHeadline({}), '');
});

test('_complexityProbeErrors(): names each failed git probe, escaped; empty otherwise', () => {
  assert.equal(helpers._complexityProbeErrors(undefined), '');
  assert.equal(helpers._complexityProbeErrors({ complexity_signal: { errors: {} } }), '');
  assert.equal(helpers._complexityProbeErrors({}), '');
  const html = helpers._complexityProbeErrors({ complexity_signal: { errors: {
    lines_changed: 'timeout after 10s', new_files: "exit 128: fatal: not a git repository <x>" } } });
  assert.match(html, /complexity probe failed \(lines_changed: timeout after 10s; new_files: exit 128: fatal: not a git repository &lt;x&gt;\)/);
});

test('renderStateSection_DataProblems(): lists each corrupt file, escaped; empty without problems', () => {
  assert.equal(helpers.renderStateSection_DataProblems({}), '');
  assert.equal(helpers.renderStateSection_DataProblems({ dataProblems: [] }), '');
  const html = helpers.renderStateSection_DataProblems({ dataProblems: [
    { file: 'learnings.jsonl', issue: '2 malformed lines dropped (first: line 4)' },
    { file: 'state.json', issue: 'invalid JSON at line 1 <x>' }] });
  assert.match(html, /<code>learnings\.jsonl<\/code> — 2 malformed lines dropped \(first: line 4\)/);
  assert.match(html, /invalid JSON at line 1 &lt;x&gt;/);
});

const bms = { closes: 3, with_candidates: 1, offered: 2, still_open: 1, excluded: 1,
  by_basis: { ratio: 1, identifier: 1, rare: 0, other: 0 },
  recent: [{ date: '2026-10-22', context: 'shipped <A>', candidates: [
    { text: 'Build <A>', section: 'tactical', match_basis: 'identifier', overlap: 5, still_open: true },
    { text: 'Vague', section: 'strategic', match_basis: 'ratio', overlap: 2, still_open: false }] }] };

test('renderStateSection_BacklogMatch(): summary, per-candidate state, escaped; empty without data', () => {
  assert.equal(helpers.renderStateSection_BacklogMatch({}), '');
  const html = helpers.renderStateSection_BacklogMatch({ backlogMatchSummary: bms });
  assert.match(html, /3 closes ran a match; 1 offered candidates \(2: 1 ratio, 1 identifier; 1 still in reality\); 1 excluded/);
  assert.match(html, /2026-10-22 — shipped &lt;A&gt;/);
  assert.match(html, /Build &lt;A&gt; <span[^>]*>\[tactical, identifier, overlap 5 · still in reality\]/);
  assert.match(html, /\[strategic, ratio, overlap 2 · gone since\]/);
});

test('backlogMatchHeadline(): offered and gone counts; empty when nothing offered', () => {
  assert.equal(helpers.backlogMatchHeadline({ backlogMatchSummary: bms }), '2 backlog matches offered, 1 gone since');
  assert.equal(helpers.backlogMatchHeadline({ backlogMatchSummary: { ...bms, offered: 0 } }), '');
  assert.equal(helpers.backlogMatchHeadline({}), '');
});

test('_cadenceLastRun(): lists each cadence with its age in a fixed order; empty without data', () => {
  assert.equal(helpers._cadenceLastRun({}), '');
  const html = helpers._cadenceLastRun({ cadenceLastRun: {
    skill_opt: { at: 'x', ago: '81d ago' }, dream: { at: 'y', ago: '0d ago' }, research: { at: null, ago: 'never' } } });
  assert.match(html, /Last run: dream 0d ago · research never · SkillOpt 81d ago</);
});

test('_cooldownOverrides(): count, rate and escaped reasons; empty without violations', () => {
  assert.equal(helpers._cooldownOverrides({}), '');
  const html = helpers._cooldownOverrides({ cooldownViolationSummary: { count: 4, rate: 0.1,
    recent: [{ timestamp: '2026-09-14T08:38:26Z', reason: 'retro <now>' }] } });
  assert.match(html, /4 cooldown overrides \(10% of sessions\)/);
  assert.match(html, /2026-09-14<\/span> retro &lt;now&gt;/);
  assert.match(helpers._cooldownOverrides({ cooldownViolationSummary: { count: 1, rate: null, recent: [] } }), /1 cooldown override<\/summary>/);
});
