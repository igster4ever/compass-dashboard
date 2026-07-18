# Backlog — compass read()/state.json data points not yet surfaced in the dashboard

**Origin:** compass-dashboard session 2026-07-18, goal 2 (compass-skill data-model audit).
**Method:** diffed `_build_orient_context()` in `~/.claude/skills/compass/scripts/compass/_monolith.py`
(the full `compass.py read` schema) and the raw keys in a sample `state.json` against what
`compass-dashboard.py`/`template.html` currently load. Out-of-scope items (interactive,
close-time-only data with no persisted trail) are noted but excluded from the actionable list.

Each item below is independently shippable — pick off one at a time, doesn't need to land as a batch.

---

## 1. `outcome_rate` (P49) — trivial add

- **Source:** `state.json["outcome_rate"]` — a plain float, already computed and persisted by
  `link-goal-outcome` / close-time bookkeeping. No new parsing needed.
- **Where to add:** State sub-tab, next to the existing reality-completeness pill (same visual
  weight — both are "session discipline" metrics).
- **Implementation breadcrumb:** `load_namespace()` around line 533 (`last_reality_score` read) —
  add `outcome_rate = state.get("outcome_rate")` alongside it, thread into the NS dict, render as
  a `%` pill in the State sub-tab template block (search `lastRealityScore` in `template.html` for
  the sibling pattern to copy).
- **Effort:** XS.

## 2. `goal_outcomes` (P49 links) — optional, medium effort

- **Source:** `state.json["goal_outcomes"]` — `{goal_hash: [reality_bullet_hash, ...]}`.
- **What it enables:** a "this goal produced these reality changes" traceability view — click a
  completed goal in History, see which reality bullets it's linked to.
- **Implementation breadcrumb:** goal_hash → goal text isn't stored anywhere obvious yet (check
  `_goal_hash()` in `compass/state.py` for the hashing function used at write time — the dashboard
  will need the same hash to resolve goal text from `planned_actions` in each session's history
  entry). Bullet hash → text already resolves via `reality_validation` (dashboard already parses
  this for `staleBulletCount`).
- **Effort:** M. **Defer until `outcome_rate` (item 1) shows meaningful adoption** — check a few
  namespaces' `goal_outcomes` dict sizes before investing; if mostly empty like compass-dashboard's
  own state.json, it's not worth the hash-resolution plumbing yet.

## 3. `quality_plateau` + `cadence_pull_forward` (P61b) — cheap, reuses existing data

- **Source:** computed each `read()` from `quality_history` (`_monolith.py:1168-1190`) — the
  dashboard already loads `quality_history` for the P51 sparklines, so no new file read.
- **What it enables:** a "⚠ plateaued" badge on the Quality Trend panel when the last 3 scored
  sessions show no improvement, matching compass's own ORIENT advisory.
- **Implementation breadcrumb:** replicate the 3-segment delta logic verbatim — `_monolith.py`
  lines 1168-1190 is the exact reference implementation (segment quality_history into thirds,
  compare mean of last segment vs first segment, threshold ±0.03 for improving/declining/stable).
  Add near `qualityHistory` field in `load_namespace()`.
- **Effort:** S.

## 4. `goal_contracts` + `contract_coverage` / `criteria_hit_rate` (P55) — cheap, low current data

- **Source:** `state.json["goal_contracts"]` — dict keyed by goal hash, schema in
  `compass/contracts.py`. `_compute_contract_coverage()` in `compass/state.py:117` is the
  reference computation (rolling window of last 20 completed goals).
- **Where to add:** small % badge, same visual treatment as corpus health / quality trend.
- **Caveat:** compass-dashboard's own `state.json` has zero contracts logged so far (P55 is new
  and this session didn't add any). **Check contract adoption across a few other namespaces before
  building this** — if it's uniformly empty, the widget will always read "no data" and isn't
  worth shipping yet.
- **Effort:** S, contingent on adoption check above.

## 5. Assumption-audit due chip (P47) — reuses already-loaded data

- **Source:** `state.json["sessions_since_assumption_audit"]` for the due flag; candidates are
  unvalidated hypothesis-type learnings with weight ≥2 and age >30d — all fields (`learning_type`,
  `weight`, `date`) are already loaded by the dashboard's Learnings sub-tab.
- **Where to add:** Overview card chip, same style/placement as the existing research-due /
  code-review-due chips.
- **Implementation breadcrumb:** `_check_assumption_audit_due()` and
  `_get_assumption_audit_candidates()` in `_monolith.py` (~line 2826) are the reference logic —
  simple age/weight filter over the learnings list the dashboard already has in memory.
- **Effort:** XS-S.

## 6. CLAUDE.md review due chip

- **Source:** `state.json["sessions_since_claude_review"]`.
- **Where to add:** same `repo_path`-gated pattern as `codeReviewDue` (dashboard already computes
  this gate for the code-review chip — reuse the same conditional).
- **Effort:** XS.

## 7. `dream_defer_count`

- **Source:** not a scalar in state.json — mirror the existing pattern for
  `code_review_deferrals.jsonl` / `research_deferrals.jsonl` (`compass-dashboard.py` lines 572-573)
  but for a `dream_deferrals.jsonl` file (confirm exact filename in `compass/_monolith.py`'s
  `defer-dream` command before wiring).
- **Where to add:** same red-at-≥2 escalation chip treatment as code-review/research defer counts
  (E21, already shipped).
- **Effort:** XS — copy-paste of an existing pattern.

## 8. `complexity_clustering_signals` (P50) — nice-to-have

- **Source:** computed from `decisions.jsonl` tag + `complexity_domain` fields (dashboard already
  loads decisions for the Decisions tab).
- **What it enables:** group/filter complex-or-chaotic decisions by tag in the existing Decisions
  tab (E22) — not a new tab, just a filter dimension.
- **Effort:** M. Lowest priority in this list — nice-to-have, not a gap in core "what needs
  attention" answering.

## 9. `skill_opt_status.friction_gate` (P61c)

- **Source:** derivable from `skill_feedback.jsonl`, which the dashboard already loads
  (`skillFeedback` field exists per `compass-dashboard.py` line 579/675).
- **Where to add:** one-line annotation on the existing SkillOpt Status widget — "thin signal"
  badge when open (unresolved) feedback count is below threshold (default 3, see
  `_check_skill_opt_friction_gate()` in `_monolith.py`).
- **Effort:** XS.

## 10. `golden_zone_conflict` (P61a) / contradiction detection (P12.2) — OUT OF SCOPE

- Interactive close-time-only decision (Y/N prompt when a new learning may contradict an existing
  one). No persisted jsonl trail exists to render — there is nothing for a static-generation
  dashboard to show. Confirmed out of scope per this session's goal statement ("any P-XX feature
  not suitable or compatible for UI visualisation").

---

## Bug found during this audit (not a gap — a live correctness issue)

**`active_learnings` filter in `compass-dashboard.py:498` is stale.**

```python
active_learnings = [l for l in all_learnings if not l.get("superseded_by")]
```

This only excludes `superseded_by` (P12 merge). It does **not** exclude `status in
("archived", "superseded")` — and P44 (episodic learning auto-decay, shipped in
`compass/_monolith.py`'s `cmd_read`, ~line 1272-1285) now sets `status: "archived"` +
`archived_reason: "episodic_stale"` automatically on episodic learnings older than
`episodic_stale_days` (default 60) with fewer than 2 surfacings. This is exactly the
"P33 forward-compat" TODO already documented in this repo's own `CLAUDE.md` — the
underlying mechanism it was written to anticipate has since shipped for real.

**Current impact:** none yet — checked all 12 active namespaces
(`~/.claude/loop/*/learnings.jsonl`) on 2026-07-18 and none have any `status: "archived"`
entries yet (no namespace has logged an episodic learning old enough to decay). **Latent,
not manifesting.**

**Fix:** one-line change —
```python
active_learnings = [
    l for l in all_learnings
    if not l.get("superseded_by") and l.get("status") not in ("archived", "superseded")
]
```
Also check the two other `status not in (...)` call sites at lines 368 and 403 for the
same drift (line 368 already handles both statuses correctly — line 403 does too — only
line 498's `load_namespace()` filter is behind).

**Effort:** XS. **Priority: do this before the first real episodic learning ages out** —
cheap now, silent miscount later. Recommend picking this up as a fast follow, independent
of the other items above.
