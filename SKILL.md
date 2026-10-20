---
name: compass-dashboard
description: |
  Build one self-contained HTML dashboard from compass loop data (intent, reality, learnings,
  decisions, history, goal trends) across all namespaces.
  Usage: /compass-dashboard [namespace] [--output <path>]. Reads data from /compass.
---

## Script

```bash
~/.claude/skills/compass-dashboard/scripts/run.sh [--namespace <ns>] [--output <path>] [--no-open]
```

## Namespace argument

If `$ARGUMENTS` contains a namespace name (not a path or flag), pass it as `--namespace`:

```bash
~/.claude/skills/compass-dashboard/scripts/run.sh --namespace <ns>
```

## Default output

Writes to `~/Downloads/compass-dashboard.html` and opens in the default browser automatically.

## What the dashboard shows

### Overview view (namespace cards + detail panel)

Each namespace card shows: status (OPEN/CLOSED), last activity, intent summary, session
count, learning count, goal completion rate, and top tags.

Click a card to open the detail panel with four tabs:

| Tab | Contents |
|---|---|
| **State** | Intent · Active goals (open sessions) · Next session entry point (code_context.md) · Reality · Recent decisions (last 3) · Deferred opportunities |
| **Learnings** | Full learnings table sorted by weight — columns: weight, text, tags, type (fact/hypothesis), date |
| **Decisions** | Full decisions log (newest first) — each entry shows decision text, rationale, alternatives considered, date. Tab only appears when decisions exist. |
| **History** | Last 5 sessions — collapsible cards showing completed, incomplete, learnings extracted, notes |

### Priorities view

Ranks up to 4 non-system namespaces by attention need. Score factors:
- Open session in progress (+30)
- Staleness: >14d since last close (+25), >7d (+15)
- Low goal completion rate: <50% (+20), <75% (+10)
- Deferred items (+4 each)
- Planned actions waiting (+8)
- High-weight learnings active (+2 each, max +10)
- No sessions yet (+10)

Each priority card shows: recommended next action, why it was ranked, and
cross-compass signals (concurrent open sessions, reality/planned-work references
to other namespaces, overlapping high-weight learning tags).

## Report back

After the script exits, read the returned JSON and confirm:

```
✓ Dashboard generated → <path>
  <N> namespaces · <M> learnings · <K> sessions
  Opening in browser…
```

If the script returns `ok: false`, surface the error message to the user.
