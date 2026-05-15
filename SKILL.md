---
name: compass-dashboard
description: |
  Generate a self-contained interactive HTML dashboard from all compass namespace data.
  Aggregates intent, reality, learnings, session history, goal trends, and deferred
  opportunities across every active loop into a single visual overview.

  Usage:
    /compass-dashboard              — generate dashboard for all namespaces, open in browser
    /compass-dashboard <namespace>  — focus on a single namespace
    /compass-dashboard --output <path>  — write to custom path

  Related: /compass (the session loop skill this reads from)
---

## Script

```bash
python3 ~/.claude/skills/compass-dashboard/scripts/compass-dashboard.py [--namespace <ns>] [--output <path>] [--no-open]
```

## Namespace argument

If `$ARGUMENTS` contains a namespace name (not a path or flag), pass it as `--namespace`:

```bash
python3 ~/.claude/skills/compass-dashboard/scripts/compass-dashboard.py --namespace <ns>
```

## Default output

Writes to `~/Downloads/compass-dashboard.html` and opens in the default browser automatically.

## Report back

After the script exits, read the returned JSON and confirm:

```
✓ Dashboard generated → <path>
  <N> namespaces · <M> learnings · <K> sessions
  Opening in browser…
```

If the script returns `ok: false`, surface the error message to the user.
