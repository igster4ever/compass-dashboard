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
    .search-input-wrap { flex: 1; max-width: 360px; position: relative; }
    .search-input {
      width: 100%; padding: .38rem .75rem .38rem 1.9rem;
      background: var(--surface2); border: 1px solid var(--border);
      border-radius: 20px; color: var(--text); font-family: inherit;
      font-size: .82rem; outline: none; transition: border-color .15s;
    }
    .search-input:focus { border-color: var(--blue); }
    .search-input::placeholder { color: var(--subtle); }
    .search-input-icon {
      position: absolute; left: .65rem; top: 50%; transform: translateY(-50%);
      color: var(--subtle); font-size: .85rem; pointer-events: none;
    }
    .search-summary { font-size: .78rem; color: var(--muted); padding: .4rem 0 .7rem; }
    .search-group {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); margin-bottom: .75rem; overflow: hidden;
    }
    .search-group-header {
      background: var(--surface2); padding: .45rem .875rem;
      font-weight: 700; font-size: .85rem; border-bottom: 1px solid var(--border);
    }
    .search-section-group { padding: .5rem .875rem; border-bottom: 1px solid var(--surface2); }
    .search-section-group:last-child { border-bottom: none; }
    .search-section-badge {
      display: inline-block; font-size: .62rem; font-weight: 700;
      letter-spacing: .06em; text-transform: uppercase;
      padding: .15em .55em; border-radius: 4px; margin-bottom: .4rem;
    }
    .sec-blue   { background: var(--blue-bg);  color: var(--blue); }
    .sec-green  { background: var(--green-bg); color: var(--green); }
    .sec-amber  { background: var(--amber-bg); color: var(--amber); }
    .sec-subtle { background: var(--surface2); color: var(--muted); }
    .search-result-item {
      padding: .32rem .5rem; border-radius: 4px; cursor: pointer;
      font-size: .8rem; margin-bottom: .15rem; transition: background .1s;
    }
    .search-result-item:hover { background: var(--surface2); }
    .snippet { color: var(--muted); line-height: 1.5; }
    mark { background: var(--amber-bg); color: var(--amber); border-radius: 2px; padding: 0 .1em; font-style: normal; }
    .search-more { font-size: .72rem; color: var(--subtle); font-style: italic; padding: .2rem .5rem; }

    @keyframes flashHighlight {
      0%   { background: var(--amber-bg); box-shadow: 0 0 0 2px var(--amber); }
      65%  { background: var(--amber-bg); box-shadow: 0 0 0 2px var(--amber); }
      100% { background: transparent; box-shadow: none; }
    }
    .highlight-flash { animation: flashHighlight 1.8s ease-out forwards; border-radius: 4px; }
  </style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="header-left">
      <h1>&#x1f9ed; Compass</h1>
      <span class="since">Generated [[GENERATED_AT]]</span>
    </div>
    <div class="search-input-wrap">
      <span class="search-input-icon">&#x2315;</span>
      <input class="search-input" type="search" id="search-input"
             placeholder="Search namespaces, learnings, decisions…"
             oninput="handleSearch(this.value)">
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
    <button class="view-tab"        id="vtab-search"     onclick="switchView('search')">Search</button>
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

  <div id="view-search" style="display:none">
    <div style="padding:2rem;text-align:center;color:var(--subtle);font-size:.85rem">
      Type in the search bar above to search across all namespaces.
    </div>
  </div>
</main>

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
  ['overview', 'priorities', 'search'].forEach(id => {
    document.getElementById('view-' + id).style.display = id === v ? '' : 'none';
    document.getElementById('vtab-' + id).classList.toggle('active', id === v);
  });
  if (v === 'priorities') renderPriorities();
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

// ── Search ────────────────────────────────────────────────────────────────────

let SEARCH_INDEX = null;
let _lastQuery   = '';

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

function buildSearchIndex() {
  const idx = [];
  NS.forEach((ns, nsIdx) => {
    if (ns.intent)      idx.push({nsIdx, section:'state', field:'intent',   text: ns.intent,      displayText: ns.intentSummary || ns.intent});
    if (ns.reality)     idx.push({nsIdx, section:'state', field:'reality',  text: ns.reality,     displayText: ns.reality.slice(0, 200)});
    if (ns.codeContext) idx.push({nsIdx, section:'state', field:'context',  text: ns.codeContext, displayText: ns.codeContext.slice(0, 200)});
    (ns.learnings || []).forEach((l, i) =>
      idx.push({nsIdx, section:'learnings', subIdx: i, text: l.text || '', displayText: l.text || ''})
    );
    [...(ns.decisions || [])].reverse().forEach((d, i) => {
      const combined = [d.decision||d.text||'', d.rationale||'', d.alternatives||''].join(' ');
      idx.push({nsIdx, section:'decisions', subIdx: i, text: combined, displayText: d.decision||d.text||''});
    });
    (ns.history || []).forEach((s, si) => {
      const parts = [...(s.completed||[]), ...(s.incomplete||[]),
                     ...(s.learnings_extracted||[]), s.notes||''].filter(Boolean);
      if (parts.length)
        idx.push({nsIdx, section:'history', subIdx: si, text: parts.join(' '), displayText: parts[0]||''});
    });
  });
  return idx;
}

function handleSearch(val) {
  _lastQuery = val.trim();
  const view = document.getElementById('view-search');
  if (!_lastQuery) {
    view.innerHTML = '<div style="padding:2rem;text-align:center;color:var(--subtle);font-size:.85rem">Type in the search bar above to search across all namespaces.</div>';
    return;
  }
  switchView('search');
  if (!SEARCH_INDEX) SEARCH_INDEX = buildSearchIndex();
  doSearch(_lastQuery);
}

function doSearch(query) {
  const q = query.toLowerCase();
  const hits = SEARCH_INDEX.filter(item => item.text.toLowerCase().includes(q));

  const groups = {};
  hits.forEach(m => {
    if (!groups[m.nsIdx]) groups[m.nsIdx] = {nsIdx: m.nsIdx, sections: {}};
    if (!groups[m.nsIdx].sections[m.section]) groups[m.nsIdx].sections[m.section] = new Map();
    const key = m.subIdx !== undefined ? String(m.subIdx) : (m.field || 'x');
    if (!groups[m.nsIdx].sections[m.section].has(key))
      groups[m.nsIdx].sections[m.section].set(key, m);
  });

  const totalNS   = Object.keys(groups).length;
  const totalHits = Object.values(groups).reduce((a, g) =>
    a + Object.values(g.sections).reduce((b, s) => b + s.size, 0), 0);

  if (!totalHits) {
    document.getElementById('view-search').innerHTML =
      '<div style="padding:2rem;text-align:center;color:var(--subtle)">No matches for &ldquo;' + esc(query) + '&rdquo;</div>';
    return;
  }

  const SECT_ORDER = ['state','learnings','decisions','history'];
  const SECT_LABEL = {state:'State', learnings:'Learnings', decisions:'Decisions', history:'History'};
  const SECT_CLS   = {state:'blue',  learnings:'green',     decisions:'amber',     history:'subtle'};

  let html = '<div class="search-summary">' + totalHits + ' match' + (totalHits!==1?'es':'') +
    ' across ' + totalNS + ' namespace' + (totalNS!==1?'s':'') +
    ' &mdash; click any result to navigate</div>';

  Object.values(groups).sort((a, b) => a.nsIdx - b.nsIdx).forEach(g => {
    const ns = NS[g.nsIdx];
    html += '<div class="search-group"><div class="search-group-header">' + esc(ns.namespace) + '</div>';
    SECT_ORDER.forEach(sec => {
      const secMap = g.sections[sec];
      if (!secMap || !secMap.size) return;
      const items = [...secMap.values()];
      html += '<div class="search-section-group"><div class="search-section-badge sec-' + SECT_CLS[sec] + '">' + SECT_LABEL[sec] + '</div>';
      items.slice(0, 6).forEach(item => {
        html += '<div class="search-result-item" onclick="navigateToResult(' +
          item.nsIdx + ',\'' + sec + '\',' +
          (item.subIdx !== undefined ? item.subIdx : -1) + ',\'' + (item.field||'') + '\')">' +
          makeSnippet(item.displayText || item.text, q) + '</div>';
      });
      if (items.length > 6)
        html += '<div class="search-more">+' + (items.length - 6) + ' more match' + (items.length-6!==1?'es':'') + '</div>';
      html += '</div>';
    });
    html += '</div>';
  });

  document.getElementById('view-search').innerHTML = html;
}

function makeSnippet(text, query) {
  if (!text) return '<span class="snippet">—</span>';
  const idx = text.toLowerCase().indexOf(query);
  if (idx === -1) return '<span class="snippet">' + esc(text.slice(0,120)) + (text.length>120?'…':'') + '</span>';
  const s = Math.max(0, idx - 45);
  const e = Math.min(text.length, idx + query.length + 70);
  return '<span class="snippet">' +
    (s > 0 ? '…' : '') +
    esc(text.slice(s, idx)) +
    '<mark>' + esc(text.slice(idx, idx + query.length)) + '</mark>' +
    esc(text.slice(idx + query.length, e)) +
    (e < text.length ? '…' : '') +
    '</span>';
}

function navigateToResult(nsIdx, section, subIdx, field) {
  switchView('overview');
  forceSelectCard(nsIdx);
  switchTab(section);

  requestAnimationFrame(() => {
    let target = null;
    if (section === 'state') {
      const headingMap = {intent:'Intent', reality:'Reality', context:'Next session entry point', decisions:'Recent decisions'};
      const want = headingMap[field] || 'Intent';
      document.querySelectorAll('#tab-state h3').forEach(h => {
        if (h.textContent.trim() === want) target = h.closest('.md-section') || h.parentElement;
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
