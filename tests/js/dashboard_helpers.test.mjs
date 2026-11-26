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

const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines', 'healthColor', 'radarAxisValue', 'radarActiveAxes', 'renderRadar', 'nsColor', 'compareAxisValue', '_compareCentralityByNsIndex', 'globalVisibleNames', 'visibleNS', 'renderCompare', 'deriveTasks', 'renderDecisions', 'detailTabs', 'decisionsTabLabel', 'renderStateSection_GoalStatuses', 'goalStatusHeadline', '_complexityProbeErrors', 'renderStateSection_DataProblems', 'renderStateSection_BacklogMatch', 'backlogMatchHeadline', '_cadenceLastRun', '_cooldownOverrides', 'windowLabel', 'renderStateSection_CycleSparkline', 'codeReviewHeadline', 'renderStateSection_CodeReviews', 'learningSurfaced', 'learningApplied', 'compareLearningRows', 'rankReasons', 'scoreNamespace'];
const CONSTS = ['RADAR_AXIS_DEFS', 'RADAR_DEFAULT_AXES', 'NS_PALETTE', 'COMPARE_AXIS_DEFS', 'GLOBAL_NS_KEY', 'CADENCE_LAST_RUN_LABELS', 'CODE_REVIEW_SEVERITIES', 'STALE_BULLETS_PER_POINT', 'STALE_BULLETS_CAP', 'MAINTENANCE_DUE_WEIGHTS', 'STRUCTURE_WARNING_POINTS', 'STRUCTURE_WARNING_CAP', 'CARRY_FORWARD_POINTS', 'CARRY_FORWARD_CAP', 'RETRIEVAL_STALE_PER_POINT', 'RETRIEVAL_STALE_CAP'];
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
const helpers = new Function(`${source}\nreturn { ${PURE_HELPERS.join(', ')}, STALE_BULLETS_PER_POINT, STALE_BULLETS_CAP, MAINTENANCE_DUE_WEIGHTS, STRUCTURE_WARNING_CAP, CARRY_FORWARD_CAP, RETRIEVAL_STALE_PER_POINT, RETRIEVAL_STALE_CAP, localStorage };`)();

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

test('detailTabs() shows the Decisions sub-tab only when there are decisions', () => {
  assert.ok(helpers.detailTabs({ decisions: [{ decision: 'd' }] }).includes('decisions'));
  assert.ok(!helpers.detailTabs({ decisions: [] }).includes('decisions'));
  assert.ok(!helpers.detailTabs({}).includes('decisions'));
  assert.deepEqual(helpers.detailTabs({ externalSignals: ['s'] }),
    ['state', 'learnings', 'history', 'tasks', 'radar', 'signals']);
});

test('decisionsTabLabel() counts decisions', () => {
  // Tab labels use non-breaking spaces so a label never wraps inside its button.
  assert.equal(helpers.decisionsTabLabel({ decisions: [{}, {}] }), 'Decisions\u00a0(2)');
  assert.equal(helpers.decisionsTabLabel({}), 'Decisions\u00a0(0)');
});

test('renderDecisions() lists decisions, or the empty state when there are none', () => {
  const plain = helpers.renderDecisions({ decisions: [{ decision: 'd1' }] });
  assert.ok(plain.includes('d1'));
  assert.ok(!plain.includes('No decisions logged'));
  assert.ok(helpers.renderDecisions({ decisions: [] }).includes('No decisions logged for this namespace yet.'));
});

// ── Goal status breakdown (data-model audit Rank 6a) ──

const gsb = {
  counts: { completed: 8, partial: 0, skipped: 1, blocked: 0, abandoned: 1, other: 0 },
  total: 10, sessions: 3,
  not_completed: [
    { date: '2026-10-02', status: 'abandoned', goal: 'Ship <b>it</b>', reason: 'Ship <b>it</b> — waiting on <API>', why: 'waiting on <API>' },
    { date: '2026-10-01', status: 'skipped', goal: null, reason: null, why: null },
    { date: '2026-09-30', status: 'blocked', goal: 'Other goal', reason: 'Reworded entirely', why: 'Reworded entirely' },
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
  // The why is computed in Python (_incomplete_why, tested in test_data_loading.py); JS only
  // escapes and renders it, and renders nothing when it is null.
  assert.match(html, /<div class="gs-why">waiting on &lt;API&gt;<\/div>/);
  assert.match(html, /<div class="gs-why">Reworded entirely<\/div>/);
  assert.equal((html.match(/gs-why/g) || []).length, 2, 'no why block for the goal with no reason');
  // JS no longer derives the why from `reason`: a missing `why` shows nothing even with a reason.
  const noWhy = helpers.renderStateSection_GoalStatuses({ goalStatusBreakdown: { ...gsb, not_completed: [
    { date: '2026-09-29', status: 'abandoned', goal: 'Bulk-delete UI', reason: 'Bulk-delete UI — deferred' },
  ] } });
  assert.doesNotMatch(noWhy, /gs-why/);
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
  // no-hash candidates are not "gone": subtract them and say so
  assert.equal(helpers.backlogMatchHeadline({ backlogMatchSummary: { ...bms, offered: 3, unknown: 1 } }),
    '3 backlog matches offered, 1 gone since, 1 unverifiable');
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

// ── Capped series are labelled (data-model audit Rank 4) ──

test('windowLabel(): names the window only when the series is shorter than the session count', () => {
  assert.equal(helpers.windowLabel(10, 83), 'last 10 of 83 sessions');
  assert.equal(helpers.windowLabel(6, 6), '');
  assert.equal(helpers.windowLabel(5, 3), '', 'never claims a window larger than the whole');
  assert.equal(helpers.windowLabel(1, undefined), '', 'unknown total says nothing');
});

test('renderStateSection_CycleSparkline(): says "last N of M sessions" when core kept only a window', () => {
  const cycle = Array.from({ length: 10 }, (_, i) => ({ opened_at: `2026-10-${10 + i}T08:00:00Z`, minutes: 20 + i }));
  const capped = helpers.renderStateSection_CycleSparkline({ cycleHistory: cycle, lastCycleMinutes: 29, sessionCount: 83 });
  assert.match(capped, /last 10 of 83 sessions/);
  assert.doesNotMatch(capped, /sessions tracked/);
  const whole = helpers.renderStateSection_CycleSparkline({ cycleHistory: cycle.slice(0, 3), lastCycleMinutes: 22, sessionCount: 3 });
  assert.match(whole, /3 sessions tracked/);
  assert.doesNotMatch(whole, /last 3 of/);
});

// ── Code reviews (data-model audit Rank 7) ──

const codeReviews = {
  count: 3,
  reviews: [
    { date: '2026-07-01', critical: 0, high: 1, medium: 2, low: 1, total: 4 },
    { date: '2026-08-01', critical: 1, high: 0, medium: 0, low: 0, total: 1 },
    { date: '2026-09-01', critical: 0, high: 2, medium: 1, low: 0, total: 3 },
  ],
  latest: { date: '2026-09-01', total: 5, findings: [
    { severity: 'high', title: 'Split <b>across</b> layers', category: 'Boundaries & Concerns' },
    { severity: 'medium', title: 'No category here', category: null },
  ] },
};

test('codeReviewHeadline(): review count and the latest severity counts, empty without reviews', () => {
  assert.equal(helpers.codeReviewHeadline({ codeReviews }), '3 reviews, latest 2 HIGH, 1 MEDIUM');
  assert.equal(helpers.codeReviewHeadline({ codeReviews: { count: 1, reviews: [
    { date: 'd', critical: 0, high: 0, medium: 0, low: 0, total: 0 }] } }), '1 review, latest no findings parsed');
  assert.equal(helpers.codeReviewHeadline({}), '');
  assert.equal(helpers.codeReviewHeadline({ codeReviews: null }), '');
});

test('renderStateSection_CodeReviews(): one stacked column per review, latest findings escaped', () => {
  const html = helpers.renderStateSection_CodeReviews({ codeReviews });
  assert.equal((html.match(/class="cr-col"/g) || []).length, 3);
  assert.match(html, /title="2026-07-01: 0 critical, 1 high, 2 medium, 1 low"/);
  assert.match(html, /Split &lt;b&gt;across&lt;\/b&gt; layers/);
  assert.doesNotMatch(html, /<b>across/);
  assert.match(html, /Boundaries &amp; Concerns/);
  assert.match(html, /Latest review — 2026-09-01/);
  assert.match(html, /… and 3 more/, 'the total exceeds the findings carried, so it says so');
  assert.doesNotMatch(html, /last \d+ of/, 'no window label when every review is shown');
});

test('renderStateSection_CodeReviews(): labels a capped window; says so when the latest parsed nothing', () => {
  const capped = helpers.renderStateSection_CodeReviews({ codeReviews: { ...codeReviews, count: 20 } });
  assert.match(capped, /last 3 of 20/);
  const none = helpers.renderStateSection_CodeReviews({ codeReviews: {
    count: 1, reviews: [{ date: '2026-09-01', critical: 0, high: 0, medium: 0, low: 0, total: 0 }],
    latest: { date: '2026-09-01', total: 0, findings: [] } } });
  assert.match(none, /Latest review parsed no findings/);
  assert.equal(helpers.renderStateSection_CodeReviews({}), '');
});

// ── Learnings: surfaced column and sort keys ─────────────────────────────────

test('learningSurfaced(): never-surfaced is spelled out, surfaced shows count and age', () => {
  const now = Date.parse('2026-11-19T12:00:00Z');
  assert.equal(helpers.learningSurfaced({}, now).label, 'never');
  assert.equal(helpers.learningSurfaced({ times_surfaced: 0 }, now).lastMs, 0);
  const s = helpers.learningSurfaced({ times_surfaced: 5, last_surfaced_at: '2026-11-16T09:00:00Z' }, now);
  assert.equal(s.label, '5\u00d7 \u00b7 3d ago');
  assert.equal(s.times, 5);
  assert.equal(helpers.learningSurfaced({ times_surfaced: 1, last_surfaced_at: '2026-11-19T01:00:00Z' }, now).label, '1\u00d7 \u00b7 today');
  assert.equal(helpers.learningSurfaced({ times_surfaced: 2 }, now).label, '2\u00d7', 'count without a timestamp shows no age');
});

test('compareLearningRows(): sorts by weight, surfaced count and date; ties keep row order', () => {
  const row = (idx, w, times, date) => ({ dataset: { idx: String(idx), w: String(w), times: String(times), date } });
  const rows = [row(0, 2, 0, '2026-07-01'), row(1, 5, 3, '2026-06-01'), row(2, 5, 1, '2026-08-01'), row(3, 1, 3, '2026-08-01')];
  const order = (key, dir) => [...rows].sort((a, b) => helpers.compareLearningRows(a, b, key, dir)).map(r => r.dataset.idx).join('');
  assert.equal(order('w', -1), '1203');      // weight high first; the 5/5 tie keeps original order
  assert.equal(order('times', -1), '1320');  // surfaced most first; 3/3 tie keeps original order
  assert.equal(order('times', 1), '0213');   // never-surfaced first when ascending: the retrieval gaps
  assert.equal(order('date', -1), '2301');   // newest first as ISO text; the 08-01 tie keeps row order
});

test('learningApplied(): a plain session count, a dash when none', () => {
  assert.equal(helpers.learningApplied({}).label, '\u2014');
  assert.equal(helpers.learningApplied({ appliedSessions: 1 }).label, '1 session');
  assert.equal(helpers.learningApplied({ appliedSessions: 3 }).label, '3 sessions');
});

test('compareLearningRows(): sorts by applied count', () => {
  const row = (idx, applied) => ({ dataset: { idx: String(idx), applied: String(applied) } });
  const rows = [row(0, 0), row(1, 2), row(2, 1)];
  assert.equal([...rows].sort((a, b) => helpers.compareLearningRows(a, b, 'applied', -1)).map(r => r.dataset.idx).join(''), '120');
});

test('rankReasons(): biggest contributor first, ties keep insertion order, input untouched', () => {
  const input = [{ points: 4, text: 'a' }, { points: 20, text: 'b' }, { points: 4, text: 'c' }, { points: 30, text: 'd' }];
  assert.deepEqual(helpers.rankReasons(input).map(r => r.text), ['d', 'b', 'a', 'c']);
  assert.deepEqual(input.map(r => r.text), ['a', 'b', 'c', 'd']);
});

test('scoreNamespace(): the 5-reason cut keeps the largest, not the first-added', () => {
  const ns = {
    open: true, lastOpen: '1d ago', goalRate: 40, deferred: [1, 2], plannedActions: ['x'],
    learnings: [{ weight: 5 }], sessionCount: 4, staleBulletCount: 30,
    codeReviewDue: true, researchDue: true,
  };
  const { score, reasons } = helpers.scoreNamespace(ns);
  assert.equal(score, reasons.reduce((t, r) => t + r.points, 0));
  assert.ok(reasons.length > 5, 'fixture must exceed the card cut');
  const shown = reasons.slice(0, 5).map(r => r.points);
  const dropped = reasons.slice(5).map(r => r.points);
  assert.ok(Math.min(...shown) >= Math.max(...dropped));
  assert.equal(reasons[0].text, 'Session currently in progress');
});

test('scoreNamespace(): stale reality bullets score 1 per 5, capped', () => {
  const pts = n => (helpers.scoreNamespace({ staleBulletCount: n, sessionCount: 3, lastClose: '1d ago' })
    .reasons.find(r => /stale reality/.test(r.text)) || { points: 0 }).points;
  assert.equal(helpers.STALE_BULLETS_PER_POINT, 5);
  assert.equal(helpers.STALE_BULLETS_CAP, 15);
  assert.equal(pts(0), 0);
  assert.equal(pts(4), 0);
  assert.equal(pts(5), 1);
  assert.equal(pts(29), 5);
  assert.equal(pts(87), 15);
  assert.equal(pts(500), 15);
});

test('scoreNamespace(): maintenance-due flags score their pinned weights, and only when due', () => {
  const total = flags => helpers.scoreNamespace({ sessionCount: 3, lastClose: '1d ago', ...flags }).score;
  assert.equal(total({}), 0);
  assert.equal(total({ codeReviewDue: true }), 6);
  assert.equal(total({ researchDue: true }), 4);
  assert.equal(total({ skillOptDue: true }), 3);
  assert.equal(total({ dreamDue: true }), 2);
  assert.equal(total({ claudeReviewDue: true }), 2);
  assert.equal(total({ codeReviewDue: true, researchDue: true, skillOptDue: true, dreamDue: true, claudeReviewDue: true }), 17);
  assert.equal(helpers.MAINTENANCE_DUE_WEIGHTS.reduce((t, w) => t + w[1], 0), 17);
});

test('scoreNamespace(): latest review severity scores only while no newer review is due', () => {
  const cr = { reviews: [{ date: '2026-10-30', critical: 1, high: 2, medium: 0, low: 0 }] };
  const base = { sessionCount: 3, lastClose: '1d ago', codeReviews: cr };
  const sev = ns => helpers.scoreNamespace(ns).reasons.find(r => /Latest code review/.test(r.text));
  assert.equal(sev({ ...base, codeReviewDue: false }).points, 10);
  assert.equal(sev({ ...base, codeReviewDue: true }), undefined);
  assert.equal(helpers.scoreNamespace({ ...base, codeReviewDue: true }).score, 6);
});

test('scoreNamespace(): structure warnings and carry-forward score 2 each, capped', () => {
  const base = { sessionCount: 3, lastClose: '1d ago' };
  const find = (ns, re) => (helpers.scoreNamespace({ ...base, ...ns }).reasons.find(r => re.test(r.text)) || { points: 0 }).points;
  const warn = n => find({ realityStructureWarnings: Array(n).fill('w') }, /structure warning/);
  assert.deepEqual([0, 1, 2, 5].map(warn), [0, 2, 4, 4]);
  assert.equal(helpers.STRUCTURE_WARNING_CAP, 4);
  const cfTrend = n => ({ carryForwardTrend: [{ date: 'd0', carryForward: 9 }, { date: 'd1', carryForward: n }] });
  const cf = n => find(cfTrend(n), /carried forward/);
  assert.deepEqual([0, 1, 3, 9].map(cf), [0, 2, 6, 8]);
  assert.equal(helpers.CARRY_FORWARD_CAP, 8);
  assert.equal(find({ carryForwardTrend: [] }, /carried forward/), 0);
  assert.equal(find({}, /carried forward/), 0);
});

test('scoreNamespace(): retrieval-stale learnings score 1 per 5, capped at 6', () => {
  const base = { sessionCount: 3, lastClose: '1d ago' };
  const pts = n => (helpers.scoreNamespace({ ...base, retrievalStaleCount: n }).reasons.find(r => /surfaced often/.test(r.text)) || { points: 0 }).points;
  assert.deepEqual([0, 4, 5, 6, 31, 500].map(pts), [0, 0, 1, 1, 6, 6]);
  assert.equal(helpers.RETRIEVAL_STALE_PER_POINT, 5);
  assert.equal(helpers.RETRIEVAL_STALE_CAP, 6);
  assert.equal(pts(undefined), 0);
});
