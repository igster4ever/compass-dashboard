# compass-dashboard "Live strip" — design

Status: **approved 2026-10-12, not yet built.** Written in the compass-pulse session S-3 (goal 3)
and moved here from `compass-pulse/docs/` once approved. The "Rough build order" below is the
input for the implementation plan.

## Intent

compass-pulse makes a running session legible inside Claude Code (phase, goals, reality flow,
loop health). The dashboard answers the same question across *all* namespaces, but only through
deep tabs. A **Live strip** at the top of the Overview would answer "what is happening right now,
and does anything need me?" without opening anything.

## The contradiction

| Wanted | Standing rule it collides with |
|---|---|
| **Live**: reflects the session as it is now | The dashboard is static HTML with "no runtime backend and there never will be" (`CLAUDE.md`, Architecture) |
| Reuse `compass.py pulse` as the source of truth | The dashboard reads namespace dirs directly and mirrors core logic under a parity suite, rather than shelling out to `compass.py` |
| No drift between pulse and dashboard | Last session rejected a shared snapshot file: it breaks `pulse` read-purity and goes stale silently |

Pushing past a plain compromise (TRIZ, ideal final result): the strip needs no live channel at all
if everything that *changes between generations* is a pure function of a timestamp. Elapsed time,
"closed 3h ago" and "snapshot is 12 min old" all are. Only goal ticks, reality edits and phase
changes need fresh data, and those only need regenerating, which the dashboard already does.
So: **bake, then tick, then regenerate**; never poll.

ASIT check: *Unification* (the strip reuses data `load_namespace()` already loads, no new
reader), *Object removal* (no server, no snapshot file, no subprocess in the render path),
*Breaking symmetry* (only open namespaces get a full row; idle ones collapse).

## Design

### 1. Data: a `pulse` object per namespace, built at generation time

Add `pulse` to each namespace dict with the **same field names** as `compass.py pulse`
(`phase`, `open_session`, `last_open`, `elapsed_seconds`, `typical_minutes`, `goals`,
`reality_delta`, `cadences`, `quality`, `git`) plus `generated_at`.

**Chosen source (my call): a mirror function in `compass-dashboard.py`, guarded by a parity test**,
because that is how every other core-derived value here already works (`test_core_parity.py`
exists for exactly this). Most fields (`goals`, `cadences`, `quality`) are probably already
computed by `_assemble_namespace_dict()`; the new work is `phase`, `elapsed`, `typical_minutes`,
`reality_delta` and `git`.

Fallback if the mirror proves costly: one `compass.py pulse <ns>` subprocess per namespace at
generation time. It is read-pure and cannot drift, but it breaks the no-shell-out convention,
so it needs an explicit exception in `CLAUDE.md`.

### 2. Rendering: one row per open namespace

```
◆ WORK  compass-pulse   14m of ~17m   ▮▮▯▯ 2/4   ▲1 ▼0   due: –    1 uncommitted
◆ ORIENT gps-wiki        3m
  2 idle · last close compass-dashboard 2d ago                       as of 08:54 (2 min ago)
```

- Phase chip uses the pulse colours (`PHASE_COLOR` in `hooks/register.tsx`) so the two surfaces match.
- Elapsed is **computed client-side** from `last_open` and `Date.now()`, ticking every 30 s.
- Idle namespaces fold into one summary line. No open loops at all gives one line, not an empty box.
- Row click selects that namespace via the existing selection path (no new navigation).
- **Honest staleness:** a badge shows `as of HH:MM (N min ago)` and turns amber after 10 minutes.
  The strip never claims to be live when it is a snapshot; "Live" is the name of the strip, not a promise.

### 3. Keeping it fresh without a backend: `--watch`

`compass-dashboard --watch [seconds]` (default 30) regenerates the *same output file* in a loop,
writing atomically (temp file then rename). Pages generated with `--watch` carry a small timer that
calls `location.reload()` when the snapshot is older than the interval. To survive the reload,
persist the selected namespace, view and tab in `location.hash` (not `localStorage`, which can
throw or come back empty). Without `--watch` there is no timer and nothing changes today's behaviour.

No new files, no server, and `pulse` is never written to.

## Goals

- At-a-glance state of every open loop on the Overview, above existing content.
- Zero drift from pulse semantics, enforced by a test rather than by discipline.
- Static HTML, stdlib-only Python and hand-rolled JS preserved.

## Non-goals

- A server, websocket, SSE or any request made from the page.
- Writing back to compass state (the strip is read-only).
- Replacing the in-Claude pane or band.
- Sub-30-second freshness.

## Anti-goals (failure even if it technically works)

- A stale strip that looks live.
- Page state (selected tab, scroll) lost on every refresh in watch mode.
- Any regression to the existing render smoke test or generation time.

## Risks and open questions

1. **How much of `pulse` is already mirrored?** I have not diffed `_assemble_namespace_dict()`
   against `compass.py pulse`. It decides mirror vs subprocess cost.
2. **`location.reload()` over `file://`** works but flashes; fine for a glanceable page, worth a
   check that scroll position survives (anchor off page-wide per `CLAUDE.md` trap 6).
3. **Clock skew:** elapsed uses the browser clock against `last_open` from the machine's clock.
   Same machine in practice; if the HTML is ever opened elsewhere, elapsed would be wrong. Mitigate by
   computing against `generated_at`'s `now` plus time since page load, not the raw browser clock.
4. **Naming:** "Live" over-promises; consider "Now".

## Testing

- `tests/test_core_parity.py`: a live parity case comparing each mirrored `pulse` field with
  `compass.py pulse <ns>` for a fixture namespace.
- `tests/test_generate.py`: `[[PLACEHOLDER]]` still fully replaced; `--watch` writes atomically.
- `node --test tests/js/render_smoke.test.mjs`: add cases for open, closing, idle-only and
  no-namespace states and the amber staleness badge.
- `template.html` traps apply: new inline handlers go in `Object.assign(window, …)`; use `grep -a`.

## Rough build order (for the later plan)

1. Mirror `pulse` fields into the namespace dict, with the parity test first.
2. Render the strip from `NS[*].pulse`, static (no ticking).
3. Client-side elapsed ticking and the staleness badge.
4. `--watch` plus hash-persisted selection.

## Confidence

| Aspect | Score | Why |
|---|---|---|
| Bake-tick-regenerate resolves the contradiction | 8/10 | Fits every stated constraint; unproven against real use |
| Mirror (not subprocess) as the data source | 6/10 | Depends on open question 1, which I haven't checked |
| `--watch` reload plus hash persistence | 6/10 | `file://` reload behaviour and scroll restore untested |
| Strip layout | 5/10 | Sketched in text only, never seen |
