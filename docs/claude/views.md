# Compass Dashboard — per-view rules

Read the section for the view you are about to edit. Pointed to from `scripts/CLAUDE.md`;
the shared upkeep rules and budget are in the root `CLAUDE.md`.

## View-specific rules

**DAG** (`_dag`, `dagInitPositions()`/`dagSimStep()`)
- The dependency edge type is `'dep'` (per `EDGE_META`/`computeAllEdges()`), not `'depends'` —
  check init and sim both when retuning.
- Node geometry reads `n.r` (18–40px) and `n.fade`, computed once in
  `dagComputeVisualEncoding()`. Never hardcode a radius.
- `'shared'` (tag-overlap) edges are near-complete in this dataset. Tightening that spring
  collapses the graph into a blob. Keep spring force clamped to `±MAX_SPRING_F` and `REPEL`
  scaled by canvas area; re-verify visually with `showSystem` on after any canvas/spring change.
- Node/edge indices are into the full `NS` array — filter nodes, never `NS` itself.

**Mind Map** (`_mm`, `mmLayout`/`mmDraw`)
- `_mm.rotation` spins the whole compass (`mmRotate(±30)`, reset by `mmResetView()`, *not* by
  `mmSelectNs()`). Per-label rotation along each node's spoke is separate and composes with it.
- `mm-detail` is an absolutely-positioned overlay inside `.mm-canvas-wrap`, so its growth never
  resizes `mm-svg`. Keep it that way.
- `_mindmap_data(n)` is built fresh inside `_js_data()` — annotate the tree there, not on the
  `load_namespace()` dict.

**Radar** (per-namespace sub-tab, `renderRadar(ns)`) — 10 toggleable axes (`RADAR_AXIS_DEFS`),
each normalised 0–100 per namespace, min 3 active, persisted to
`localStorage['compass-radar-axes']`. Insufficient-data axes render hollow at 50, not dropped.
`healthColor()` (≥68 green / ≥40 amber / red) is module-scope and shared with Scorecard.

**Compare** (`renderCompare()`) — 6 fixed macro axes (`COMPARE_AXIS_DEFS`), no axis picker;
min-max normalisation across the currently visible namespaces only. `nsColor(namespace)` is the
single shared palette function — don't re-duplicate it.

**Global namespace filter** (`#gfilter`) — drives Overview, Priorities, Scorecard, DAG, Heatmap,
Compare. `globalVisibleNames()` (Set, `localStorage['compass-global-namespaces']`, default all
visible) and `visibleNS()` (filtered copy — `NS` stays `const`, never mutated).
- Overview cards are static HTML; `refreshOverviewVisibility()` hides/shows `#card-N`.
- Anything emitting `selectCard(${idx})` must use the **absolute** `NS` index, not the filtered
  array's index.
- Guard empty selections (e.g. Scorecard's `Math.min/max` on `[]`).
- `globalFilterRerender()` re-invokes uncached views and only clears+re-renders cached views
  (`dataset.rendered`/`_dag.rendered`) that have already been visited.

**Live strip** (`renderLiveStrip()`, `#live-strip` above the Overview grid) renders from the baked
`NS[*].pulse` (snake_case keys, passed through `_js_data()` unrenamed). It is a snapshot that
only ticks the clock: elapsed is the baked `elapsed_seconds` plus time since page load (never the
viewer's clock against `last_open`), re-rendered every 30 s with no polling or requests. The footer
says `snapshot as of HH:MM (N min ago)` and turns amber from 10 min, so it never claims to be live.
`renderLiveStrip(nowMs)` takes an injectable clock for tests. `_build_pulse(namespace, raw)` reads
no files (inputs come from `_read_namespace_files()`); its only I/O is `_pulse_git()`.
`pulse.git.errors` is dashboard-only; parity compares core's keys only. Spec:
`docs/superpowers/specs/2026-10-12-live-strip-design.md` (all 4 steps shipped). `generate_fixture.py` injects a synthetic `pulse` per namespace.
`--watch [s]` writes atomically; page state lives in `location.hash` (namespace by name).
`restoreUiHash()` must run last in the IIFE: it renders the detail panel (TDZ otherwise).

**Tasks sub-tab** (`deriveTasks(ns)`, pure JS over `ns.reality`) — reads `## What is next`,
inline `Next session:` lines, `plannedActions`, `deferred`, recent `history[].incomplete`, and
`## Backlog` → `### Tactical` (score N+3) / `### Strategic` (score N+1). Any other heading ends
the backlog bucket. There's no `--purple` CSS variable; Strategic uses a one-off `#a371f7`.

**State sub-tab** (`renderState()`) — always-visible Intent, Active goals and a "Health &
cadence" strip (`.state-health-strip`), then `stateGroup` drawers (Reality, Decisions & backlog,
Goal tracking, Cross-namespace signals, Feedback & failure analysis, Intent history). New
sections go in the matching drawer, not the flat top. The Reality drawer's upkeep lines
(`renderRealityUpkeep()`) show compaction cadence, eligible/archived counts with a `file://`
link to `reality_archive.md`, and verification durability over bullets still in reality.md.

**Learnings sub-tab** — type and zone filters compose through `applyLearningFilters(table,
nsId)` over `data-ltype`/`data-zone`; never set `row.style.display` from a second independent
filter. `filterLearningZone` (click-to-toggle) is exported; `applyLearningFilters` is not.

**Decision Guidance** (P65) — rendered inside the Decisions sub-tab by
`renderDecisionGuidance(ns)`, returns `''` when empty. It renders before the decisions empty state,
so a guidance-only namespace still shows its pairs. `qualityDelta` is `null` unless both evidence
qualities are numbers (`_guidance_quality_delta()`); core stores `evidence` unvalidated.
The tab label counts pairs via `decisionsTabLabel(ns)`. A "Guidance (N)" heading sits above the cards,
and a "Decisions (N)" heading above the list only when guidance is present. Each card leads with
`contextSummary`. The delta shows in `pp` (a difference of 0–1 scores), and a negative delta gets the
amber `.guidance-delta.neg` pill.
