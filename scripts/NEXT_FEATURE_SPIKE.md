# Next Feature Surface — Spike / Decision Note
_Generated: 2026-06-18 · compass-dashboard session_

---

## Candidates assessed

### A — Global decisions registry
Aggregate all decisions from every namespace into a single chronological feed.

**Data available now:** `ns.decisions[]` already in NS array — each entry has `decision`, `rationale`, `alternatives`, `date`. No new Python needed.

**Render:** sortable table or timeline. Columns: date, namespace badge, decision summary, rationale on expand. Filter by namespace or tag.

**Value:** decisions are currently buried in per-namespace sub-tabs. A unified view answers "what was decided across the whole project and when" — directly serves the intent's "what needs attention right now" criterion (overdue decisions, conflicting decisions across namespaces).

**Complexity:** low. ~80 lines JS. No new Python. No new data model fields.

**Verdict: BUILD THIS FIRST.**

---

### B — Cross-namespace session swimlane
One row per namespace, session dates as dots on a shared time axis.

**Data available:** `ns.sessionDates[]` (full history, YYYY-MM-DD strings). No duration data for most sessions (cycleHistory is capped at last 10).

**Render:** SVG dot plot, one row per namespace, x-axis = date, dots = sessions. Could colour by open/closed session.

**Value:** shows temporal rhythm and gaps at a glance. Reveals things like "3-week gap in gps-wiki while compass-dashboard was active". Complements the session heatmap (monthly granularity → daily granularity).

**Complexity:** low–medium. ~60 lines JS. But with only dot precision (no bars), it's not much richer than the existing heatmap. Upgrade path: add duration once cycleHistory is extended.

**Verdict: worth building after A, or as a sub-panel of the existing Heatmap tab.**

---

### C — Tag knowledge map (force graph)
Force-directed graph where nodes are tags, edges = learnings that share both tags, thickness = edge strength.

**Data available:** `ns.learnings[]` with `tags[]`. Tag co-occurrence computable in JS.

**Render:** D3 force simulation (already have D3 for DAG). Nodes coloured by dominant namespace.

**Value:** shows which topic areas cluster — e.g., if `tooling` and `debugging` always co-occur, that's a signal worth knowing. Potentially useful for cross-namespace pattern detection.

**Complexity:** medium. ~150 lines JS + D3 layout. Risk: with 18 learnings across namespaces, the graph may be too sparse to be meaningful. Revisit when corpus > 50 active learnings.

**Verdict: DEFER. Corpus too small; graph will look empty.**

---

### D — Hypothesis tracker
Dedicated view of all unvalidated hypotheses across namespaces, sorted by age and urgency.

**Data available:** `ns.learnings[]` filtered by `learning_type === 'hypothesis'`.

**Render:** simple table — hypothesis text, namespace, age, confidence, validation status.

**Value:** direct "what needs attention" signal.

**Complexity:** very low. ~40 lines JS.

**Verdict: DEFER. Only 4 hypotheses exist across all namespaces. Not worth a tab until corpus grows. Add as a filter to the Learnings sub-tab instead.**

---

## Decision

**Build: Global decisions registry** as a new `Decisions` view tab.

**Then: Cross-namespace session swimlane** as an additional sub-panel in the Heatmap tab (next to the existing Session Activity, Goal Completion, etc.).

**Skip for now:** tag knowledge map (corpus too small), hypothesis tracker (data too sparse → add as a learnings filter when count > 10 across all namespaces).

---

## Implementation sketch — Global decisions registry

**New view tab: `decisions`**

Data construction (JS, no Python changes):
```js
// In switchView or on tab init:
const allDecisions = NS.flatMap(ns =>
  (ns.decisions || []).map(d => ({...d, namespace: ns.namespace}))
).sort((a, b) => (b.date || '').localeCompare(a.date || ''));
```

Render: filtered table with expand-on-click for rationale. Namespace badge (colour-coded). Search integration via existing ⌘K palette.

**Tab wiring checklist** (per CLAUDE.md tab system rules):
1. Button in `<nav>` HTML
2. `<div id="view-decisions">` in HTML
3. Add `'decisions'` to `switchView()` forEach array
4. `if (v === 'decisions') renderDecisions();` in `switchView()`
5. `renderDecisions()` function

Estimated: ~90 lines JS, 0 lines Python, ~30 min.

---

## Implementation sketch — Cross-namespace swimlane

Add as `sessions-timeline` sub-panel to the Heatmap tab selector.

Data: `ns.sessionDates[]` → deduplicate into `{YYYY-MM-DD: [namespace, ...]}` map. X-axis spans min→max date across all namespaces.

SVG render: one row per namespace, dots at each session date. Hover tooltip shows date + count.

Estimated: ~70 lines JS, 0 lines Python, ~25 min.
