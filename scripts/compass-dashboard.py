#!/usr/bin/env python3
"""
compass-dashboard.py — generate a self-contained HTML dashboard from compass loop data.
stdlib-only (json, pathlib, datetime, re, subprocess, argparse). No pip installs.

Usage:
    python3 compass-dashboard.py [--namespace <ns>] [--output <path>] [--no-open]
"""

import json
import sys
import re
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timezone

LOOP_DIR    = Path.home() / ".claude" / "loop"
OUTPUT_PATH = Path.home() / "Downloads" / "compass-dashboard.html"


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc():
    return datetime.now(timezone.utc)


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _time_ago(dt):
    if dt is None:
        return "never"
    delta = _now_utc() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return f"{days}d ago"


def _read_file(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _read_jsonl(path):
    items = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return items


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _e(s):
    """HTML-escape a string."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def _parse_history_file(path):
    text = _read_file(path)
    if not text:
        return None

    result = {
        "filename": Path(path).name,
        "opened": "",
        "closed": "",
        "planned": [],
        "completed": [],
        "incomplete": [],
        "notes": "",
        "learnings_extracted": [],
    }

    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("**Opened:**"):
            result["opened"] = s.replace("**Opened:**", "").strip()
        elif s.startswith("**Closed:**"):
            result["closed"] = s.replace("**Closed:**", "").strip()
        elif s == "## Planned":
            section = "planned"
        elif s == "## Completed":
            section = "completed"
        elif s == "## Incomplete":
            section = "incomplete"
        elif s == "## Notes":
            section = "notes"
        elif s == "## Learnings extracted":
            section = "learnings_extracted"
        elif s.startswith("## "):
            section = None
        elif (s.startswith("- ") or s.startswith("* ")) and section in (
            "planned", "completed", "incomplete", "learnings_extracted"
        ):
            item = s[2:].strip().lstrip("✓✗ ").strip()
            if item and item not in ("(none)", "(none recorded)"):
                result[section].append(item)
        elif section == "notes" and s:
            result["notes"] += s + " "

    return result


def _top_tags(learnings, n=5):
    counts = {}
    for l in learnings:
        for tag in l.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def _goal_stats(state):
    completions = state.get("goal_completions", {})
    if not completions:
        return None, []

    sessions = sorted(completions.items())[-5:]

    dots = []
    for _, statuses in sessions:
        total = len(statuses)
        n_done = sum(1 for s in statuses if s == "completed")
        rate = int((n_done / total * 100) if total else 0)
        level = "high" if rate >= 80 else "mid" if rate >= 50 else "low"
        dots.append({"level": level, "rate": rate})

    latest = sessions[-1][1] if sessions else []
    total = len(latest)
    n_done = sum(1 for s in latest if s == "completed")
    rate = int((n_done / total * 100) if total else 0) if total else None

    return rate, dots


def load_namespace(ns_dir):
    state        = _read_json(ns_dir / "state.json")
    intent       = _read_file(ns_dir / "intent.md")
    reality      = _read_file(ns_dir / "reality.md")
    learnings    = _read_jsonl(ns_dir / "learnings.jsonl")
    decisions    = _read_jsonl(ns_dir / "decisions.jsonl")
    code_context = _read_file(ns_dir / "code_context.md")

    history_dir   = ns_dir / "history"
    history_files = []
    if history_dir.exists():
        for f in sorted(history_dir.glob("*.md"), reverse=True)[:5]:
            parsed = _parse_history_file(f)
            if parsed:
                history_files.append(parsed)

    session_count = len(list(history_dir.glob("*.md"))) if history_dir.exists() else 0

    open_session = state.get("open_session", False)
    last_close   = _parse_iso(state.get("last_close"))
    last_open    = _parse_iso(state.get("last_open"))
    goal_rate, goal_dots = _goal_stats(state)

    intent_summary = ""
    for line in intent.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            intent_summary = line
            break

    return {
        "namespace":       ns_dir.name,
        "open_session":    open_session,
        "last_close":      last_close,
        "last_open":       last_open,
        "planned_actions": state.get("planned_actions", []),
        "deferred":        state.get("deferred_opportunities", {}),
        "intent":          intent,
        "intent_summary":  intent_summary,
        "reality":         reality,
        "learnings":       sorted(learnings, key=lambda x: -x.get("weight", 1)),
        "decisions":       decisions,
        "code_context":    code_context,
        "history":         history_files,
        "goal_rate":       goal_rate,
        "goal_dots":       goal_dots,
        "top_tags":        _top_tags(learnings),
        "session_count":   session_count,
    }


def discover_namespaces(filter_ns=None):
    if not LOOP_DIR.exists():
        return []

    result = []
    for d in sorted(LOOP_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("."):
            continue
        if not (d / "state.json").exists():
            continue
        if filter_ns and d.name != filter_ns:
            continue
        result.append(load_namespace(d))

    def sort_key(n):
        if n["open_session"]:
            return (0, 0)
        lc = n["last_close"]
        return (1, -(lc.timestamp() if lc else 0))

    result.sort(key=sort_key)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HTML card generation (Python side — static markup)
# ─────────────────────────────────────────────────────────────────────────────

def _card_html(n, i):
    status_cls   = "open" if n["open_session"] else "closed"
    status_label = "OPEN" if n["open_session"] else "CLOSED"
    time_label   = _time_ago(n["last_open"] if n["open_session"] else n["last_close"])

    summary = n["intent_summary"][:90]
    if len(n["intent_summary"]) > 90:
        summary += "…"

    tags_html = "".join(
        f'<span class="tag">{_e(t)}</span>' for t in n["top_tags"][:3]
    )

    rate_html = ""
    if n["goal_rate"] is not None:
        rc = "high" if n["goal_rate"] >= 80 else "mid" if n["goal_rate"] >= 50 else "low"
        rate_html = f'<span class="rate-pill {rc}">{n["goal_rate"]}%</span>'

    deferred_html = ""
    dc = len(n["deferred"])
    if dc > 0:
        deferred_html = f'<span class="deferred-chip">{dc} deferred</span>'

    return f"""
    <div class="card" id="card-{i}" data-idx="{i}" onclick="selectCard({i})">
      <div class="card-top">
        <span class="ns-name">{_e(n["namespace"])}</span>
        <span class="badge {status_cls}">{status_label}</span>
      </div>
      <div class="card-time">{_e(time_label)}</div>
      <div class="card-intent">{_e(summary)}</div>
      <div class="card-stats">
        <span>{n["session_count"]} sessions</span>
        <span>{len(n["learnings"])} learnings</span>
        {rate_html}
        {deferred_html}
      </div>
      <div class="card-tags">{tags_html}</div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────────────
# JS data serialisation
# ─────────────────────────────────────────────────────────────────────────────

def _js_data(namespaces):
    data = []
    for n in namespaces:
        data.append({
            "namespace":      n["namespace"],
            "open":           n["open_session"],
            "lastClose":      _time_ago(n["last_close"]),
            "lastOpen":       _time_ago(n["last_open"]),
            "intentSummary":  n["intent_summary"][:150],
            "intent":         n["intent"],
            "reality":        n["reality"],
            "learnings":      n["learnings"],
            "decisions":      n["decisions"],
            "codeContext":    n["code_context"],
            "history":        n["history"],
            "goalRate":       n["goal_rate"],
            "goalDots":       n["goal_dots"],
            "topTags":        n["top_tags"],
            "deferred":       [
                {"key": k, **v}
                for k, v in n["deferred"].items()
            ],
            "sessionCount":   n["session_count"],
            "plannedActions": n["planned_actions"],
        })
    raw = json.dumps(data, ensure_ascii=False, default=str)
    # Prevent </script> from breaking the embedding
    return raw.replace("</script>", r"<\/script>").replace("<!--", r"<\!--")


# ─────────────────────────────────────────────────────────────────────────────
# HTML template
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Compass Dashboard</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:       #0d1117;
      --surface:  #161b22;
      --surface2: #21262d;
      --border:   #30363d;
      --text:     #e6edf3;
      --muted:    #8b949e;
      --subtle:   #484f58;
      --green:    #3fb950;
      --green-bg: rgba(63,185,80,.12);
      --blue:     #58a6ff;
      --blue-bg:  rgba(88,166,255,.12);
      --amber:    #d29922;
      --amber-bg: rgba(210,153,34,.12);
      --red:      #f85149;
      --red-bg:   rgba(248,81,73,.12);
      --radius:   8px;
    }

    html { font-size: 14px; }
    body {
      background: var(--bg); color: var(--text);
      font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, monospace;
      min-height: 100vh;
    }

    /* ── Header ── */
    header {
      position: sticky; top: 0; z-index: 100;
      background: var(--surface); border-bottom: 1px solid var(--border);
      height: 52px;
    }
    .header-inner {
      max-width: 1400px; margin: 0 auto; padding: 0 1rem; height: 100%;
      display: flex; align-items: center; justify-content: space-between;
    }
    .header-left { display: flex; align-items: baseline; gap: .75rem; }
    .header-left h1 { font-size: .95rem; font-weight: 600; }
    .header-left .since { color: var(--muted); font-size: .72rem; }
    .header-stats { display: flex; gap: 1.5rem; }
    .hstat { display: flex; flex-direction: column; align-items: center; }
    .hstat-val { font-size: .95rem; font-weight: 600; color: var(--blue); line-height: 1.2; }
    .hstat-lbl { font-size: .62rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }

    /* ── Main ── */
    main { max-width: 1400px; margin: 0 auto; padding: 1rem; }

    /* ── Card grid ── */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: .75rem; margin-bottom: .75rem;
    }

    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: .875rem 1rem;
      cursor: pointer; transition: border-color .15s, box-shadow .15s;
      display: flex; flex-direction: column; gap: .45rem;
    }
    .card:hover { border-color: var(--blue); }
    .card.selected { border-color: var(--blue); box-shadow: 0 0 0 1px var(--blue); }

    .card-top { display: flex; align-items: center; justify-content: space-between; }
    .ns-name { font-weight: 600; font-size: .875rem; }

    .badge {
      font-size: .62rem; font-weight: 700; letter-spacing: .07em;
      padding: .15em .55em; border-radius: 999px;
    }
    .badge.open   { background: var(--green-bg); color: var(--green); }
    .badge.closed { background: var(--surface2); color: var(--muted); }

    .card-time { font-size: .7rem; color: var(--muted); }
    .card-intent {
      font-size: .8rem; color: var(--muted); font-style: italic;
      line-height: 1.45; min-height: 2.3em;
    }
    .card-stats {
      display: flex; flex-wrap: wrap; gap: .4rem;
      font-size: .7rem; color: var(--subtle); align-items: center;
    }
    .rate-pill {
      font-size: .62rem; font-weight: 600;
      padding: .15em .5em; border-radius: 999px;
    }
    .rate-pill.high { background: var(--green-bg); color: var(--green); }
    .rate-pill.mid  { background: var(--amber-bg); color: var(--amber); }
    .rate-pill.low  { background: var(--red-bg);   color: var(--red); }
    .deferred-chip {
      font-size: .62rem; background: var(--amber-bg); color: var(--amber);
      padding: .15em .5em; border-radius: 999px;
    }
    .card-tags { display: flex; flex-wrap: wrap; gap: .3rem; min-height: 1.4em; }
    .tag {
      font-size: .62rem; background: var(--surface2); color: var(--muted);
      padding: .15em .55em; border-radius: 4px;
    }

    /* ── Detail panel ── */
    .detail {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); overflow: hidden; display: none;
    }
    .detail.visible { display: block; }

    .detail-header {
      background: var(--surface2); border-bottom: 1px solid var(--border);
      padding: .75rem 1rem; display: flex; align-items: center; gap: .75rem;
    }
    .detail-ns { font-weight: 700; font-size: .95rem; }

    .tabs {
      display: flex; border-bottom: 1px solid var(--border);
      background: var(--surface2);
    }
    .tab-btn {
      padding: .55rem 1rem; font-size: .78rem; font-family: inherit;
      cursor: pointer; background: none; border: none; color: var(--muted);
      border-bottom: 2px solid transparent; margin-bottom: -1px;
      transition: color .12s;
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active { color: var(--blue); border-bottom-color: var(--blue); }

    .tab-content { padding: 1rem; display: none; max-height: 70vh; overflow-y: auto; }
    .tab-content.active { display: block; }

    /* ── Markdown sections ── */
    .md-section { margin-bottom: 1.25rem; }
    .md-section h3 {
      font-size: .72rem; font-weight: 600; color: var(--muted);
      text-transform: uppercase; letter-spacing: .07em; margin-bottom: .5rem;
      border-bottom: 1px solid var(--border); padding-bottom: .35rem;
    }
    .md-section h4 { font-size: .85rem; font-weight: 600; color: var(--text); margin: .75rem 0 .35rem; }
    .md-section ul { list-style: none; padding: 0; }
    .md-section li {
      font-size: .82rem; color: var(--text); padding: .3rem 0 .3rem 1rem;
      position: relative; border-bottom: 1px solid transparent;
    }
    .md-section li::before { content: "–"; position: absolute; left: 0; color: var(--subtle); }
    .md-section p { font-size: .82rem; color: var(--muted); line-height: 1.6; margin-bottom: .4rem; }
    .empty-state { font-size: .82rem; color: var(--subtle); font-style: italic; padding: .5rem 0; }

    /* ── Goals list ── */
    .goals-list { list-style: none; padding: 0; }
    .goals-list li {
      font-size: .82rem; padding: .4rem 0 .4rem 1.5rem;
      border-bottom: 1px solid var(--border); position: relative; color: var(--text);
    }
    .goals-list li::before { content: "→"; position: absolute; left: 0; color: var(--blue); }

    /* ── Learnings table ── */
    .learnings-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
    .learnings-table th {
      text-align: left; color: var(--muted); font-weight: 600;
      font-size: .68rem; text-transform: uppercase; letter-spacing: .05em;
      padding: .4rem .5rem; border-bottom: 1px solid var(--border);
      position: sticky; top: 0; background: var(--surface);
    }
    .learnings-table td {
      padding: .5rem; border-bottom: 1px solid var(--surface2); vertical-align: top;
    }
    .learnings-table tr:hover td { background: var(--surface2); }

    .weight-dot { display: inline-flex; align-items: center; gap: .3rem; }
    .wdot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .wdot.w-high { background: var(--green); }
    .wdot.w-mid  { background: var(--amber); }
    .wdot.w-low  { background: var(--subtle); }
    .wnum { color: var(--muted); font-size: .75rem; }

    .tags-cell { display: flex; flex-wrap: wrap; gap: .25rem; }

    .type-badge { font-size: .62rem; padding: .1em .45em; border-radius: 4px; font-weight: 600; }
    .type-fact       { background: var(--blue-bg);  color: var(--blue); }
    .type-hypothesis { background: var(--amber-bg); color: var(--amber); }

    .learning-text { line-height: 1.5; color: var(--text); }

    /* ── History timeline ── */
    .timeline { display: flex; flex-direction: column; gap: .6rem; }
    .session-card { border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
    .session-header {
      background: var(--surface2); padding: .5rem .75rem;
      display: flex; align-items: center; justify-content: space-between;
      cursor: pointer; user-select: none;
    }
    .session-date { font-size: .75rem; font-weight: 600; color: var(--blue); }
    .session-meta { font-size: .7rem; color: var(--muted); }
    .session-chevron { font-size: .7rem; color: var(--subtle); transition: transform .15s; }
    .session-card.expanded .session-chevron { transform: rotate(90deg); }
    .session-body { padding: .75rem; display: none; }
    .session-body.open { display: block; }

    .session-section { margin-bottom: .65rem; }
    .session-section:last-child { margin-bottom: 0; }
    .session-label {
      font-size: .62rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .07em; color: var(--muted); margin-bottom: .3rem;
    }
    .session-items { list-style: none; padding: 0; }
    .session-items li { font-size: .78rem; color: var(--text); padding: .2rem 0 .2rem 1.2rem; position: relative; }
    .session-items li.done::before   { content: "✓"; position: absolute; left: 0; color: var(--green); }
    .session-items li.undone::before { content: "✗"; position: absolute; left: 0; color: var(--red); }
    .session-items li.plain::before  { content: "·"; position: absolute; left: 0; color: var(--subtle); }
    .session-note { font-size: .78rem; color: var(--muted); font-style: italic; margin-top: .5rem; }

    /* ── Deferred panel ── */
    .deferred-list { list-style: none; padding: 0; }
    .deferred-list li {
      font-size: .8rem; color: var(--text); padding: .4rem 0;
      border-bottom: 1px solid var(--surface2);
      display: flex; gap: .5rem; align-items: flex-start;
    }
    .defer-count {
      flex-shrink: 0; font-size: .62rem;
      background: var(--amber-bg); color: var(--amber);
      padding: .1em .45em; border-radius: 999px; margin-top: .1em;
    }

    /* ── No selection state ── */
    .no-selection { text-align: center; padding: 2rem; color: var(--subtle); font-size: .85rem; }
    .no-selection .arrow { font-size: 1.4rem; margin-bottom: .4rem; display: block; opacity: .5; }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    /* ── Top-level view tabs ── */
    .view-nav {
      display: flex; border-bottom: 1px solid var(--border); margin-bottom: .75rem;
    }
    .view-tab {
      padding: .5rem 1.25rem; font-size: .82rem; font-family: inherit;
      cursor: pointer; background: none; border: none;
      border-bottom: 2px solid transparent; color: var(--muted);
      margin-bottom: -1px; transition: color .12s;
    }
    .view-tab:hover { color: var(--text); }
    .view-tab.active { color: var(--blue); border-bottom-color: var(--blue); }

    /* ── Priority cards ── */
    .priority-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: .75rem; margin-bottom: .75rem;
    }
    .priority-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1rem;
      display: flex; flex-direction: column; gap: .65rem;
      transition: box-shadow .15s;
    }
    .priority-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.35); }
    .priority-card.rank-1 { border-color: var(--green); }
    .priority-card.rank-2 { border-color: var(--blue); }
    .priority-card.rank-3 { border-color: var(--amber); }
    .priority-card.rank-4 { border-color: var(--subtle); }

    .p-header { display: flex; align-items: center; gap: .6rem; }
    .p-rank { font-size: 1.1rem; font-weight: 800; min-width: 2rem; }
    .rank-1 .p-rank { color: var(--green); }
    .rank-2 .p-rank { color: var(--blue); }
    .rank-3 .p-rank { color: var(--amber); }
    .rank-4 .p-rank { color: var(--subtle); }
    .p-ns { font-weight: 700; font-size: .95rem; flex: 1; }
    .p-intent { font-size: .78rem; color: var(--muted); font-style: italic; line-height: 1.4; }
    .p-action {
      font-size: .75rem; font-weight: 600; color: var(--blue);
      padding: .4rem .75rem; background: var(--blue-bg);
      border-radius: var(--radius); text-align: center;
    }
    .p-section-label {
      font-size: .62rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .07em; color: var(--muted); margin-bottom: .3rem;
    }
    .p-reasons { list-style: none; padding: 0; display: flex; flex-direction: column; gap: .2rem; }
    .p-reason { font-size: .78rem; color: var(--text); display: flex; align-items: baseline; gap: .45rem; }
    .p-reason-icon { color: var(--amber); flex-shrink: 0; font-size: .85rem; }
    .p-signals { display: flex; flex-direction: column; gap: .3rem; }
    .p-signal {
      font-size: .75rem; padding: .3rem .55rem; border-radius: 4px;
      display: flex; gap: .4rem; align-items: flex-start; line-height: 1.4;
    }
    .p-signal.sig-shared     { background: var(--blue-bg);  color: var(--blue); }
    .p-signal.sig-dep        { background: var(--amber-bg); color: var(--amber); }
    .p-signal.sig-conflict   { background: var(--red-bg);   color: var(--red); }
    .p-signal.sig-concurrent { background: var(--green-bg); color: var(--green); }
    .p-signal-icon { flex-shrink: 0; }
    .p-no-signals { font-size: .75rem; color: var(--subtle); font-style: italic; }
    .p-score { font-size: .62rem; color: var(--subtle); text-align: right; padding-top: .25rem; border-top: 1px solid var(--surface2); }

    /* ── Decision cards ── */
    .decision-list { display: flex; flex-direction: column; gap: .5rem; }
    .decision-item {
      border: 1px solid var(--border); border-radius: 6px;
      padding: .6rem .75rem; background: var(--surface2);
    }
    .decision-text { font-size: .82rem; color: var(--text); line-height: 1.45; margin-bottom: .3rem; }
    .decision-meta { display: flex; gap: .75rem; flex-wrap: wrap; align-items: baseline; }
    .decision-rationale { font-size: .75rem; color: var(--muted); flex: 1; line-height: 1.4; }
    .decision-date { font-size: .68rem; color: var(--subtle); white-space: nowrap; }
    .decision-alts { font-size: .72rem; color: var(--subtle); font-style: italic; margin-top: .25rem; }

    /* ── Code context / next session block ── */
    .context-block {
      background: var(--surface2); border-left: 2px solid var(--blue);
      border-radius: 0 6px 6px 0; padding: .75rem 1rem;
      font-size: .82rem; line-height: 1.6;
    }
    .context-block strong { color: var(--blue); }
    .context-block p { color: var(--text); margin-bottom: .2rem; }

    /* ── Search ── */
    /* ── Search (command palette) ── */
    .search-trigger {
      flex: 1; max-width: 340px; display: flex; align-items: center; gap: .5rem;
      background: var(--surface2); border: 1px solid var(--border);
      border-radius: 20px; padding: .35rem .75rem .35rem .9rem;
      color: var(--subtle); font-size: .82rem; cursor: pointer;
      transition: border-color .15s, color .15s;
    }
    .search-trigger:hover { border-color: var(--blue); color: var(--text); }
    .search-trigger-icon { font-size: .85rem; flex-shrink: 0; }
    .search-trigger-label { flex: 1; }
    .search-trigger-kbd {
      font-size: .68rem; background: var(--surface); border: 1px solid var(--border);
      border-radius: 4px; padding: .1em .4em; color: var(--muted); font-family: inherit;
    }
    .search-modal {
      position: fixed; inset: 0; z-index: 9000;
      background: rgba(0,0,0,.55); backdrop-filter: blur(3px);
      display: flex; align-items: flex-start; justify-content: center;
      padding-top: 12vh;
    }
    .search-palette {
      width: 680px; max-width: calc(100vw - 2rem);
      max-height: 70vh; display: flex; flex-direction: column;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,.5);
      overflow: hidden;
    }
    .search-palette-header {
      display: flex; align-items: center; gap: .6rem;
      padding: .75rem 1rem; border-bottom: 1px solid var(--border);
    }
    .search-palette-icon { color: var(--subtle); font-size: 1rem; flex-shrink: 0; }
    .search-palette-input {
      flex: 1; background: transparent; border: none; outline: none;
      color: var(--text); font-family: inherit; font-size: .95rem;
    }
    .search-palette-input::placeholder { color: var(--subtle); }
    .search-esc-hint {
      font-size: .68rem; background: var(--surface2); border: 1px solid var(--border);
      border-radius: 4px; padding: .1em .5em; color: var(--muted);
      cursor: pointer; flex-shrink: 0;
    }
    .search-esc-hint:hover { color: var(--text); }
    .search-filters {
      display: flex; gap: .4rem; padding: .5rem 1rem;
      border-bottom: 1px solid var(--border); flex-wrap: wrap;
    }
    .search-filter-pill {
      font-size: .72rem; padding: .2em .7em; border-radius: 20px;
      border: 1px solid var(--border); background: var(--surface2);
      color: var(--muted); cursor: pointer; transition: all .12s;
    }
    .search-filter-pill:hover { border-color: var(--blue); color: var(--text); }
    .search-filter-pill.active { background: var(--blue); border-color: var(--blue); color: #fff; }
    .search-results { flex: 1; overflow-y: auto; padding: .5rem 0; }
    .search-group { margin-bottom: .25rem; }
    .search-group-ns {
      position: sticky; top: 0; background: var(--surface);
      padding: .3rem 1rem; font-size: .72rem; font-weight: 700;
      letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
      border-bottom: 1px solid var(--surface2);
    }
    .search-result-item {
      display: flex; align-items: baseline; gap: .6rem;
      padding: .42rem 1rem; cursor: pointer; font-size: .82rem;
      transition: background .08s; border-left: 2px solid transparent;
    }
    .search-result-item:hover { background: var(--surface2); }
    .search-result-item.focused { background: var(--surface2); border-left-color: var(--blue); }
    .search-result-section {
      font-size: .62rem; font-weight: 700; letter-spacing: .06em;
      text-transform: uppercase; padding: .15em .5em; border-radius: 3px;
      flex-shrink: 0;
    }
    .sec-state     { background: var(--blue-bg);  color: var(--blue); }
    .sec-learnings { background: var(--green-bg); color: var(--green); }
    .sec-decisions { background: var(--amber-bg); color: var(--amber); }
    .sec-history   { background: var(--surface2); color: var(--muted); }
    .snippet { color: var(--muted); line-height: 1.5; flex: 1; }
    mark { background: var(--amber-bg); color: var(--amber); border-radius: 2px; padding: 0 .1em; font-style: normal; }
    .search-more { font-size: .72rem; color: var(--subtle); font-style: italic; padding: .2rem 1rem; }
    .search-empty { padding: 2rem; text-align: center; color: var(--subtle); font-size: .85rem; }
    .search-footer {
      display: flex; gap: 1.2rem; padding: .45rem 1rem; align-items: center;
      border-top: 1px solid var(--border); font-size: .72rem; color: var(--subtle);
    }

    @keyframes flashHighlight {
      0%   { background: var(--amber-bg); box-shadow: 0 0 0 2px var(--amber); }
      65%  { background: var(--amber-bg); box-shadow: 0 0 0 2px var(--amber); }
      100% { background: transparent; box-shadow: none; }
    }
    .highlight-flash { animation: flashHighlight 1.8s ease-out forwards; border-radius: 4px; }

    /* ── DAG view ── */
    .dag-toolbar {
      display: flex; align-items: center; gap: .6rem; margin-bottom: .75rem; flex-wrap: wrap;
    }
    .dag-title { font-weight: 700; font-size: .9rem; }
    .dag-hint { font-size: .72rem; color: var(--muted); flex: 1; min-width: 120px; }
    .dag-btn {
      font-size: .72rem; font-family: inherit; background: var(--surface2);
      border: 1px solid var(--border); color: var(--muted);
      padding: .3rem .7rem; border-radius: var(--radius); cursor: pointer; white-space: nowrap;
    }
    .dag-btn:hover { color: var(--text); border-color: var(--blue); }
    .dag-btn.active { background: var(--blue-bg); border-color: var(--blue); color: var(--blue); }
    .dag-wrap { display: flex; gap: 1rem; align-items: flex-start; }
    .dag-svg {
      flex: 1; background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); display: block; min-height: 320px; max-height: 560px;
    }
    .dag-legend {
      width: 190px; flex-shrink: 0; background: var(--surface);
      border: 1px solid var(--border); border-radius: var(--radius); padding: .75rem;
    }
    .dag-legend-title {
      font-size: .62rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: .07em; color: var(--muted); margin-bottom: .45rem;
    }
    .dag-legend-item {
      display: flex; align-items: center; gap: .5rem;
      font-size: .72rem; color: var(--text); margin-bottom: .42rem;
    }
    .dag-tooltip {
      position: fixed; z-index: 8000; pointer-events: none;
      background: var(--surface2); border: 1px solid var(--border);
      border-radius: 6px; padding: .5rem .75rem; max-width: 300px;
      box-shadow: 0 4px 16px rgba(0,0,0,.45);
    }
    .dag-tip-header {
      font-size: .78rem; color: var(--text); margin-bottom: .3rem;
      display: flex; align-items: baseline; gap: .4rem; flex-wrap: wrap; line-height: 1.4;
    }
    .dag-tip-type {
      font-size: .62rem; font-weight: 700; padding: .1em .45em;
      border-radius: 3px; flex-shrink: 0;
    }
    .dag-tip-dep        { background: var(--amber-bg); color: var(--amber); }
    .dag-tip-shared     { background: var(--blue-bg);  color: var(--blue); }
    .dag-tip-conflict   { background: var(--red-bg);   color: var(--red); }
    .dag-tip-concurrent { background: var(--green-bg); color: var(--green); }
    .dag-tip-detail { font-size: .72rem; color: var(--muted); line-height: 1.5; }
  </style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="header-left">
      <h1>&#x1f9ed; Compass</h1>
      <span class="since">Generated [[GENERATED_AT]]</span>
    </div>
    <div class="search-trigger" onclick="openSearch()" title="Search (⌘K)">
      <span class="search-trigger-icon">&#x2315;</span>
      <span class="search-trigger-label">Search…</span>
      <kbd class="search-trigger-kbd">⌘K</kbd>
    </div>
    <div class="header-stats">
      <div class="hstat"><span class="hstat-val">[[N_NS]]</span><span class="hstat-lbl">namespaces</span></div>
      <div class="hstat"><span class="hstat-val">[[N_OPEN]]</span><span class="hstat-lbl">open</span></div>
      <div class="hstat"><span class="hstat-val">[[N_LEARNINGS]]</span><span class="hstat-lbl">learnings</span></div>
      <div class="hstat"><span class="hstat-val">[[N_SESSIONS]]</span><span class="hstat-lbl">sessions</span></div>
    </div>
  </div>
</header>

<main>
  <nav class="view-nav">
    <button class="view-tab active" id="vtab-overview"   onclick="switchView('overview')">Overview</button>
    <button class="view-tab"        id="vtab-priorities" onclick="switchView('priorities')">Priorities</button>
    <button class="view-tab"        id="vtab-dag"        onclick="switchView('dag')">DAG</button>
  </nav>

  <div id="view-overview">
    <div class="grid">[[CARDS]]</div>
    <div class="detail" id="detail">
      <div class="no-selection">
        <span class="arrow">&#x2191;</span>
        Select a namespace to view details
      </div>
    </div>
  </div>

  <div id="view-priorities" style="display:none"></div>
  <div id="view-dag"        style="display:none"></div>

  </div>
</main>
<div id="search-modal" class="search-modal" style="display:none" onclick="closeSearchIfBackdrop(event)">
  <div class="search-palette">
    <div class="search-palette-header">
      <span class="search-palette-icon">&#x2315;</span>
      <input class="search-palette-input" id="search-palette-input" type="search"
             placeholder="Search namespaces, learnings, decisions, history…"
             oninput="handleSearch(this.value)" onkeydown="handleSearchKey(event)">
      <kbd class="search-esc-hint" onclick="closeSearch()">esc</kbd>
    </div>
    <div class="search-filters" id="search-filters"></div>
    <div class="search-results" id="search-results">
      <div class="search-empty">Type to search…</div>
    </div>
    <div class="search-footer">
      <span>↑↓ navigate</span><span>↵ open</span><span>esc close</span>
      <span style="margin-left:auto">⌘K</span>
    </div>
  </div>
</div>

<script>
const NS = [[DATA_JSON]];
let selected = -1;

// ── Markdown renderer (headings, lists, bold, inline code) ───────────────────

function md(text) {
  if (!text) return '<span class="empty-state">—</span>';
  const lines = text.split('\\n');
  let html = '';
  let inList = false;

  const flush = () => { if (inList) { html += '</ul>'; inList = false; } };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line) { flush(); continue; }
    if (line.startsWith('## ')) {
      flush(); html += `<h3>${mdInline(line.slice(3))}</h3>`;
    } else if (line.startsWith('### ')) {
      flush(); html += `<h4>${mdInline(line.slice(4))}</h4>`;
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${mdInline(line.slice(2))}</li>`;
    } else {
      flush(); html += `<p>${mdInline(line)}</p>`;
    }
  }
  flush();
  return html || '<span class="empty-state">—</span>';
}

function mdInline(s) {
  return esc(s)
    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code style="background:var(--surface2);padding:.1em .3em;border-radius:3px">$1</code>');
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Card selection ────────────────────────────────────────────────────────────

function selectCard(i) {
  if (selected === i) {
    document.getElementById(`card-${i}`).classList.remove('selected');
    document.getElementById('detail').classList.remove('visible');
    selected = -1;
    return;
  }
  if (selected >= 0) {
    document.getElementById(`card-${selected}`)?.classList.remove('selected');
  }
  selected = i;
  document.getElementById(`card-${i}`).classList.add('selected');
  renderDetail(NS[i]);
  const detail = document.getElementById('detail');
  detail.classList.add('visible');
  requestAnimationFrame(() => detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function renderDetail(ns) {
  const tabs = (ns.decisions && ns.decisions.length)
    ? ['state', 'learnings', 'decisions', 'history']
    : ['state', 'learnings', 'history'];
  const labels = {
    state:     'State',
    learnings: `Learnings (${ns.learnings.length})`,
    decisions: `Decisions (${(ns.decisions || []).length})`,
    history:   `History (${ns.sessionCount})`,
  };

  const btnHtml = tabs.map(t =>
    `<button class="tab-btn${t === 'state' ? ' active' : ''}" onclick="switchTab('${t}')" id="tab-btn-${t}">${labels[t]}</button>`
  ).join('');

  const panelHtml = tabs.map(t =>
    `<div class="tab-content${t === 'state' ? ' active' : ''}" id="tab-${t}">${renderTab(t, ns)}</div>`
  ).join('');

  const statusCls   = ns.open ? 'open' : 'closed';
  const statusLabel = ns.open ? 'OPEN' : 'CLOSED';
  const timeHtml    = ns.open
    ? `<span style="font-size:.75rem;color:var(--muted)">opened&nbsp;${esc(ns.lastOpen)}</span>`
    : `<span style="font-size:.75rem;color:var(--muted)">closed&nbsp;${esc(ns.lastClose)}</span>`;

  document.getElementById('detail').innerHTML = `
    <div class="detail-header">
      <span class="detail-ns">${esc(ns.namespace)}</span>
      <span class="badge ${statusCls}">${statusLabel}</span>
      ${timeHtml}
    </div>
    <div class="tabs">${btnHtml}</div>
    ${panelHtml}
  `;
}

function switchTab(t) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById(`tab-btn-${t}`).classList.add('active');
  document.getElementById(`tab-${t}`).classList.add('active');
}

// ── Tab renderers ─────────────────────────────────────────────────────────────

function renderTab(tab, ns) {
  if (tab === 'state')     return renderState(ns);
  if (tab === 'learnings') return renderLearnings(ns);
  if (tab === 'decisions') return renderDecisions(ns);
  if (tab === 'history')   return renderHistory(ns);
  return '';
}

function renderState(ns) {
  let html = '';

  // Intent
  html += `<div class="md-section"><h3>Intent</h3><div>${md(ns.intent)}</div></div>`;

  // Active goals (open sessions only)
  if (ns.open && ns.plannedActions.length > 0) {
    const items = ns.plannedActions.map(a => `<li>${esc(a)}</li>`).join('');
    html += `<div class="md-section"><h3>Active goals</h3><ul class="goals-list">${items}</ul></div>`;
  }

  // Next session entry point (code_context.md)
  if (ns.codeContext) {
    html += `<div class="md-section"><h3>Next session entry point</h3>
      <div class="context-block">${md(ns.codeContext)}</div>
    </div>`;
  }

  // Reality
  html += `<div class="md-section"><h3>Reality</h3><div>${md(ns.reality)}</div></div>`;

  // Recent decisions (last 3, inline summary — full log in Decisions tab)
  if (ns.decisions && ns.decisions.length > 0) {
    const recent = [...ns.decisions].reverse().slice(0, 3);
    const items = recent.map(d => {
      const rat = d.rationale ? ` <span style="color:var(--muted);font-size:.75rem">— ${esc(d.rationale)}</span>` : '';
      return `<li>${esc(d.decision || d.text || '')}${rat}</li>`;
    }).join('');
    html += `<div class="md-section"><h3>Recent decisions</h3><ul>${items}</ul></div>`;
  }

  // Deferred opportunities
  if (ns.deferred.length > 0) {
    const items = ns.deferred.map(d => {
      const text = d.text || d.opportunity_text || d.key;
      const cnt  = d.defer_count || 1;
      return `<li><span class="defer-count">×${cnt}</span>${esc(text)}</li>`;
    }).join('');
    html += `<div class="md-section"><h3>Deferred opportunities</h3><ul class="deferred-list">${items}</ul></div>`;
  }

  return html;
}

function renderLearnings(ns) {
  if (!ns.learnings.length) {
    return '<div class="empty-state">No learnings recorded yet.</div>';
  }

  const rows = ns.learnings.map((l, lIdx) => {
    const w    = l.weight || 1;
    const wCls = w >= 4 ? 'w-high' : w >= 2 ? 'w-mid' : 'w-low';
    const tags = (l.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const type = l.learning_type === 'hypothesis' ? 'hypothesis' : 'fact';
    const date = (l.logged_at || '').slice(0, 10) || '—';
    const conf = l.confidence ? ` <span style="color:var(--subtle);font-size:.68rem">${esc(l.confidence)}</span>` : '';
    return `
      <tr data-idx="${lIdx}">
        <td><span class="weight-dot"><span class="wdot ${wCls}"></span><span class="wnum">${w}</span></span></td>
        <td class="learning-text">${esc(l.text || '')}</td>
        <td><div class="tags-cell">${tags}</div></td>
        <td><span class="type-badge type-${type}">${type}</span>${conf}</td>
        <td style="color:var(--subtle);white-space:nowrap;font-size:.75rem">${date}</td>
      </tr>`;
  }).join('');

  return `
    <table class="learnings-table">
      <thead>
        <tr><th>Wt</th><th>Learning</th><th>Tags</th><th>Type</th><th>Date</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Decisions ─────────────────────────────────────────────────────────────────

function renderDecisions(ns) {
  if (!ns.decisions || !ns.decisions.length) {
    return '<div class="empty-state">No decisions logged for this namespace yet.<br>Use <code>compass log-decision</code> mid-session to capture them.</div>';
  }
  const items = [...ns.decisions].reverse().map((d, dIdx) => {
    const date = (d.timestamp || d.logged_at || '').slice(0, 10) || '—';
    const ratHtml = d.rationale
      ? `<div class="decision-rationale">${esc(d.rationale)}</div>` : '';
    const altHtml = d.alternatives
      ? `<div class="decision-alts">Alternatives considered: ${esc(d.alternatives)}</div>` : '';
    return `
      <div class="decision-item" data-idx="${dIdx}">
        <div class="decision-text">${esc(d.decision || d.text || '')}</div>
        <div class="decision-meta">
          ${ratHtml}
          <div class="decision-date">${date}</div>
        </div>
        ${altHtml}
      </div>`;
  }).join('');
  return `<div class="decision-list">${items}</div>`;
}

// ── History timeline ──────────────────────────────────────────────────────────

function renderHistory(ns) {
  if (!ns.history.length) {
    return '<div class="empty-state">No session history recorded yet.</div>';
  }

  const sessions = ns.history.map((s, i) => {
    const dateLabel = (s.filename || '').replace('.md', '').replace('T', ' ');
    const nDone = s.completed.length;
    const nSkip = s.incomplete.length;

    const doneHtml = s.completed.length
      ? `<div class="session-section">
           <div class="session-label">Completed</div>
           <ul class="session-items">${s.completed.map(c => `<li class="done">${esc(c)}</li>`).join('')}</ul>
         </div>` : '';

    const skipHtml = s.incomplete.length
      ? `<div class="session-section">
           <div class="session-label">Incomplete</div>
           <ul class="session-items">${s.incomplete.map(c => `<li class="undone">${esc(c)}</li>`).join('')}</ul>
         </div>` : '';

    const learnHtml = (s.learnings_extracted || []).length
      ? `<div class="session-section">
           <div class="session-label">Learnings</div>
           <ul class="session-items">${s.learnings_extracted.map(l => `<li class="plain">${esc(l)}</li>`).join('')}</ul>
         </div>` : '';

    const noteHtml = s.notes
      ? `<div class="session-note">${esc(s.notes.trim())}</div>` : '';

    return `
      <div class="session-card" id="scard-${i}">
        <div class="session-header" onclick="toggleSession(${i})">
          <span class="session-date">${esc(dateLabel)}</span>
          <span class="session-meta">${nDone} done &middot; ${nSkip} skipped</span>
          <span class="session-chevron">&rsaquo;</span>
        </div>
        <div class="session-body" id="sbody-${i}">
          ${doneHtml}${skipHtml}${learnHtml}${noteHtml}
        </div>
      </div>`;
  }).join('');

  return `<div class="timeline">${sessions}</div>`;
}

function toggleSession(i) {
  const card = document.getElementById(`scard-${i}`);
  const body = document.getElementById(`sbody-${i}`);
  card.classList.toggle('expanded');
  body.classList.toggle('open');
}

// ── Top-level view switching ──────────────────────────────────────────────────

function switchView(v) {
  if (v !== 'dag' && _dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }
  ['overview', 'priorities', 'dag'].forEach(id => {
    document.getElementById('view-' + id).style.display = id === v ? '' : 'none';
    document.getElementById('vtab-' + id).classList.toggle('active', id === v);
  });
  if (v === 'priorities') renderPriorities();
  if (v === 'dag') renderDAG();
}

// ── Priority scoring ──────────────────────────────────────────────────────────

// Namespaces managed by tooling/the compass skill itself — excluded from priority ranking
const SYSTEM_NS = new Set(['global', 'compass']);

function _daysSince(timeAgoStr) {
  if (!timeAgoStr || timeAgoStr === 'never') return 999;
  const m = timeAgoStr.match(/^(\\d+)([dhm])/);
  if (!m) return 0;
  const n = parseInt(m[1]);
  if (m[2] === 'd') return n;
  if (m[2] === 'h') return n / 24;
  return 0;
}

function computePriorities() {
  return NS.filter(ns => !SYSTEM_NS.has(ns.namespace.toLowerCase())).map((ns, idx) => {
    // Remap idx to the original NS array position so selectCard() works correctly
    idx = NS.indexOf(ns);
    let score = 0;
    const reasons = [];

    if (ns.open) {
      score += 30;
      reasons.push({ icon: '●', text: 'Session currently in progress' });
    }

    const lastActivity = ns.open ? ns.lastOpen : ns.lastClose;
    const days = _daysSince(lastActivity);
    if (days > 14) {
      score += 25;
      reasons.push({ icon: '⚠', text: `Stale — ${Math.round(days)}d since last session` });
    } else if (days > 7) {
      score += 15;
      reasons.push({ icon: '↩', text: `${Math.round(days)}d since last session` });
    }

    if (ns.goalRate !== null && ns.goalRate !== undefined) {
      if (ns.goalRate < 50) {
        score += 20;
        reasons.push({ icon: '↓', text: `Low completion rate (${ns.goalRate}%)` });
      } else if (ns.goalRate < 75) {
        score += 10;
        reasons.push({ icon: '~', text: `Moderate completion rate (${ns.goalRate}%)` });
      }
    }

    const deferredCount = (ns.deferred || []).length;
    if (deferredCount > 0) {
      score += deferredCount * 4;
      reasons.push({ icon: '⏸', text: `${deferredCount} deferred item${deferredCount !== 1 ? 's' : ''} queued` });
    }

    if (ns.plannedActions && ns.plannedActions.length > 0) {
      score += 8;
      reasons.push({ icon: '→', text: `${ns.plannedActions.length} planned action${ns.plannedActions.length !== 1 ? 's' : ''} waiting` });
    }

    const highWeight = (ns.learnings || []).filter(l => (l.weight || 1) >= 4);
    if (highWeight.length > 0) {
      score += Math.min(highWeight.length * 2, 10);
      reasons.push({ icon: '★', text: `${highWeight.length} high-weight learning${highWeight.length !== 1 ? 's' : ''} — active area` });
    }

    if (ns.sessionCount === 0) {
      score += 10;
      reasons.push({ icon: '+', text: 'No sessions yet — namespace needs bootstrapping' });
    }

    return { ns, idx, score, reasons };
  })
  .sort((a, b) => b.score - a.score)
  .slice(0, 4);
}

// ── Cross-compass signal detection ────────────────────────────────────────────

function detectSignals(ns) {
  const signals = [];
  const nsTagSet = new Set(ns.topTags || []);
  const nsNameLower = ns.namespace.toLowerCase();
  const nsHWTags = new Set(
    (ns.learnings || []).filter(l => (l.weight || 1) >= 4).flatMap(l => l.tags || [])
  );
  const nsReality = (ns.reality || '').toLowerCase();
  const nsPlanned = (ns.plannedActions || []).join(' ').toLowerCase();

  const seen = new Set();
  const add = s => {
    if (!seen.has(s.detail)) { seen.add(s.detail); signals.push(s); }
  };

  NS.forEach(other => {
    if (other.namespace === ns.namespace) return;
    if (SYSTEM_NS.has(other.namespace.toLowerCase())) return;
    const otherLower = other.namespace.toLowerCase();

    // Both sessions open — context-switch cost
    if (ns.open && other.open) {
      add({ type: 'concurrent', icon: '⚡',
            detail: `"${other.namespace}" also has an open session — context-switch cost if you switch` });
    }

    // Planned work explicitly references another namespace
    if (nsPlanned.includes(otherLower)) {
      add({ type: 'dep', icon: '→',
            detail: `Planned work references "${other.namespace}" — may depend on it or block it` });
    }

    // Reality doc references another namespace
    if (nsReality.includes(otherLower)) {
      add({ type: 'dep', icon: '⤷',
            detail: `Reality doc mentions "${other.namespace}" — verify dependency is current` });
    }

    // Overlapping top tags (≥2 shared)
    const sharedTags = (other.topTags || []).filter(t => nsTagSet.has(t));
    if (sharedTags.length >= 2) {
      add({ type: 'shared', icon: '⊕',
            detail: `Overlaps with "${other.namespace}" on: ${sharedTags.slice(0, 3).join(', ')}` });
    }

    // High-weight learnings share tags — work in one may require rework in the other
    const conflictTags = (other.learnings || [])
      .filter(l => (l.weight || 1) >= 4)
      .flatMap(l => l.tags || [])
      .filter(t => nsHWTags.has(t));
    if (conflictTags.length > 0) {
      const uniq = [...new Set(conflictTags)].slice(0, 2);
      add({ type: 'conflict', icon: '⚠',
            detail: `High-weight learnings in "${other.namespace}" share themes (${uniq.join(', ')}) — changes here may require rework there` });
    }
  });

  return signals.slice(0, 5);
}

// ── Recommended action ────────────────────────────────────────────────────────

function recommendedAction(ns) {
  if (ns.open) return 'Close this loop — session in progress';
  if (ns.sessionCount === 0) return 'Open first session to bootstrap this namespace';
  if ((ns.deferred || []).length >= 3) return 'Review deferred items, then open a new session';
  if (ns.goalRate !== null && ns.goalRate !== undefined && ns.goalRate < 50)
    return 'Open a session — completion rate needs attention';
  if (_daysSince(ns.lastClose) > 14) return 'Open a session — this namespace has gone quiet';
  return 'Open a new session to progress planned work';
}

// ── Priorities view renderer ──────────────────────────────────────────────────

function renderPriorities() {
  const top4 = computePriorities();

  if (!top4.length) {
    document.getElementById('view-priorities').innerHTML =
      '<div class="empty-state" style="padding:2rem;text-align:center">No namespaces to rank.</div>';
    return;
  }

  const cards = top4.map(({ ns, idx, score, reasons }, rank) => {
    const signals = detectSignals(ns);
    const rankN = rank + 1;

    const reasonsHtml = reasons.slice(0, 5).map(r =>
      `<li class="p-reason"><span class="p-reason-icon">${esc(r.icon)}</span>${esc(r.text)}</li>`
    ).join('');

    const signalsHtml = signals.length
      ? signals.map(s =>
          `<div class="p-signal sig-${s.type}">
             <span class="p-signal-icon">${esc(s.icon)}</span>
             <span>${esc(s.detail)}</span>
           </div>`
        ).join('')
      : '<div class="p-no-signals">No cross-compass dependencies detected</div>';

    const statusCls   = ns.open ? 'open' : 'closed';
    const statusLabel = ns.open ? 'OPEN' : 'CLOSED';
    const summary     = (ns.intentSummary || '').slice(0, 110) + (ns.intentSummary && ns.intentSummary.length > 110 ? '…' : '');

    return `
      <div class="priority-card rank-${rankN}" onclick="selectCard(${idx}); switchView('overview')" style="cursor:pointer" title="Click to open in Overview">
        <div class="p-header">
          <span class="p-rank">#${rankN}</span>
          <span class="p-ns">${esc(ns.namespace)}</span>
          <span class="badge ${statusCls}">${statusLabel}</span>
        </div>
        ${summary ? `<div class="p-intent">${esc(summary)}</div>` : ''}
        <div class="p-action">${esc(recommendedAction(ns))}</div>
        ${reasonsHtml ? `<div>
          <div class="p-section-label">Why prioritised</div>
          <ul class="p-reasons">${reasonsHtml}</ul>
        </div>` : ''}
        <div>
          <div class="p-section-label">Cross-compass signals</div>
          <div class="p-signals">${signalsHtml}</div>
        </div>
        <div class="p-score">Priority score: ${score}</div>
      </div>`;
  }).join('');

  document.getElementById('view-priorities').innerHTML = `<div class="priority-grid">${cards}</div>`;
}

// ── Search (command palette) ────────────────────────────────────────────────────────────────────────────────

let SEARCH_INDEX = null;
let _activeFilter = 'all';
let _focusIdx     = -1;
let _flatResults  = [];

function forceSelectCard(i) {
  if (selected >= 0 && selected !== i) {
    document.getElementById('card-' + selected)?.classList.remove('selected');
  }
  selected = i;
  document.getElementById('card-' + i)?.classList.add('selected');
  renderDetail(NS[i]);
  const detail = document.getElementById('detail');
  detail.classList.add('visible');
  requestAnimationFrame(() =>
    detail.scrollIntoView({behavior: 'smooth', block: 'nearest'})
  );
}

function openSearch() {
  document.getElementById('search-modal').style.display = '';
  const inp = document.getElementById('search-palette-input');
  inp.focus();
  inp.select();
  renderFilterPills();
  if (inp.value.trim()) doSearch(inp.value.trim().toLowerCase(), _activeFilter);
}

function closeSearch() {
  document.getElementById('search-modal').style.display = 'none';
  _focusIdx = -1;
  _flatResults = [];
}

function closeSearchIfBackdrop(e) {
  if (e.target === document.getElementById('search-modal')) closeSearch();
}

function buildSearchIndex() {
  const idx = [];
  NS.forEach((ns, nsIdx) => {
    if (ns.intent)
      idx.push({nsIdx, section:'state', field:'intent',
                text: ns.intent, displayText: ns.intentSummary || ns.intent, bonus: 2});
    if (ns.reality)
      idx.push({nsIdx, section:'state', field:'reality',
                text: ns.reality, displayText: ns.reality.slice(0, 200), bonus: 2});
    if (ns.codeContext)
      idx.push({nsIdx, section:'state', field:'context',
                text: ns.codeContext, displayText: ns.codeContext.slice(0, 200), bonus: 2});
    (ns.learnings || []).forEach((l, i) =>
      idx.push({nsIdx, section:'learnings', subIdx: i,
                text: l.text || '', displayText: l.text || '',
                bonus: Math.min((l.weight || 1) * 2, 8)})
    );
    [...(ns.decisions || [])].reverse().forEach((d, i) => {
      const combined = [d.decision||d.text||'', d.rationale||'', d.alternatives||''].join(' ');
      idx.push({nsIdx, section:'decisions', subIdx: i,
                text: combined, displayText: d.decision||d.text||'', bonus: 3});
    });
    (ns.history || []).forEach((s, si) => {
      const parts = [...(s.completed||[]), ...(s.incomplete||[]),
                     ...(s.learnings_extracted||[]), s.notes||''].filter(Boolean);
      if (parts.length)
        idx.push({nsIdx, section:'history', subIdx: si,
                  text: parts.join(' '), displayText: parts[0]||'', bonus: 0});
    });
  });
  return idx;
}

function scoreItem(item, q) {
  const t  = (item.text        || '').toLowerCase();
  const dt = (item.displayText || '').toLowerCase();
  let s = 0;
  if      (t === q || dt === q)                            s = 100;
  else if (t.startsWith(q) || dt.startsWith(q))           s = 80;
  else if (t.includes(' ' + q) || dt.includes(' ' + q))   s = 60;
  else if (t.includes(q))                                  s = 40;
  else return 0;
  return s + (item.bonus || 0);
}

function handleSearch(val) {
  const q = val.trim().toLowerCase();
  if (!q) {
    document.getElementById('search-results').innerHTML =
      '<div class="search-empty">Type to search\u2026</div>';
    _flatResults = []; _focusIdx = -1;
    return;
  }
  if (!SEARCH_INDEX) SEARCH_INDEX = buildSearchIndex();
  doSearch(q, _activeFilter);
}

function handleSearchKey(e) {
  if (e.key === 'Escape') { closeSearch(); return; }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _focusIdx = Math.min(_focusIdx + 1, _flatResults.length - 1);
    updateFocus(); return;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    _focusIdx = Math.max(_focusIdx - 1, 0);
    updateFocus(); return;
  }
  if (e.key === 'Enter' && _focusIdx >= 0 && _flatResults[_focusIdx]) {
    const r = _flatResults[_focusIdx];
    handleResultClick(r.nsIdx, r.section,
      r.subIdx !== undefined ? r.subIdx : -1, r.field || '');
  }
}

function updateFocus() {
  document.querySelectorAll('#search-results .search-result-item').forEach((el, i) => {
    el.classList.toggle('focused', i === _focusIdx);
    if (i === _focusIdx) el.scrollIntoView({block: 'nearest'});
  });
}

function setFilter(filter) {
  _activeFilter = filter;
  _focusIdx = -1;
  renderFilterPills();
  const q = document.getElementById('search-palette-input').value.trim().toLowerCase();
  if (q) doSearch(q, filter);
}

function renderFilterPills() {
  const filters = ['all', 'state', 'learnings', 'decisions', 'history'];
  const labels  = {all: 'All', state: 'State', learnings: 'Learnings',
                   decisions: 'Decisions', history: 'History'};
  document.getElementById('search-filters').innerHTML = filters.map(f =>
    `<button class="search-filter-pill${f === _activeFilter ? ' active' : ''}" onclick="setFilter('${f}')">${labels[f]}</button>`
  ).join('');
}

function doSearch(query, filter) {
  const SECT_ORDER = ['state', 'learnings', 'decisions', 'history'];
  const SECT_LABEL = {state: 'State', learnings: 'Learnings',
                      decisions: 'Decisions', history: 'History'};
  const SECT_CLS   = {state: 'state', learnings: 'learnings',
                      decisions: 'decisions', history: 'history'};

  const hits = SEARCH_INDEX
    .filter(item => filter === 'all' || item.section === filter)
    .map(item => ({item, score: scoreItem(item, query)}))
    .filter(({score}) => score > 0)
    .sort((a, b) => b.score - a.score);

  const groups = {};
  hits.forEach(({item}) => {
    if (!groups[item.nsIdx]) groups[item.nsIdx] = {nsIdx: item.nsIdx, sections: {}};
    if (!groups[item.nsIdx].sections[item.section])
      groups[item.nsIdx].sections[item.section] = new Map();
    const key = item.subIdx !== undefined ? String(item.subIdx) : (item.field || 'x');
    if (!groups[item.nsIdx].sections[item.section].has(key))
      groups[item.nsIdx].sections[item.section].set(key, item);
  });

  const totalHits = Object.values(groups).reduce((a, g) =>
    a + Object.values(g.sections).reduce((b, s) => b + s.size, 0), 0);

  if (!totalHits) {
    document.getElementById('search-results').innerHTML =
      '<div class="search-empty">No matches for &ldquo;' + esc(query) + '&rdquo;</div>';
    _flatResults = []; _focusIdx = -1;
    return;
  }

  _flatResults = [];
  let html = '';

  Object.values(groups).sort((a, b) => a.nsIdx - b.nsIdx).forEach(g => {
    const ns = NS[g.nsIdx];
    html += '<div class="search-group">';
    html += `<div class="search-group-ns">${esc(ns.namespace)}</div>`;
    SECT_ORDER.forEach(sec => {
      const secMap = g.sections[sec];
      if (!secMap || !secMap.size) return;
      const items = [...secMap.values()];
      items.slice(0, 6).forEach(item => {
        _flatResults.push(item);
        const subI = item.subIdx !== undefined ? item.subIdx : -1;
        const fld  = item.field || '';
        html += `<div class="search-result-item" onclick="handleResultClick(${item.nsIdx},'${sec}',${subI},'${fld}')">` +
                `<span class="search-result-section sec-${SECT_CLS[sec]}">${SECT_LABEL[sec]}</span>` +
                makeSnippet(item.displayText || item.text, query) + '</div>';
      });
      if (items.length > 6)
        html += '<div class="search-more">+' + (items.length - 6) + ' more</div>';
    });
    html += '</div>';
  });

  document.getElementById('search-results').innerHTML = html;
  _focusIdx = -1;
}

function makeSnippet(text, query) {
  if (!text) return '<span class="snippet">\u2014</span>';
  const idx = text.toLowerCase().indexOf(query);
  if (idx === -1)
    return '<span class="snippet">' + esc(text.slice(0, 120)) +
           (text.length > 120 ? '\u2026' : '') + '</span>';
  const s = Math.max(0, idx - 45);
  const e = Math.min(text.length, idx + query.length + 70);
  return '<span class="snippet">' +
    (s > 0 ? '\u2026' : '') +
    esc(text.slice(s, idx)) +
    '<mark>' + esc(text.slice(idx, idx + query.length)) + '</mark>' +
    esc(text.slice(idx + query.length, e)) +
    (e < text.length ? '\u2026' : '') + '</span>';
}

function handleResultClick(nsIdx, section, subIdx, field) {
  closeSearch();
  switchView('overview');
  navigateToResult(nsIdx, section, subIdx, field);
}

function navigateToResult(nsIdx, section, subIdx, field) {
  forceSelectCard(nsIdx);
  switchTab(section);

  requestAnimationFrame(() => {
    let target = null;
    if (section === 'state') {
      const headingMap = {intent: 'Intent', reality: 'Reality',
                          context: 'Next session entry point',
                          decisions: 'Recent decisions'};
      const want = headingMap[field] || 'Intent';
      document.querySelectorAll('#tab-state h3').forEach(h => {
        if (h.textContent.trim() === want)
          target = h.closest('.md-section') || h.parentElement;
      });
    } else if (section === 'learnings') {
      target = document.querySelector('#tab-learnings tr[data-idx="' + subIdx + '"]');
    } else if (section === 'decisions') {
      target = document.querySelector('#tab-decisions .decision-item[data-idx="' + subIdx + '"]');
    } else if (section === 'history') {
      target = document.getElementById('scard-' + subIdx);
      if (target) {
        const body = document.getElementById('sbody-' + subIdx);
        target.classList.add('expanded');
        if (body) body.classList.add('open');
      }
    }
    if (target) {
      target.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      target.classList.add('highlight-flash');
      setTimeout(() => target.classList.remove('highlight-flash'), 1800);
    }
  });
}

document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    openSearch();
  }
});
// ── Dependency Graph (DAG) ────────────────────────────────────────────────────

const EDGE_META = {
  dep:        { color: '#d29922', label: 'Dependency',    dash: '',    arrow: true,  title: 'directed' },
  shared:     { color: '#58a6ff', label: 'Shared themes', dash: '5,3', arrow: false, title: 'shared tag themes (≥2)' },
  conflict:   { color: '#f85149', label: 'Theme overlap', dash: '2,3', arrow: false, title: 'high-weight learning overlap' },
  concurrent: { color: '#3fb950', label: 'Concurrent',    dash: '',    arrow: false, title: 'both sessions open' },
};

const _dag = { nodes: [], edges: [], nodeMap: new Map(), raf: null, tick: 0, maxTick: 220, svgW: 900, svgH: 530 };
let _dagDrag = null;
let _dagShowSystem = false;

function _addEdge(map, s, t, type, detail) {
  const key = type === 'dep' ? `${s}->${t}:dep` : `${Math.min(s,t)}-${Math.max(s,t)}:${type}`;
  if (!map.has(key)) map.set(key, { source: s, target: t, type, details: [] });
  map.get(key).details.push(detail);
}

function computeAllEdges(includeSystem) {
  const map = new Map();
  const skip = ns => !includeSystem && SYSTEM_NS.has(ns.namespace.toLowerCase());
  NS.forEach((ns, i) => {
    if (skip(ns)) return;
    const nsHWTags = new Set((ns.learnings || []).filter(l => (l.weight||1) >= 4).flatMap(l => l.tags||[]));
    const nsTagSet = new Set(ns.topTags || []);
    const reality  = (ns.reality || '').toLowerCase();
    const planned  = (ns.plannedActions || []).join(' ').toLowerCase();
    NS.forEach((other, j) => {
      if (i === j || skip(other)) return;
      const ol = other.namespace.toLowerCase();
      if (planned.includes(ol))
        _addEdge(map, i, j, 'dep', '"' + ns.namespace + '" planned work references "' + other.namespace + '"');
      if (reality.includes(ol))
        _addEdge(map, i, j, 'dep', '"' + ns.namespace + '" reality mentions "' + other.namespace + '"');
      if (i < j) {
        const shared = (other.topTags||[]).filter(t => nsTagSet.has(t));
        if (shared.length >= 2)
          _addEdge(map, i, j, 'shared', 'Shared themes: ' + shared.slice(0,3).join(', '));
        const conflict = (other.learnings||[]).filter(l => (l.weight||1) >= 4)
          .flatMap(l => l.tags||[]).filter(t => nsHWTags.has(t));
        if (conflict.length)
          _addEdge(map, i, j, 'conflict', 'High-weight learning overlap: ' + [...new Set(conflict)].slice(0,2).join(', '));
        if (ns.open && other.open)
          _addEdge(map, i, j, 'concurrent', 'Both sessions open simultaneously');
      }
    });
  });
  return [...map.values()];
}

function buildDAGLegend(edges) {
  const types = new Set(edges.map(e => e.type));
  const edgeRows = Object.entries(EDGE_META).filter(([t]) => types.has(t)).map(([type, m]) => {
    const dattr = m.dash ? ' stroke-dasharray="' + m.dash + '"' : '';
    const arrowSvg = m.arrow
      ? '<defs><marker id="lg-' + type + '" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto"><polygon points="0,0 6,2 0,4" fill="' + m.color + '"/></marker></defs>'
      : '';
    const mend = m.arrow ? ' marker-end="url(#lg-' + type + ')"' : '';
    return '<div class="dag-legend-item">'
      + '<svg width="26" height="2" style="overflow:visible;flex-shrink:0">'
      + arrowSvg
      + '<line x1="0" y1="1" x2="26" y2="1" stroke="' + m.color + '" stroke-width="2"' + dattr + mend + '/>'
      + '</svg><span>' + esc(m.label) + '</span></div>';
  }).join('');
  const nodeRows = ''
    + '<div class="dag-legend-item"><svg width="16" height="16" style="flex-shrink:0"><circle cx="8" cy="8" r="7" fill="rgba(63,185,80,.18)" stroke="#3fb950" stroke-width="2"/></svg><span>Open session</span></div>'
    + '<div class="dag-legend-item"><svg width="16" height="16" style="flex-shrink:0"><circle cx="8" cy="8" r="7" fill="rgba(33,38,45,.9)" stroke="#484f58" stroke-width="1"/></svg><span>Closed</span></div>'
    + '<div class="dag-legend-item"><svg width="16" height="16" style="flex-shrink:0"><circle cx="8" cy="8" r="5" fill="#3fb950"/></svg><span>Goal rate</span></div>';
  return '<div class="dag-legend-title">Relationships</div>'
    + (edgeRows || '<div style="font-size:.72rem;color:var(--subtle);font-style:italic">None detected</div>')
    + '<div style="margin-top:.6rem;border-top:1px solid var(--border);padding-top:.5rem">'
    + '<div class="dag-legend-title">Nodes</div>' + nodeRows + '</div>';
}

function dagPosTooltip(ev, tip) {
  if (!tip) return;
  const x = ev.clientX + 14, y = ev.clientY + 14;
  const tw = tip.offsetWidth || 260, th = tip.offsetHeight || 60;
  tip.style.left = (x + tw > window.innerWidth - 8  ? ev.clientX - tw - 14 : x) + 'px';
  tip.style.top  = (y + th > window.innerHeight - 8 ? ev.clientY - th - 14 : y) + 'px';
}

function renderDAG() {
  if (_dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }
  const container = document.getElementById('view-dag');
  const nodeData = NS.map((ns, i) => ({ ns, nsIdx: i, x: 0, y: 0, vx: 0, vy: 0, fixed: false }))
    .filter(n => _dagShowSystem || !SYSTEM_NS.has(n.ns.namespace.toLowerCase()));
  if (!nodeData.length) {
    container.innerHTML = '<div class="empty-state" style="padding:2rem;text-align:center">No namespaces to visualise.</div>';
    return;
  }
  const allEdges = computeAllEdges(_dagShowSystem)
    .filter(e => nodeData.some(n => n.nsIdx === e.source) && nodeData.some(n => n.nsIdx === e.target));
  const nodeMap = new Map(nodeData.map((n, i) => [n.nsIdx, i]));
  const W = _dag.svgW, H = _dag.svgH, cx = W/2, cy = H/2;
  const R0 = Math.min(W, H) * 0.32;
  nodeData.forEach((n, i) => {
    const a = (2 * Math.PI * i / nodeData.length) - Math.PI / 2;
    n.x = cx + R0 * Math.cos(a); n.y = cy + R0 * Math.sin(a);
  });
  Object.assign(_dag, { nodes: nodeData, edges: allEdges, nodeMap, tick: 0 });

  const sysLabel = _dagShowSystem ? 'Hide system NS' : 'Show system NS';
  const sysCls   = _dagShowSystem ? ' active' : '';
  container.innerHTML = ''
    + '<div class="dag-toolbar">'
    +   '<span class="dag-title">Dependency Graph</span>'
    +   '<span class="dag-hint">Drag nodes · hover edges for details · click node to navigate</span>'
    +   '<button class="dag-btn' + sysCls + '" id="dag-sys-btn" onclick="toggleDAGSystem()">&#x2699; ' + sysLabel + '</button>'
    +   '<button class="dag-btn" onclick="resetDAGLayout()">&#x21ba; Reset</button>'
    + '</div>'
    + '<div class="dag-wrap">'
    +   '<svg id="dag-svg" viewBox="0 0 ' + W + ' ' + H + '" class="dag-svg" preserveAspectRatio="xMidYMid meet"></svg>'
    +   '<div class="dag-legend">' + buildDAGLegend(allEdges) + '</div>'
    + '</div>'
    + '<div id="dag-tooltip" class="dag-tooltip" style="display:none"></div>';

  const svgEl = document.getElementById('dag-svg');
  const SVG   = 'http://www.w3.org/2000/svg';

  // Arrowhead markers in defs
  const defs = document.createElementNS(SVG, 'defs');
  Object.entries(EDGE_META).forEach(([type, m]) => {
    if (!m.arrow) return;
    const mk = document.createElementNS(SVG, 'marker');
    mk.setAttribute('id', 'arr-' + type); mk.setAttribute('markerWidth', '8'); mk.setAttribute('markerHeight', '6');
    mk.setAttribute('refX', '7'); mk.setAttribute('refY', '3'); mk.setAttribute('orient', 'auto');
    const poly = document.createElementNS(SVG, 'polygon');
    poly.setAttribute('points', '0,0 8,3 0,6'); poly.setAttribute('fill', m.color);
    mk.appendChild(poly); defs.appendChild(mk);
  });
  svgEl.appendChild(defs);

  // Edge lines
  const eg = document.createElementNS(SVG, 'g');
  allEdges.forEach((e, ei) => {
    const m = EDGE_META[e.type] || EDGE_META.shared;
    const ln = document.createElementNS(SVG, 'line');
    ln.setAttribute('id', 'dag-edge-' + ei);
    ln.setAttribute('stroke', m.color); ln.setAttribute('stroke-width', '1.5');
    ln.setAttribute('stroke-opacity', '0.65');
    if (m.dash) ln.setAttribute('stroke-dasharray', m.dash);
    if (m.arrow) ln.setAttribute('marker-end', 'url(#arr-' + e.type + ')');
    // Wider hover area via a transparent overlay
    const hit = document.createElementNS(SVG, 'line');
    hit.setAttribute('id', 'dag-hit-' + ei);
    hit.setAttribute('stroke', 'transparent'); hit.setAttribute('stroke-width', '10');
    const showTip = ev => {
      const tt = document.getElementById('dag-tooltip');
      if (!tt) return;
      const arrow = m.arrow ? ' → ' : ' ↔ ';
      const nsA = NS[e.source]?.namespace || '?', nsB = NS[e.target]?.namespace || '?';
      const dets = e.details.slice(0,4).map(d => '<div class="dag-tip-detail">• ' + esc(d) + '</div>').join('');
      tt.innerHTML = '<div class="dag-tip-header"><span class="dag-tip-type dag-tip-' + e.type + '">' + esc(m.label) + '</span>'
        + '<span style="color:var(--muted)">' + esc(nsA) + arrow + esc(nsB) + '</span></div>' + dets;
      tt.style.display = 'block'; dagPosTooltip(ev, tt);
    };
    const hideTip = () => { const tt = document.getElementById('dag-tooltip'); if (tt) tt.style.display = 'none'; };
    [ln, hit].forEach(el => {
      el.addEventListener('mouseenter', showTip);
      el.addEventListener('mousemove', ev => dagPosTooltip(ev, document.getElementById('dag-tooltip')));
      el.addEventListener('mouseleave', hideTip);
    });
    eg.appendChild(ln); eg.appendChild(hit);
  });
  svgEl.appendChild(eg);

  // Node groups
  const ng = document.createElementNS(SVG, 'g');
  nodeData.forEach((n, ni) => {
    const isSys = SYSTEM_NS.has(n.ns.namespace.toLowerCase());
    const g = document.createElementNS(SVG, 'g');
    g.setAttribute('id', 'dag-node-' + ni); g.style.cursor = 'pointer';

    const circ = document.createElementNS(SVG, 'circle');
    circ.setAttribute('r', '28');
    circ.setAttribute('fill', n.ns.open ? 'rgba(63,185,80,.18)' : isSys ? 'rgba(22,27,34,.95)' : 'rgba(33,38,45,.9)');
    circ.setAttribute('stroke', n.ns.open ? '#3fb950' : isSys ? '#58a6ff' : '#484f58');
    circ.setAttribute('stroke-width', n.ns.open ? '2' : isSys ? '1.5' : '1');
    if (isSys) circ.setAttribute('stroke-dasharray', '3,2');
    g.appendChild(circ);

    // Goal-rate dot (top-right)
    if (n.ns.goalRate !== null && n.ns.goalRate !== undefined) {
      const dot = document.createElementNS(SVG, 'circle');
      dot.setAttribute('r', '5'); dot.setAttribute('cx', '20'); dot.setAttribute('cy', '-20');
      dot.setAttribute('fill', n.ns.goalRate >= 80 ? '#3fb950' : n.ns.goalRate >= 50 ? '#d29922' : '#f85149');
      dot.setAttribute('stroke', '#0d1117'); dot.setAttribute('stroke-width', '1.5');
      g.appendChild(dot);
    }

    // Namespace name — split at hyphens for readability
    const nm   = n.ns.namespace;
    const segs = nm.split('-');
    const rows = segs.length >= 3
      ? [segs.slice(0, Math.ceil(segs.length/2)).join('-'), segs.slice(Math.ceil(segs.length/2)).join('-')]
      : [nm];
    rows.forEach((row, ri) => {
      const t = document.createElementNS(SVG, 'text');
      t.setAttribute('text-anchor', 'middle'); t.setAttribute('dominant-baseline', 'middle');
      t.setAttribute('font-size', rows.length > 1 ? '9' : '10.5');
      t.setAttribute('font-family', 'ui-monospace, monospace');
      t.setAttribute('fill', isSys ? '#8b949e' : '#e6edf3');
      t.setAttribute('pointer-events', 'none');
      t.setAttribute('y', rows.length > 1 ? (ri === 0 ? '-6' : '7') : '0');
      t.textContent = row.length > 14 ? row.slice(0,13) + '…' : row;
      g.appendChild(t);
    });

    // Session count below circle
    if (n.ns.sessionCount > 0) {
      const sc = document.createElementNS(SVG, 'text');
      sc.setAttribute('text-anchor', 'middle'); sc.setAttribute('y', '42');
      sc.setAttribute('font-size', '9'); sc.setAttribute('fill', '#484f58');
      sc.setAttribute('pointer-events', 'none');
      sc.textContent = n.ns.sessionCount + '×';
      g.appendChild(sc);
    }

    g.addEventListener('click', ev => { ev.stopPropagation(); switchView('overview'); forceSelectCard(n.nsIdx); });
    g.addEventListener('mousedown', ev => { ev.preventDefault(); startDagDrag(ev, ni); });
    ng.appendChild(g);
  });
  svgEl.appendChild(ng);

  _dag.raf = requestAnimationFrame(dagSimStep);
  dagUpdatePositions();
}

function toggleDAGSystem() {
  _dagShowSystem = !_dagShowSystem;
  renderDAG();
}

function dagSimStep() {
  const { nodes, edges, nodeMap, svgW, svgH } = _dag;
  const cx = svgW/2, cy = svgH/2;
  const REPEL = 5000, SLEN = 130, SK = 0.025, DAMP = 0.78, CENT = 0.006;

  for (let i = 0; i < nodes.length; i++) {
    for (let j = i+1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x || 0.01, dy = nodes[j].y - nodes[i].y || 0.01;
      const d = Math.sqrt(dx*dx + dy*dy) || 1, f = REPEL / (d*d);
      const fx = dx/d*f, fy = dy/d*f;
      if (!nodes[i].fixed) { nodes[i].vx -= fx; nodes[i].vy -= fy; }
      if (!nodes[j].fixed) { nodes[j].vx += fx; nodes[j].vy += fy; }
    }
  }
  edges.forEach(e => {
    const ai = nodeMap.get(e.source), bi = nodeMap.get(e.target);
    if (ai == null || bi == null) return;
    const a = nodes[ai], b = nodes[bi];
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx*dx + dy*dy) || 1;
    const f = SK * (d - SLEN), fx = dx/d*f, fy = dy/d*f;
    if (!a.fixed) { a.vx += fx; a.vy += fy; }
    if (!b.fixed) { b.vx -= fx; b.vy -= fy; }
  });
  let ke = 0;
  nodes.forEach(n => {
    if (!n.fixed) { n.vx += (cx - n.x) * CENT; n.vy += (cy - n.y) * CENT; }
    n.vx *= DAMP; n.vy *= DAMP;
    if (!n.fixed) {
      n.x = Math.max(40, Math.min(svgW - 40, n.x + n.vx));
      n.y = Math.max(35, Math.min(svgH - 35, n.y + n.vy));
    }
    ke += n.vx*n.vx + n.vy*n.vy;
  });
  dagUpdatePositions();
  _dag.tick++;
  if (_dag.tick < _dag.maxTick && ke > 0.02)
    _dag.raf = requestAnimationFrame(dagSimStep);
}

function dagUpdatePositions() {
  const { nodes, edges, nodeMap } = _dag;
  edges.forEach((e, ei) => {
    const ai = nodeMap.get(e.source), bi = nodeMap.get(e.target);
    if (ai == null || bi == null) return;
    const a = nodes[ai], b = nodes[bi];
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx*dx + dy*dy) || 1;
    const startR = 30, endR = EDGE_META[e.type]?.arrow ? 32 : 0;
    const x1 = a.x + dx/d*startR, y1 = a.y + dy/d*startR;
    const x2 = b.x - dx/d*endR,   y2 = b.y - dy/d*endR;
    const ln  = document.getElementById('dag-edge-' + ei);
    const hit = document.getElementById('dag-hit-'  + ei);
    [ln, hit].forEach(el => {
      if (!el) return;
      el.setAttribute('x1', x1.toFixed(1)); el.setAttribute('y1', y1.toFixed(1));
      el.setAttribute('x2', x2.toFixed(1)); el.setAttribute('y2', y2.toFixed(1));
    });
  });
  nodes.forEach((n, ni) => {
    const g = document.getElementById('dag-node-' + ni);
    if (g) g.setAttribute('transform', 'translate(' + n.x.toFixed(1) + ',' + n.y.toFixed(1) + ')');
  });
}

function startDagDrag(ev, ni) {
  const svg = document.getElementById('dag-svg');
  if (!svg) return;
  const bb = svg.getBoundingClientRect();
  const sx = _dag.svgW / bb.width, sy = _dag.svgH / bb.height;
  _dagDrag = { ni, ox: ev.clientX, oy: ev.clientY, nx: _dag.nodes[ni].x, ny: _dag.nodes[ni].y, sx, sy };
  _dag.nodes[ni].fixed = true;
  if (_dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }
  const onMove = e => {
    if (!_dagDrag) return;
    _dag.nodes[_dagDrag.ni].x = Math.max(40, Math.min(_dag.svgW-40, _dagDrag.nx + (e.clientX-_dagDrag.ox)*_dagDrag.sx));
    _dag.nodes[_dagDrag.ni].y = Math.max(35, Math.min(_dag.svgH-35, _dagDrag.ny + (e.clientY-_dagDrag.oy)*_dagDrag.sy));
    dagUpdatePositions();
  };
  const onUp = () => {
    _dagDrag = null;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    _dag.tick = 0; _dag.raf = requestAnimationFrame(dagSimStep);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function resetDAGLayout() {
  const { nodes, svgW, svgH } = _dag;
  const cx = svgW/2, cy = svgH/2, R0 = Math.min(svgW, svgH) * 0.32;
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i / nodes.length) - Math.PI / 2;
    n.x = cx + R0 * Math.cos(a); n.y = cy + R0 * Math.sin(a);
    n.vx = 0; n.vy = 0; n.fixed = false;
  });
  if (_dag.raf) cancelAnimationFrame(_dag.raf);
  _dag.tick = 0; _dag.raf = requestAnimationFrame(dagSimStep);
}

// Auto-open first card when only one namespace is shown
if (NS.length === 1) selectCard(0);
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# HTML assembly
# ─────────────────────────────────────────────────────────────────────────────

def render_html(namespaces):
    now         = _now_utc().strftime("%d %b %Y %H:%M UTC")
    n_open      = sum(1 for n in namespaces if n["open_session"])
    n_learnings = sum(len(n["learnings"]) for n in namespaces)
    n_sessions  = sum(n["session_count"] for n in namespaces)

    cards = "".join(_card_html(n, i) for i, n in enumerate(namespaces))

    html = HTML_TEMPLATE
    html = html.replace("[[GENERATED_AT]]", now)
    html = html.replace("[[N_NS]]",         str(len(namespaces)))
    html = html.replace("[[N_OPEN]]",       str(n_open))
    html = html.replace("[[N_LEARNINGS]]",  str(n_learnings))
    html = html.replace("[[N_SESSIONS]]",   str(n_sessions))
    html = html.replace("[[CARDS]]",        cards)
    html = html.replace("[[DATA_JSON]]",    _js_data(namespaces))

    return html


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate compass HTML dashboard")
    parser.add_argument("--namespace", "-n", help="Focus on a single namespace")
    parser.add_argument("--output",    "-o", default=str(OUTPUT_PATH), help="Output HTML path")
    parser.add_argument("--no-open",   action="store_true", help="Don't open in browser")
    args = parser.parse_args()

    namespaces = discover_namespaces(filter_ns=args.namespace)

    if not namespaces:
        msg = (f"Namespace '{args.namespace}' not found" if args.namespace
               else "No compass namespaces found in ~/.claude/loop/")
        print(json.dumps({"ok": False, "error": msg}))
        sys.exit(1)

    html      = render_html(namespaces)
    out_path  = Path(args.output)
    out_path.write_text(html, encoding="utf-8")

    if not args.no_open:
        import sys as _sys
        if _sys.platform == "darwin":
            subprocess.run(["open", str(out_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(out_path)], check=False)

    print(json.dumps({
        "ok":        True,
        "path":      str(out_path),
        "namespaces": len(namespaces),
        "learnings": sum(len(n["learnings"]) for n in namespaces),
        "sessions":  sum(n["session_count"] for n in namespaces),
    }))


if __name__ == "__main__":
    main()
