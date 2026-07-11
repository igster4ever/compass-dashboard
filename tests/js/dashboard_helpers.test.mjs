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

const PURE_HELPERS = ['esc', 'fmtYM', '_daysSince', 'urgencyScore', 'scoreItem', 'scaleLinear', 'renderYAxisGridlines'];
const source = PURE_HELPERS.map(extractFunction).join('\n\n');
// `source` is read only from this repo's own scripts/template.html (never from
// user input, network, or CLI args) — there is no untrusted-string injection
// surface here, just an in-repo test harness for embedded functions.
const helpers = new Function(`${source}\nreturn { ${PURE_HELPERS.join(', ')} };`)();

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
