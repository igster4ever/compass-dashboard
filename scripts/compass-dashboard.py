#!/usr/bin/env python3
"""
compass-dashboard.py — generate a self-contained HTML dashboard from compass loop data.
stdlib-only (json, pathlib, datetime, re, subprocess, argparse). No pip installs.

Usage:
    python3 compass-dashboard.py [--namespace <ns>] [--output <path>] [--no-open]
"""

import hashlib
import json
import sys
import re
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

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


# Local copies — keep in sync with scripts/compass/reality.py (can't import; stdlib-only constraint)
_COMPLETION_MARKERS = frozenset({
    "complete", "live", "exists and works", "shipped", "passing", "done", "✓", "operational",
})
_BACKLOG_HEADERS = frozenset({
    "backlog", "planned", "missing", "next", "todo", "debt", "pending", "phase",
})


def _reality_completeness(reality_md):
    lines = reality_md.splitlines()
    in_backlog = False
    total = 0
    achieved = 0
    for line in lines:
        s = line.strip()
        if s.startswith("##"):
            header_text = s.lstrip("#").strip().lower()
            in_backlog = any(k in header_text for k in _BACKLOG_HEADERS)
        elif s.startswith("- ") or s.startswith("* "):
            text = s[2:].strip()
            if not text or text.startswith("_") or in_backlog:
                continue
            total += 1
            if any(marker in text.lower() for marker in _COMPLETION_MARKERS):
                achieved += 1
    if total == 0:
        return None
    return round(achieved / total * 100, 1)


def _corpus_health(active_learnings, superseded_count):
    total = len(active_learnings)
    if total < 3:
        return None
    unvalidated_hyp = sum(
        1 for l in active_learnings
        if l.get("learning_type") == "hypothesis" and not l.get("validation_result")
    )
    low_weight = sum(1 for l in active_learnings if (l.get("weight") or 1) == 1)
    total_with_sup = total + superseded_count

    score = 100
    score -= int((unvalidated_hyp / total) * 30)
    score -= int((low_weight / total) * 20)
    if superseded_count > 0:
        score += min(10, int(superseded_count / total_with_sup * 20))

    return {
        "score":                 max(0, min(100, score)),
        "unvalidatedHypotheses": unvalidated_hyp,
        "lowWeightCount":        low_weight,
        "totalActive":           total,
        "supersededCount":       superseded_count,
    }


def _stale_bullet_count(reality_md, state, days=30):
    """Count reality bullets not verified within `days` days (mirrors compass logic)."""
    validation = state.get("reality_validation", {})
    now = _now_utc()
    stale = 0
    for line in reality_md.splitlines():
        s = line.strip()
        if (s.startswith("- ") or s.startswith("* ")):
            text = s[2:].strip()
            if not text or text.startswith("_"):
                continue
            h = hashlib.sha256(text.encode()).hexdigest()[:8]
            ts = validation.get(h)
            if not ts:
                stale += 1
            else:
                dt = _parse_iso(ts)
                if dt and (now - dt) > timedelta(days=days):
                    stale += 1
    return stale


def _parse_goal_entry(entry):
    """Normalise a goal_completions entry to (total_goals, hit_rate_pct)."""
    if isinstance(entry, dict):
        return entry.get("total_goals", 0), int(entry.get("hit_rate", 0))
    if isinstance(entry, list) and entry:
        n_done = sum(1 for s in entry if s == "completed")
        total = len(entry)
        return total, int(n_done / total * 100)
    return 0, 0


def _suggested_goal_count(state):
    completions = state.get("goal_completions", {})
    if not completions:
        return {"count": 4, "basis": "no history — using default"}
    rates = []
    for v in completions.values():
        if not v:
            continue
        _, rate = _parse_goal_entry(v)
        rates.append(rate)
    if not rates:
        return {"count": 4, "basis": "no history — using default"}
    avg = sum(rates) / len(rates)
    if avg >= 80:
        return {"count": 5, "basis": f"≥80% avg hit-rate ({avg:.1f}%) — capacity to spare"}
    if avg >= 60:
        return {"count": 4, "basis": f"60–79% avg hit-rate ({avg:.1f}%) — calibrated"}
    return {"count": 3, "basis": f"<60% avg hit-rate ({avg:.1f}%) — reduce scope"}


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
            if item and not item.lower().startswith("(none"):
                result[section].append(item)
        elif section == "notes" and s:
            result["notes"] += s + " "

    return result


def _classify_session(session, hit_rate=None):
    """Classify a parsed history session as 'high', 'neutral', or 'poor'.

    hit_rate (0–100) from goal_completions is preferred; falls back to
    completed/planned ratio from the history file.
    """
    planned   = len(session.get("planned", []))
    completed = len(session.get("completed", []))
    if hit_rate is None:
        if planned == 0:
            return "neutral"
        hit_rate = completed / planned * 100
    if hit_rate >= 80:
        return "high"
    if hit_rate < 50:
        return "poor"
    return "neutral"


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
    for _, entry in sessions:
        total, rate = _parse_goal_entry(entry)
        level = "high" if rate >= 80 else "mid" if rate >= 50 else "low"
        dots.append({"level": level, "rate": rate})

    _, latest = sessions[-1] if sessions else (None, {})
    total, rate = _parse_goal_entry(latest)
    return (rate if total else None), dots


def _goal_by_month(state):
    completions = state.get("goal_completions", {})
    monthly = {}
    for key, entry in completions.items():
        if not entry:
            continue
        month = str(key)[:7]
        if len(month) != 7 or month[4] != '-':
            continue
        _, rate = _parse_goal_entry(entry)
        if month not in monthly:
            monthly[month] = []
        monthly[month].append(rate)
    return {m: int(sum(rates) / len(rates)) for m, rates in monthly.items()}


def _compute_exploration_ratio(state):
    """Replicate compass _compute_exploration_ratio logic (stdlib-only, can't import)."""
    completions = state.get("goal_completions", {})
    if not completions:
        return None
    recent = sorted(completions.items(), key=lambda x: x[0], reverse=True)[:5]
    typed  = [v for _, v in recent if v.get("types")]
    if len(typed) < 2:
        return None
    explore = sum(t.count("explore") for t in (v["types"] for v in typed))
    total   = sum(len(v["types"]) for v in typed)
    ratio   = round(explore / total * 100, 1) if total else 0.0
    return {
        "ratio":             ratio,
        "sessionsWithTypes": len(typed),
        "explore":           explore,
        "total":             total,
        "low":               ratio < 20.0 and len(typed) >= 3,
    }


def _goal_type_by_session(state):
    """Per-session E/X breakdown from goal_completions[*].types, chronological."""
    completions = state.get("goal_completions", {})
    result = []
    for ts, entry in sorted(completions.items()):
        if not isinstance(entry, dict):
            continue
        types   = entry.get("types")
        date    = ts[:10]
        if types:
            exploit = types.count("exploit")
            explore = types.count("explore")
        else:
            exploit = entry.get("total_goals", 0)
            explore = 0
        result.append({"date": date, "exploit": exploit, "explore": explore})
    return result


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
    session_dates = sorted(
        f.stem[:10] for f in history_dir.glob("*.md")
        if len(f.stem) >= 10
    ) if history_dir.exists() else []

    open_session = state.get("open_session", False)
    last_close   = _parse_iso(state.get("last_close"))
    last_open    = _parse_iso(state.get("last_open"))
    goal_rate, goal_dots = _goal_stats(state)
    goal_by_month = _goal_by_month(state)

    all_learnings    = sorted(learnings, key=lambda x: -x.get("weight", 1))
    active_learnings = [l for l in all_learnings if not l.get("superseded_by")]
    superseded_count = len(all_learnings) - len(active_learnings)

    cycle_history      = state.get("cycle_history", [])
    last_cycle_minutes = state.get("last_cycle_minutes")

    config = _read_json(ns_dir / "config.json")

    sessions_since_dream      = state.get("sessions_since_dream", 0)
    corpus_size               = len(active_learnings)
    corpus_delta              = state.get("corpus_delta", 0) or 0
    dream_due                 = sessions_since_dream >= 5 or corpus_size >= 15 or corpus_delta >= 10
    reality_completeness_score = _reality_completeness(reality)
    suggested_goal_count      = _suggested_goal_count(state)

    research_interval  = config.get("research_interval_sessions", 10)
    research_due       = state.get("sessions_since_research", 0) >= research_interval

    review_interval    = config.get("review_interval_sessions", 5)
    repo_path          = state.get("repo_path", "")
    code_review_due    = bool(repo_path) and state.get("sessions_since_review", 0) >= review_interval

    intent_version     = state.get("intent_versions", 1)
    stale_bullet_count = _stale_bullet_count(reality, state)
    corpus_health      = _corpus_health(active_learnings, superseded_count)

    exploration_ratio    = _compute_exploration_ratio(state)
    last_reality_score   = state.get("last_reality_score")
    goal_type_by_session = _goal_type_by_session(state)
    # Carry-forward trend + quality distribution: all history files (uncapped) — sorted chronologically
    carry_forward_trend = []
    quality_dist = {"high": 0, "neutral": 0, "poor": 0}
    # Build date-keyed lookup from goal_completions for hit_rate matching
    completions_by_date = {}
    for ts, entry in state.get("goal_completions", {}).items():
        date = str(ts)[:10]
        if isinstance(entry, dict):
            completions_by_date[date] = entry.get("hit_rate")
    if history_dir.exists():
        for f in sorted(history_dir.glob("*.md")):
            parsed = _parse_history_file(f)
            if parsed:
                carry_forward_trend.append({
                    "date":           f.stem[:10],
                    "carryForward":   len(parsed["incomplete"]),
                    "goalsCompleted": len(parsed["completed"]),
                })
                hit_rate = completions_by_date.get(f.stem[:10])
                quality_dist[_classify_session(parsed, hit_rate)] += 1

    # Intent drift timeline
    intent_history = _read_jsonl(ns_dir / "intent_history.jsonl")

    # Decay history — corpus maintenance events (newest first)
    decay_history = list(reversed(_read_jsonl(ns_dir / "decay_history.jsonl")))

    # Deferral escalation counts (used in Priorities scoring)
    code_review_defer_count  = len(_read_jsonl(ns_dir / "code_review_deferrals.jsonl"))
    research_defer_count     = len(_read_jsonl(ns_dir / "research_deferrals.jsonl"))

    # External research signals
    external_signals = list(reversed(_read_jsonl(ns_dir / "external_signals.jsonl")))

    # Cross-namespace learning links
    back_refs_raw = _read_jsonl(ns_dir / "back_references.jsonl")
    conflicts_raw = _read_jsonl(ns_dir / "conflict_resolutions.jsonl")
    back_refs_by_text = {
        r["learning_text"]: {"sourceNamespace": r.get("source_namespace", ""), "recordedAt": r.get("recorded_at", "")}
        for r in back_refs_raw if r.get("learning_text")
    }
    conflicts_by_text = {}
    for r in conflicts_raw:
        txt = r.get("learning_text", "")
        if txt:
            conflicts_by_text.setdefault(txt, []).append({
                "decision":        r.get("decision", ""),
                "sourceNamespace": r.get("source_namespace", ""),
                "targetNamespace": r.get("target_namespace", ""),
            })

    intent_summary = ""
    for line in intent.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            intent_summary = line
            break

    return {
        "namespace":            ns_dir.name,
        "open_session":         open_session,
        "last_close":           last_close,
        "last_open":            last_open,
        "planned_actions":      state.get("planned_actions", []),
        "deferred":             state.get("deferred_opportunities", {}),
        "intent":               intent,
        "intent_summary":       intent_summary,
        "reality":              reality,
        "learnings":            active_learnings,
        "superseded_count":     superseded_count,
        "decisions":            decisions,
        "code_context":         code_context,
        "history":              history_files,
        "session_dates":        session_dates,
        "goal_rate":            goal_rate,
        "goal_dots":            goal_dots,
        "goal_by_month":        goal_by_month,
        "top_tags":             _top_tags(active_learnings),
        "session_count":        session_count,
        "cycle_history":        cycle_history,
        "last_cycle_minutes":   last_cycle_minutes,
        "sessions_since_dream":      sessions_since_dream,
        "dream_due":                 dream_due,
        "reality_completeness_score": reality_completeness_score,
        "suggested_goal_count":      suggested_goal_count,
        "research_due":              research_due,
        "code_review_due":           code_review_due,
        "intent_version":            intent_version,
        "stale_bullet_count":        stale_bullet_count,
        "back_refs_by_text":         back_refs_by_text,
        "conflicts_by_text":         conflicts_by_text,
        "intent_history":            intent_history,
        "corpus_health":             corpus_health,
        "external_signals":          external_signals,
        "exploration_ratio":         exploration_ratio,
        "last_reality_score":        last_reality_score,
        "goal_type_by_session":      goal_type_by_session,
        "carry_forward_trend":       carry_forward_trend,
        "quality_dist":              quality_dist,
        "decay_history":             decay_history,
        "code_review_defer_count":   code_review_defer_count,
        "research_defer_count":      research_defer_count,
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
        escalated = sum(1 for v in n["deferred"].values() if v.get("defer_count", 0) >= 2)
        if escalated:
            deferred_html = f'<span class="deferred-chip escalated">⚠ {dc} deferred</span>'
        else:
            deferred_html = f'<span class="deferred-chip">{dc} deferred</span>'

    dream_html     = '<span class="dream-chip">🌙 dream due</span>' if n["dream_due"] else ""
    research_html  = '<span class="cadence-chip research">🔬 research due</span>' if n["research_due"] else ""
    review_html    = '<span class="cadence-chip review">🔍 review due</span>' if n["code_review_due"] else ""

    completeness_html = ""
    rcs = n["reality_completeness_score"]
    if rcs is not None:
        rc_cls = "high" if rcs >= 60 else "mid" if rcs >= 30 else "low"
        lrs = n.get("last_reality_score")
        delta_html = ""
        if lrs is not None:
            delta = rcs - lrs
            if abs(delta) >= 1:
                delta_sign = "+" if delta > 0 else ""
                delta_col  = "green" if delta > 0 else "red"
                delta_html = f' <span style="font-size:.7rem;color:var(--{delta_col})">{delta_sign}{delta:.0f}</span>'
        completeness_html = f'<span class="rate-pill {rc_cls}" title="Reality completeness">{rcs:.0f}% done{delta_html}</span>'

    # E14 — Exploration ratio badge
    explore_html = ""
    er = n.get("exploration_ratio")
    if er and er.get("ratio") is not None:
        er_style = "color:var(--amber)" if er.get("low") else "color:var(--muted)"
        explore_html = (f'<span class="cadence-chip" style="{er_style}" '
                        f'title="{er.get("sessionsWithTypes", 0)} typed sessions">'
                        f'{er["ratio"]:.0f}% explore</span>')

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
        {completeness_html}
        {deferred_html}
        {dream_html}
        {research_html}
        {review_html}
        {explore_html}
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
            "sessionDates":   n["session_dates"],
            "goalRate":       n["goal_rate"],
            "goalDots":       n["goal_dots"],
            "topTags":        n["top_tags"],
            "deferred":       [
                {"key": k, "escalated": v.get("defer_count", 0) >= 2, **v}
                for k, v in n["deferred"].items()
            ],
            "goalByMonth":        n["goal_by_month"],
            "sessionCount":       n["session_count"],
            "plannedActions":     n["planned_actions"],
            "supersededCount":    n["superseded_count"],
            "cycleHistory":       n["cycle_history"],
            "lastCycleMinutes":   n["last_cycle_minutes"],
            "sessionsSinceDream":       n["sessions_since_dream"],
            "dreamDue":                n["dream_due"],
            "realityCompletenessScore": n["reality_completeness_score"],
            "suggestedGoalCount":       n["suggested_goal_count"],
            "researchDue":             n["research_due"],
            "codeReviewDue":           n["code_review_due"],
            "intentVersion":           n["intent_version"],
            "staleBulletCount":        n["stale_bullet_count"],
            "backRefsByText":          n["back_refs_by_text"],
            "conflictsByText":         n["conflicts_by_text"],
            "intentHistory":           n["intent_history"],
            "corpusHealth":            n["corpus_health"],
            "externalSignals":         n["external_signals"],
            "explorationRatio":        n["exploration_ratio"],
            "lastRealityScore":        n["last_reality_score"],
            "goalTypeBySession":       n["goal_type_by_session"],
            "carryForwardTrend":       n["carry_forward_trend"],
            "qualityDist":             n["quality_dist"],
            "decayHistory":            n["decay_history"],
            "codeReviewDeferCount":    n["code_review_defer_count"],
            "researchDeferCount":      n["research_defer_count"],
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
    .deferred-chip.escalated {
      background: var(--red-bg); color: var(--red); font-weight: 600;
    }
    .dream-chip {
      font-size: .62rem; background: rgba(139,93,199,.15); color: #b48ef0;
      padding: .15em .5em; border-radius: 999px;
    }
    .cadence-chip {
      font-size: .62rem; padding: .15em .5em; border-radius: 999px;
    }
    .cadence-chip.research { background: rgba(56,189,248,.12); color: #38bdf8; }
    .cadence-chip.review   { background: rgba(52,211,153,.12); color: #34d399; }
    .version-badge {
      font-size: .6rem; font-weight: 600; background: var(--border);
      color: var(--muted); padding: .1em .45em; border-radius: 999px;
      vertical-align: middle; margin-left: .3em;
    }
    .link-ref {
      font-size: .68rem; color: var(--subtle); margin-top: .2em;
    }
    .link-ref code {
      font-size: .68rem; color: var(--accent); background: none; padding: 0;
    }
    .intent-hist-entry {
      display: grid; grid-template-columns: 2.2rem 6rem 1fr;
      gap: .2rem .6rem; align-items: baseline;
      padding: .35rem 0; border-bottom: 1px solid var(--border);
      font-size: .8rem;
    }
    .intent-hist-entry:last-child { border-bottom: none; }
    .intent-hist-ver  { font-weight: 700; color: var(--accent); font-size: .72rem; }
    .intent-hist-date { color: var(--muted); font-size: .72rem; white-space: nowrap; }
    .intent-hist-text { color: var(--text); grid-column: 3; }
    .intent-hist-reason {
      grid-column: 3; color: var(--subtle); font-size: .72rem;
      font-style: italic; margin-top: .1rem;
    }
    .corpus-health {
      display: flex; align-items: center; gap: .5rem;
      margin-bottom: .75rem; font-size: .75rem;
    }
    .ch-label  { color: var(--muted); white-space: nowrap; }
    .ch-bar-wrap {
      flex: 0 0 80px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden;
    }
    .ch-bar    { height: 100%; border-radius: 3px; transition: width .3s; }
    .ch-high   { background: var(--green, #34d399); }
    .ch-mid    { background: var(--amber); }
    .ch-low    { background: var(--red); }
    .ch-score  { font-weight: 700; color: var(--text); min-width: 2rem; }
    .ch-detail { color: var(--subtle); }
    .decay-event {
      padding: .45rem .6rem; border-left: 2px solid var(--border); margin-bottom: .4rem;
    }
    .decay-date   { color: var(--muted); font-size: .72rem; margin-right: .5rem; }
    .decay-count  { color: var(--amber); font-size: .72rem; margin-right: .5rem; }
    .decay-reason { color: var(--subtle); font-size: .7rem; }
    .decay-texts  { margin: .25rem 0 0 .5rem; padding: 0; list-style: none; }
    .signals-list { display: flex; flex-direction: column; gap: .75rem; }
    .signal-entry {
      padding: .6rem .8rem; border: 1px solid var(--border); border-radius: 6px;
    }
    .signal-header {
      display: flex; align-items: center; gap: .5rem; margin-bottom: .3rem;
      font-size: .72rem;
    }
    .signal-date   { color: var(--muted); white-space: nowrap; }
    .signal-source {
      background: rgba(56,189,248,.12); color: #38bdf8;
      padding: .1em .4em; border-radius: 999px; font-size: .65rem;
    }
    .signal-text  { font-size: .82rem; color: var(--text); line-height: 1.45; }
    .signal-remit { font-size: .72rem; color: var(--subtle); margin-top: .2rem; font-style: italic; }
    .vel-legend {
      display: flex; flex-wrap: wrap; gap: .3rem .8rem;
      padding: .5rem 0 .75rem; font-size: .72rem; color: var(--muted);
    }
    .vel-legend-item { display: flex; align-items: center; gap: .3rem; }
    .vel-legend-dot  { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
    .cycle-bar {
      display: inline-block; width: 6px; border-radius: 2px 2px 0 0;
      background: var(--blue-bg); border: 1px solid var(--blue);
      flex-shrink: 0;
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

    /* ── Tasks tab ── */
    .task-list { display: flex; flex-direction: column; gap: .45rem; }
    .task-row { display: flex; align-items: flex-start; gap: .7rem; padding: .55rem .65rem; border-radius: 6px; background: var(--surface2); }
    .task-row:hover { filter: brightness(1.12); }
    .task-rank { flex-shrink: 0; width: 1.35rem; height: 1.35rem; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: .7rem; font-weight: 700; color: var(--muted); border: 1px solid var(--border); margin-top: .1rem; }
    .task-rank.top3 { color: var(--blue); border-color: var(--blue); }
    .task-body { flex: 1; min-width: 0; }
    .task-text { font-size: .82rem; color: var(--text); line-height: 1.4; word-break: break-word; }
    .task-meta { margin-top: .28rem; display: flex; gap: .35rem; flex-wrap: wrap; align-items: center; }
    .task-src { font-size: .67rem; padding: .1rem .42rem; border-radius: 3px; font-weight: 600; white-space: nowrap; }
    .task-src-incomplete { background: rgba(210,153,34,.15); color: var(--amber); }
    .task-src-next       { background: rgba(63,185,80,.15);  color: var(--green); }
    .task-src-planned    { background: rgba(88,166,255,.15); color: var(--blue); }
    .task-src-deferred   { background: var(--surface); color: var(--muted); border: 1px solid var(--border); }
    .task-recur { font-size: .67rem; color: var(--muted); }
    .task-empty { color: var(--muted); font-size: .82rem; padding: .5rem 0; }

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

    /* ── Heatmap view ── */
    .heatmap-wrap { overflow-x: auto; padding-bottom: .5rem; }
    .heatmap-grid {
      display: grid;
      gap: 2px;
      width: max-content;
      min-width: 100%;
    }
    .heatmap-label-row { display: contents; }
    .heatmap-row { display: contents; }
    .heatmap-corner { background: none; }
    .heatmap-col-label {
      font-size: .68rem; color: var(--muted);
      text-align: center; padding: .2rem .1rem;
      writing-mode: vertical-rl; transform: rotate(180deg);
      height: 56px; align-self: end; white-space: nowrap;
    }
    .heatmap-ns-label {
      font-size: .75rem; color: var(--text);
      padding: .2rem .5rem .2rem 0;
      white-space: nowrap; align-self: center;
      text-align: right;
    }
    .heatmap-ns-label.open-ns { color: var(--green); }
    .heatmap-cell {
      width: 28px; height: 28px; border-radius: 3px;
      background: var(--surface2);
      cursor: default; transition: opacity .1s;
      position: relative;
    }
    .heatmap-cell:hover { opacity: .75; }
    .heatmap-cell[data-count="0"] { background: var(--surface2); }
    .heatmap-cell[data-level="1"] { background: #1a4731; }
    .heatmap-cell[data-level="2"] { background: #206040; }
    .heatmap-cell[data-level="3"] { background: #2a8055; }
    .heatmap-cell[data-level="4"] { background: #38a86e; }
    .heatmap-legend {
      display: flex; align-items: center; gap: .4rem;
      margin-top: .75rem; font-size: .7rem; color: var(--muted);
    }
    .heatmap-legend-cell {
      width: 14px; height: 14px; border-radius: 2px;
    }
    .heatmap-tooltip {
      position: fixed; z-index: 200;
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: .4rem .6rem;
      font-size: .75rem; color: var(--text);
      pointer-events: none; display: none; white-space: nowrap;
      box-shadow: 0 4px 16px rgba(0,0,0,.4);
    }

    /* ── Learning timeline ── */
    .timeline-wrap { padding: .5rem 0; }
    .timeline-chart-area { overflow-x: auto; padding-bottom: .5rem; }
    .timeline-svg { display: block; }
    .timeline-legend {
      display: flex; flex-wrap: wrap; gap: .5rem 1.25rem;
      margin-top: .75rem; font-size: .72rem; color: var(--muted);
    }
    .timeline-legend-item { display: flex; align-items: center; gap: .4rem; }
    .timeline-legend-swatch { width: 20px; height: 3px; border-radius: 2px; flex-shrink: 0; }

    /* ── Heatmap sub-selector ── */
    .hmap-toolbar { display: flex; gap: .5rem; margin-bottom: .75rem; }

    /* ── Goal heatmap ── */
    .goal-cell {
      width: 28px; height: 28px; border-radius: 3px;
      background: var(--surface2);
      cursor: default; transition: opacity .1s; position: relative;
    }
    .goal-cell:hover { opacity: .75; }
    .goal-cell[data-qlevel="1"] { background: #0d2847; }
    .goal-cell[data-qlevel="2"] { background: #154075; }
    .goal-cell[data-qlevel="3"] { background: #1a5ba0; }
    .goal-cell[data-qlevel="4"] { background: #2679cc; }

    /* ── Scorecard ── */
    .scard-wrap { padding: .25rem 0; }
    .scard-chart-area { overflow-x: auto; margin-bottom: 1rem; }
    .scard-table { display: flex; flex-direction: column; gap: .2rem; }
    .scard-header {
      display: flex; align-items: center; gap: .75rem;
      padding: .2rem .6rem; font-size: .62rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .06em; color: var(--subtle);
    }
    .scard-row {
      display: flex; align-items: center; gap: .75rem;
      padding: .35rem .6rem; border-radius: 4px;
      background: var(--surface2); transition: opacity .12s; cursor: default;
    }
    .scard-rank  { font-size: .68rem; color: var(--subtle); min-width: 1.4rem; text-align: right; flex-shrink: 0; }
    .scard-ns    { font-size: .78rem; font-weight: 600; min-width: 10rem; flex-shrink: 0; }
    .scard-score { font-size: .72rem; font-weight: 700; min-width: 2.8rem; text-align: right; flex-shrink: 0; }
    .scard-bars  { flex: 1; display: flex; gap: .35rem; align-items: center; min-width: 0; }
    .scard-bar-col { flex: 1; min-width: 0; }
    .scard-bar-bg  { height: 5px; border-radius: 3px; background: var(--surface); }
    .scard-bar-fg  { height: 5px; border-radius: 3px; }
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
    <button class="view-tab"        id="vtab-scorecard"  onclick="switchView('scorecard')">Scorecard</button>
    <button class="view-tab"        id="vtab-dag"        onclick="switchView('dag')">DAG</button>
    <button class="view-tab"        id="vtab-heatmap"       onclick="switchView('heatmap')">Heatmap</button>
    <button class="view-tab"        id="vtab-timeline"      onclick="switchView('timeline')">Learning Timeline</button>
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
  <div id="view-scorecard"  style="display:none"></div>
  <div id="view-dag"        style="display:none"></div>
  <div id="view-heatmap"      style="display:none"></div>
  <div id="view-timeline"     style="display:none"></div>
  <div id="heatmap-tooltip" class="heatmap-tooltip"></div>

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
  const derivedTasks = deriveTasks(ns);
  const hasSignals   = (ns.externalSignals || []).length > 0;
  const hasDecisions = ns.decisions && ns.decisions.length;
  const baseTabs     = hasDecisions
    ? ['state', 'learnings', 'decisions', 'history']
    : ['state', 'learnings', 'history'];
  const tabs   = [...baseTabs, 'tasks', ...(hasSignals ? ['signals'] : [])];
  const labels = {
    state:     'State',
    learnings: `Learnings (${ns.learnings.length})`,
    decisions: `Decisions (${(ns.decisions || []).length})`,
    history:   `History (${ns.sessionCount})`,
    tasks:     derivedTasks.length ? `Tasks (${derivedTasks.length})` : 'Tasks',
    signals:   `Signals (${(ns.externalSignals || []).length})`,
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
  if (tab === 'tasks')     return renderTasks(ns);
  if (tab === 'signals')   return renderExternalSignals(ns);
  return '';
}

// Derive and rank up to 10 pending tasks from incomplete history, reality.md next-session
// bullets, plannedActions, and deferred opportunities.
function deriveTasks(ns) {
  const candidates = new Map();
  const N = (ns.history || []).length;

  // Incomplete items: scored by recency (most recent session = highest) + recurrence bonus
  (ns.history || []).forEach((h, hi) => {
    const recency = (N - hi);
    (h.incomplete || []).filter(r => !r.toLowerCase().startsWith('(none')).forEach(raw => {
      const key = raw.toLowerCase().trim().replace(/^[\u2713\u2717-] */, '').trim();
      const ex = candidates.get(key);
      if (ex) { ex.score += recency; ex.sessions++; }
      else candidates.set(key, { text: raw, score: recency * 2, sessions: 1, src: 'incomplete' });
    });
  });

  // 'What is next' section bullets and inline 'Next session:' lines in reality.md
  const realityLines = (ns.reality || '').split('\\n');
  let inNextSection = false;
  realityLines.forEach(line => {
    // Detect '## What is next' (compass skill canonical format)
    if (/^#{1,4}\\s+[Ww]hat\\s+is\\s+next/i.test(line)) { inNextSection = true; return; }
    // Any subsequent heading exits the section
    if (/^#{1,4}\\s/.test(line)) { inNextSection = false; }
    if (inNextSection) {
      const bullet = line.match(/^\\s*[-*]\\s+(.+)/);
      if (!bullet) return;
      const raw = bullet[1].trim();
      const key = raw.toLowerCase().trim();
      if (raw.length > 2 && !candidates.has(key))
        candidates.set(key, { text: raw, score: N + 4, sessions: 1, src: 'next' });
      return;
    }
    // Inline 'Next session: ...' fallback
    const m = line.match(/[Nn]ext +session *[:-] *(.+)/);
    if (!m) return;
    m[1].split(/[,;]/).map(s => s.trim().replace(/^-+/, '').trim()).filter(s => s.length > 2).forEach(raw => {
      const key = raw.toLowerCase().trim();
      if (!candidates.has(key)) candidates.set(key, { text: raw, score: N + 4, sessions: 1, src: 'next' });
    });
  });

  // Explicit planned actions (usually empty but future-proof)
  (ns.plannedActions || []).forEach(raw => {
    const text = typeof raw === 'string' ? raw : (raw.text || '');
    const key = text.toLowerCase().trim();
    if (key && !candidates.has(key)) candidates.set(key, { text, score: N + 8, sessions: 1, src: 'planned' });
  });

  // Deferred opportunities (lower priority)
  (ns.deferred || []).forEach(d => {
    const text = d.key || d.text || '';
    const key = text.toLowerCase().trim();
    if (key && !candidates.has(key)) candidates.set(key, { text, score: 2, sessions: 1, src: 'deferred' });
  });

  return Array.from(candidates.values())
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);
}

function renderTasks(ns) {
  const tasks = deriveTasks(ns);
  if (!tasks.length) return '<p class="task-empty">No pending tasks found — all clear.</p>';
  const SRC_LABELS = { incomplete: 'incomplete', next: 'next session', planned: 'planned', deferred: 'deferred' };
  const SRC_CLS    = { incomplete: 'task-src-incomplete', next: 'task-src-next', planned: 'task-src-planned', deferred: 'task-src-deferred' };
  const rows = tasks.map((t, i) => {
    const rankCls = i < 3 ? ' top3' : '';
    const recur = t.sessions > 1 ? `<span class="task-recur">${t.sessions}\u00d7 sessions</span>` : '';
    const srcCls = SRC_CLS[t.src] || 'task-src-deferred';
    const srcLabel = SRC_LABELS[t.src] || t.src;
    return `<div class="task-row">`
      + `<span class="task-rank${rankCls}">${i+1}</span>`
      + `<div class="task-body">`
      + `<div class="task-text">${esc(t.text)}</div>`
      + `<div class="task-meta"><span class="task-src ${srcCls}">${srcLabel}</span>${recur}</div>`
      + `</div></div>`;
  }).join('');
  return `<div class="task-list">${rows}</div>`;
}

function renderState(ns) {
  let html = '';

  // Intent
  const intentVer = ns.intentVersion > 1 ? ` <span class="version-badge">v${ns.intentVersion}</span>` : '';
  html += `<div class="md-section"><h3>Intent${intentVer}</h3><div>${md(ns.intent)}</div></div>`;

  // Intent history (only if 2+ versions exist)
  if (ns.intentHistory && ns.intentHistory.length > 1) {
    const entries = [...ns.intentHistory].reverse().map(h => {
      const date   = (h.recorded_at || '').slice(0, 10);
      const oneliner = (h.text || '').split('\\n')[0].slice(0, 120);
      const reason = h.reason ? `<div class="intent-hist-reason">${esc(h.reason)}</div>` : '';
      return `<div class="intent-hist-entry">
        <span class="intent-hist-ver">v${h.version}</span>
        <span class="intent-hist-date">${esc(date)}</span>
        <div class="intent-hist-text">${esc(oneliner)}</div>
        ${reason}
      </div>`;
    }).join('');
    html += `<div class="md-section"><h3>Intent history</h3>${entries}</div>`;
  }

  // Active goals (open sessions only)
  if (ns.open && ns.plannedActions.length > 0) {
    const items = ns.plannedActions.map(a => `<li>${esc(a)}</li>`).join('');
    html += `<div class="md-section"><h3>Active goals</h3><ul class="goals-list">${items}</ul></div>`;
  }

  // Suggested goal count for next session (closed sessions only)
  if (!ns.open && ns.suggestedGoalCount) {
    const sgc = ns.suggestedGoalCount;
    html += `<div class="md-section"><h3>Next session</h3>
      <div style="font-size:.82rem">Suggested goals: <strong>${sgc.count}</strong>
      <span style="color:var(--muted);font-size:.75rem"> \\u2014 ${esc(sgc.basis)}</span></div>
    </div>`;
  }

  // Next session entry point (code_context.md)
  if (ns.codeContext) {
    html += `<div class="md-section"><h3>Next session entry point</h3>
      <div class="context-block">${md(ns.codeContext)}</div>
    </div>`;
  }

  // Reality
  const staleNote = ns.staleBulletCount > 0
    ? ` <span style="color:var(--amber);font-size:.66rem;font-weight:normal">\\u26a0 ${ns.staleBulletCount} unverified</span>`
    : '';
  html += `<div class="md-section"><h3>Reality${staleNote}</h3><div>${md(ns.reality)}</div></div>`;

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

  // Cycle time sparkline
  if (ns.cycleHistory && ns.cycleHistory.length > 0) {
    const maxMins = Math.max(...ns.cycleHistory.map(s => s.minutes), 1);
    const hasCmds = ns.cycleHistory.some(s => s.command_count != null);
    const bars = ns.cycleHistory.map(s => {
      const h   = Math.max(4, Math.round(s.minutes / maxMins * 32));
      const dt  = (s.opened_at || '').slice(0, 10);
      const cc  = s.command_count != null ? `, ${s.command_count} cmds` : '';
      const bar = `<span class="cycle-bar" style="height:${h}px"></span>`;
      const lbl = hasCmds
        ? `<span style="font-size:.62rem;color:var(--muted);line-height:1;min-width:10px;text-align:center">${s.command_count != null ? s.command_count : ''}</span>`
        : '';
      return `<div title="${esc(dt)}: ${s.minutes}m${cc}" style="display:flex;flex-direction:column;align-items:center;gap:2px">${bar}${lbl}</div>`;
    }).join('');
    const lastLabel = ns.lastCycleMinutes != null ? `${ns.lastCycleMinutes}m` : '\\u2014';
    const cmdEntries = ns.cycleHistory.filter(s => s.command_count != null);
    const avgCmds    = cmdEntries.length > 0
      ? Math.round(cmdEntries.reduce((a, s) => a + s.command_count, 0) / cmdEntries.length)
      : null;
    const cmdLabel = avgCmds != null ? ` \\u00b7 avg ${avgCmds} cmds/session` : '';
    const sparkHeight = hasCmds ? '50px' : '36px';
    html += `<div class="md-section"><h3>Session cycle time</h3>
      <div style="display:flex;align-items:flex-end;gap:3px;height:${sparkHeight};margin:.4rem 0 .3rem">${bars}</div>
      <div style="font-size:.72rem;color:var(--muted)">Last: <strong style="color:var(--text)">${esc(lastLabel)}</strong> \\u00b7 ${ns.cycleHistory.length} session${ns.cycleHistory.length !== 1 ? 's' : ''} tracked${cmdLabel}${hasCmds ? ' \\u00b7 cmd count shown below bars' : ''}</div>
    </div>`;
  }

  // Dream consolidation status
  const dsd       = ns.sessionsSinceDream || 0;
  const dreamIcon = ns.dreamDue ? '⚠' : '✓';
  const dreamCol  = ns.dreamDue ? 'var(--amber)' : 'var(--muted)';
  const dreamMsg  = ns.dreamDue
    ? `due — ${dsd} session${dsd !== 1 ? 's' : ''} since last consolidation`
    : `${dsd} session${dsd !== 1 ? 's' : ''} since last consolidation`;
  html += `<div class="md-section"><h3>Dream consolidation</h3>
    <div style="font-size:.82rem;color:${dreamCol}">${dreamIcon} ${esc(dreamMsg)}</div>
  </div>`;

  return html;
}

function renderLearnings(ns) {
  if (!ns.learnings.length) {
    return '<div class="empty-state">No learnings recorded yet.</div>';
  }

  const supersededNote = (ns.supersededCount || 0) > 0
    ? `<div style="font-size:.72rem;color:var(--muted);margin-bottom:.5rem">
        ${ns.supersededCount} superseded (merged) learning${ns.supersededCount !== 1 ? 's' : ''} hidden
       </div>`
    : '';

  let corpusHealthHtml = '';
  if (ns.corpusHealth) {
    const ch    = ns.corpusHealth;
    const pct   = ch.score;
    const barCls = pct >= 75 ? 'ch-high' : pct >= 50 ? 'ch-mid' : 'ch-low';
    const details = [
      ch.unvalidatedHypotheses > 0 ? `${ch.unvalidatedHypotheses} unvalidated hypothesis${ch.unvalidatedHypotheses !== 1 ? 'es' : ''}` : null,
      `${ch.lowWeightCount} weight-1 (${Math.round(ch.lowWeightCount / ch.totalActive * 100)}%)`,
      ch.supersededCount > 0 ? `${ch.supersededCount} superseded` : null,
    ].filter(Boolean).join(' \\u00b7 ');
    corpusHealthHtml = `<div class="corpus-health">
      <span class="ch-label">Corpus health</span>
      <div class="ch-bar-wrap"><div class="ch-bar ${barCls}" style="width:${pct}%"></div></div>
      <span class="ch-score">${pct}</span>
      <span class="ch-detail">${esc(details)}</span>
    </div>`
  }

  const rows = ns.learnings.map((l, lIdx) => {
    const w    = l.weight || 1;
    const wCls = w >= 4 ? 'w-high' : w >= 2 ? 'w-mid' : 'w-low';
    const tags = (l.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const type = l.learning_type === 'hypothesis' ? 'hypothesis' : 'fact';
    const date = (l.date || l.logged_at || '').slice(0, 10) || '\\u2014';
    const conf = l.confidence ? ` <span style="color:var(--subtle);font-size:.68rem">${esc(l.confidence)}</span>` : '';
    const lidTitle = l.learning_id ? ` title="ID: ${esc(l.learning_id)}"` : '';
    let staleHtml = '';
    if (type === 'hypothesis' && !l.validation_result && date !== '\\u2014') {
      const ageDays = (Date.now() - new Date(date).getTime()) / 86400000;
      if (ageDays > 30) {
        staleHtml = ` <span style="color:var(--amber);font-size:.66rem" title="Unvalidated hypothesis \\u2014 ${Math.round(ageDays)}d old">\\u26a0 stale</span>`;
      }
    }
    const backRef  = (ns.backRefsByText  || {})[l.text || ''];
    const conflicts = (ns.conflictsByText || {})[l.text || ''] || [];
    let linkHtml = '';
    if (backRef) {
      linkHtml += `<div class="link-ref">\\u2190 propagated from <code>${esc(backRef.sourceNamespace)}</code></div>`;
    }
    for (const c of conflicts) {
      const other = c.sourceNamespace === ns.namespace ? c.targetNamespace : c.sourceNamespace;
      const icon  = c.decision === 'link' ? '\\u2194' : c.decision === 'merge' ? '\\u21d2' : '\\u2260';
      linkHtml += `<div class="link-ref">${icon} ${esc(c.decision)} \\u2014 <code>${esc(other)}</code></div>`;
    }
    return `
      <tr data-idx="${lIdx}"${lidTitle}>
        <td><span class="weight-dot"><span class="wdot ${wCls}"></span><span class="wnum">${w}</span></span></td>
        <td class="learning-text">${esc(l.text || '')}${linkHtml}</td>
        <td><div class="tags-cell">${tags}</div></td>
        <td><span class="type-badge type-${type}">${type}</span>${conf}${staleHtml}</td>
        <td style="color:var(--subtle);white-space:nowrap;font-size:.75rem">${date}</td>
      </tr>`;
  }).join('');

  const decayHtml = renderDecayTimeline(ns);
  return corpusHealthHtml + supersededNote + `
    <table class="learnings-table">
      <thead>
        <tr><th>Wt</th><th>Learning</th><th>Tags</th><th>Type</th><th>Date</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>` + decayHtml;
}

function renderDecayTimeline(ns) {
  const events = ns.decayHistory || [];
  if (!events.length) return '';
  const reasonLabel = r => r === 'dream_pass_weak' ? 'dream pass (weak)' : r === 'dream_pass_merge' ? 'dream pass (merged)' : esc(r);
  const items = events.map(e => {
    const date  = (e.timestamp || '').slice(0, 10);
    const count = e.removed_count || (e.removed_texts || []).length;
    const texts = (e.removed_texts || []).slice(0, 3);
    const more  = (e.removed_texts || []).length - texts.length;
    const preview = texts.map(t => `<li style="color:var(--muted);font-size:.7rem">${esc(t.length > 80 ? t.slice(0, 80) + '\\u2026' : t)}</li>`).join('');
    const moreNote = more > 0 ? `<li style="color:var(--subtle);font-size:.68rem">+${more} more</li>` : '';
    return `<div class="decay-event">
      <span class="decay-date">${date}</span>
      <span class="decay-count">${count} removed</span>
      <span class="decay-reason">${reasonLabel(e.reason || '')}</span>
      <ul class="decay-texts">${preview}${moreNote}</ul>
    </div>`;
  }).join('');
  return `<details class="decay-timeline" style="margin-top:1.25rem">
    <summary style="font-size:.75rem;color:var(--muted);cursor:pointer;user-select:none">
      Corpus maintenance &mdash; ${events.length} decay event${events.length !== 1 ? 's' : ''}
    </summary>
    <div style="margin-top:.5rem">${items}</div>
  </details>`;
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

// ── External signals ──────────────────────────────────────────────────────────

function renderExternalSignals(ns) {
  const signals = ns.externalSignals || [];
  if (!signals.length) {
    return '<div class="empty-state">No external research signals recorded yet.<br>Use the compass research pass (P11) to capture findings.</div>';
  }

  const items = signals.map(s => {
    const date    = (s.date || '').slice(0, 10) || '\\u2014';
    const tags    = (s.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const remit   = s.research_remit || {};
    let remitHtml = '';
    if (remit.focus_area) {
      remitHtml += `<div class="signal-remit">Focus: ${esc(remit.focus_area)}</div>`;
    }
    if (remit.hypothesis) {
      remitHtml += `<div class="signal-remit">Hypothesis: ${esc(remit.hypothesis)}</div>`;
    }
    return `<div class="signal-entry">
      <div class="signal-header">
        <span class="signal-date">${esc(date)}</span>
        <span class="signal-source">${esc(s.source || 'research')}</span>
        <div class="tags-cell" style="display:inline-flex">${tags}</div>
      </div>
      <div class="signal-text">${esc(s.text || '')}</div>
      ${remitHtml}
    </div>`;
  }).join('');

  return `<div class="signals-list">${items}</div>`;
}

// ── History timeline ──────────────────────────────────────────────────────────

function renderQualityBar(ns) {
  const qd = ns.qualityDist || {};
  const total = (qd.high || 0) + (qd.neutral || 0) + (qd.poor || 0);
  if (!total) return '';
  const pct = n => Math.round(n / total * 100);
  const segments = [
    { key: 'high',    color: '#38a86e', label: 'High' },
    { key: 'neutral', color: '#5a7a8a', label: 'Neutral' },
    { key: 'poor',    color: '#c0392b', label: 'Poor' },
  ].filter(s => qd[s.key] > 0);
  const barSegs = segments.map(s =>
    `<div style="width:${pct(qd[s.key])}%;background:${s.color};height:100%;display:inline-block;vertical-align:top"
          title="${s.label}: ${qd[s.key]} session${qd[s.key] !== 1 ? 's' : ''} (${pct(qd[s.key])}%)"></div>`
  ).join('');
  const legend = segments.map(s =>
    `<span style="color:${s.color}">${s.label} ${qd[s.key]}</span>`
  ).join('<span style="color:var(--muted)"> &#x00b7; </span>');
  return `<div style="margin-bottom:1rem">
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:.35rem">
      Session quality &mdash; ${total} total &nbsp; ${legend}
    </div>
    <div style="height:8px;border-radius:4px;overflow:hidden;background:var(--surface2)">${barSegs}</div>
  </div>`;
}

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

  return renderQualityBar(ns) + `<div class="timeline">${sessions}</div>`;
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
  ['overview', 'priorities', 'scorecard', 'dag', 'heatmap', 'timeline'].forEach(id => {
    document.getElementById('view-' + id).style.display = id === v ? '' : 'none';
    document.getElementById('vtab-' + id).classList.toggle('active', id === v);
  });
  if (v === 'priorities') renderPriorities();
  if (v === 'scorecard')  renderScorecard();
  if (v === 'dag')        renderDAG();
  if (v === 'heatmap')    renderHeatmap();
  if (v === 'timeline')   renderLearningTimeline();
}

// ── Attention queue (E9) ─────────────────────────────────────────────────────

function urgencyScore(ns) {
  let score = 0;
  if (ns.open) score += 30;
  const days = _daysSince(ns.open ? ns.lastOpen : ns.lastClose);
  if (days > 14) score += 25;
  else if (days > 7) score += 15;
  if (ns.goalRate !== null && ns.goalRate !== undefined) {
    if (ns.goalRate < 50) score += 20;
    else if (ns.goalRate < 75) score += 10;
  }
  if (ns.dreamDue) score += 12;
  const deferredCount = (ns.deferred || []).length;
  score += Math.min(deferredCount * 4, 20);
  if (ns.plannedActions && ns.plannedActions.length > 0) score += 8;
  if (ns.realityCompletenessScore != null && ns.realityCompletenessScore < 30) score += 8;
  return score;
}

function initAttentionQueue() {
  const grid = document.querySelector('.grid');
  if (!grid) return;
  const cards = Array.from(grid.children);
  cards.sort((a, b) => {
    const ia = parseInt(a.dataset.idx, 10);
    const ib = parseInt(b.dataset.idx, 10);
    return urgencyScore(NS[ib]) - urgencyScore(NS[ia]);
  });
  cards.forEach(c => grid.appendChild(c));
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

    if (ns.corpusHealth && ns.corpusHealth.score < 50) {
      score += 12;
      reasons.push({ icon: '🧪', text: `Low corpus health (${ns.corpusHealth.score}/100) — validate hypotheses or boost learnings` });
    }

    if ((ns.codeReviewDeferCount || 0) >= 2) {
      score += 10;
      reasons.push({ icon: '🔬', text: `Code review deferred ${ns.codeReviewDeferCount}x — overdue` });
    }
    if ((ns.researchDeferCount || 0) >= 2) {
      score += 8;
      reasons.push({ icon: '🔍', text: `External research deferred ${ns.researchDeferCount}x — overdue` });
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
        ${(() => {
          const er = ns.explorationRatio;
          if (!er || er.ratio == null) return '';
          const exp   = er.explore || 0;
          const tot   = er.total   || 1;
          const xpPct = Math.round(exp / tot * 100);
          const exPct = 100 - xpPct;
          const col   = er.low ? 'var(--amber)' : 'var(--green)';
          return `<div style="margin-top:.5rem">
            <div style="font-size:.7rem;color:var(--muted);margin-bottom:.25rem">E/X split (last ${er.sessionsWithTypes} typed sessions)</div>
            <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;background:var(--surface2)">
              <div style="width:${exPct}%;background:var(--green);opacity:.7" title="Exploit: ${exPct}%"></div>
              <div style="width:${xpPct}%;background:${col}" title="Explore: ${xpPct}%"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:.68rem;color:var(--muted);margin-top:.2rem">
              <span style="color:var(--green)">exploit ${exPct}%</span>
              <span style="color:${col}">explore ${xpPct}%</span>
            </div>
          </div>`;
        })()}
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

initAttentionQueue();

// ── Dependency Graph (DAG) ────────────────────────────────────────────────────

const EDGE_META = {
  dep:        { color: '#d29922', label: 'Dependency',    dash: '',    arrow: true,  title: 'directed' },
  shared:     { color: '#58a6ff', label: 'Shared themes', dash: '5,3', arrow: false, title: 'shared tag themes (≥2)' },
  conflict:   { color: '#f85149', label: 'Theme overlap', dash: '2,3', arrow: false, title: 'high-weight learning overlap' },
  concurrent: { color: '#3fb950', label: 'Concurrent',    dash: '',    arrow: false, title: 'both sessions open' },
};

const _dag = { nodes: [], edges: [], nodeMap: new Map(), raf: null, tick: 0, maxTick: 280, svgW: 900, svgH: 530, rendered: false };
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

// ── Heatmap ───────────────────────────────────────────────────────────────────

function wireHeatmapTooltip(container, cellSelector) {
  const tooltip = document.getElementById('heatmap-tooltip');
  container.addEventListener('mousemove', ev => {
    const cell = ev.target.closest(cellSelector);
    if (!cell) { tooltip.style.display = 'none'; return; }
    tooltip.textContent = cell.dataset.tip;
    tooltip.style.display = 'block';
    const x = ev.clientX + 14, y = ev.clientY + 14;
    const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
    tooltip.style.left = (x + tw > window.innerWidth  - 8 ? ev.clientX - tw - 14 : x) + 'px';
    tooltip.style.top  = (y + th > window.innerHeight - 8 ? ev.clientY - th - 14 : y) + 'px';
  });
  container.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
}

function renderHeatmap() {
  const container = document.getElementById('view-heatmap');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';
  container.innerHTML = `<div class="hmap-toolbar">
    <button class="dag-btn active" id="hbtn-sessions"   onclick="switchHeatmap('sessions')">Session Activity</button>
    <button class="dag-btn"        id="hbtn-goals"      onclick="switchHeatmap('goals')">Goal Completion</button>
    <button class="dag-btn"        id="hbtn-velocity"   onclick="switchHeatmap('velocity')">Velocity</button>
    <button class="dag-btn"        id="hbtn-goaltypes"  onclick="switchHeatmap('goaltypes')">Goal Types</button>
    <button class="dag-btn"        id="hbtn-planning"   onclick="switchHeatmap('planning')">Planning</button>
  </div>
  <div id="hpanel-sessions"></div>
  <div id="hpanel-goals"      style="display:none"></div>
  <div id="hpanel-velocity"   style="display:none"></div>
  <div id="hpanel-goaltypes"  style="display:none"></div>
  <div id="hpanel-planning"   style="display:none"></div>`;
  renderSessionHeatmapPanel();
}

function switchHeatmap(name) {
  ['sessions', 'goals', 'velocity', 'goaltypes', 'planning'].forEach(id => {
    document.getElementById('hpanel-' + id).style.display = id === name ? '' : 'none';
    document.getElementById('hbtn-' + id).classList.toggle('active', id === name);
  });
  if (name === 'goals')     renderGoalHeatmapPanel();
  if (name === 'velocity')  renderVelocityPanel();
  if (name === 'goaltypes') renderGoalTypesPanel();
  if (name === 'planning')  renderPlanningPanel();
}

function renderSessionHeatmapPanel() {
  const container = document.getElementById('hpanel-sessions');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  // Collect all (namespace, YYYY-MM) session counts from full sessionDates
  const periodSet = new Set();
  const nsMap = {};  // namespace -> { 'YYYY-MM': count }
  NS.forEach(ns => {
    nsMap[ns.namespace] = {};
    (ns.sessionDates || []).forEach(d => {
      const period = d.slice(0, 7);  // 'YYYY-MM'
      periodSet.add(period);
      nsMap[ns.namespace][period] = (nsMap[ns.namespace][period] || 0) + 1;
    });
  });

  const periods = Array.from(periodSet).sort();
  if (!periods.length) {
    container.innerHTML = '<p style="padding:1rem;color:var(--muted)">No session history to display.</p>';
    return;
  }

  // Sort namespaces by total sessions descending
  const nsSorted = NS.slice().sort((a, b) => (b.sessionCount || 0) - (a.sessionCount || 0));

  // Colour levels: 0 = empty, 1–4 scaled to max count in any single cell
  const allCounts = nsSorted.flatMap(ns => periods.map(p => nsMap[ns.namespace][p] || 0));
  const maxCount = Math.max(1, ...allCounts);
  function level(count) {
    if (!count) return 0;
    return Math.min(4, Math.ceil(count / maxCount * 4));
  }

  // Build grid: col 0 = ns labels, cols 1..N = period columns
  const cols = 1 + periods.length;
  let html = `<div class="heatmap-wrap">
  <div class="heatmap-grid" style="grid-template-columns: minmax(120px,auto) repeat(${periods.length}, 28px)">`;

  // Header row: corner + month labels
  html += '<div class="heatmap-corner"></div>';
  periods.forEach(p => {
    const [yr, mo] = p.split('-');
    const label = new Date(+yr, +mo - 1, 1).toLocaleString('default', { month: 'short' }) + '\\u2019' + yr.slice(2);
    html += `<div class="heatmap-col-label">${label}</div>`;
  });

  // Data rows
  nsSorted.forEach(ns => {
    const openCls = ns.open ? ' open-ns' : '';
    const nsName = esc(ns.namespace);
    html += `<div class="heatmap-ns-label${openCls}">${nsName}</div>`;
    periods.forEach(p => {
      const count = nsMap[ns.namespace][p] || 0;
      const lv = level(count);
      const tip = esc(count
        ? `${ns.namespace} · ${p} · ${count} session${count > 1 ? 's' : ''}`
        : `${ns.namespace} · ${p} · no sessions`);
      html += `<div class="heatmap-cell" data-count="${count}" data-level="${lv}" data-tip="${tip}"></div>`;
    });
  });

  html += `</div>
  <div class="heatmap-legend">
    <span>Less</span>
    <div class="heatmap-legend-cell" style="background:var(--surface2)"></div>
    <div class="heatmap-legend-cell" style="background:#1a4731"></div>
    <div class="heatmap-legend-cell" style="background:#206040"></div>
    <div class="heatmap-legend-cell" style="background:#2a8055"></div>
    <div class="heatmap-legend-cell" style="background:#38a86e"></div>
    <span>More</span>
    <span style="margin-left:1rem;color:var(--muted)">1 cell = 1 month · max ${maxCount} session${maxCount > 1 ? 's' : ''}</span>
  </div>
</div>`;

  container.innerHTML = html;

  wireHeatmapTooltip(container, '.heatmap-cell');
}

// ── Learning timeline ─────────────────────────────────────────────────────────

function renderLearningTimeline() {
  const container = document.getElementById('view-timeline');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  const allLearnings = [];
  NS.forEach(ns => {
    (ns.learnings || []).forEach(l => { if (l.date) allLearnings.push(l); });
  });

  if (!allLearnings.length) {
    container.innerHTML = '<p style="padding:1rem;color:var(--muted)">No learnings with dates to display.</p>';
    return;
  }

  const monthSet = new Set();
  allLearnings.forEach(l => {
    const m = l.date.slice(0, 7);
    if (m.length === 7) monthSet.add(m);
  });
  const months = Array.from(monthSet).sort();

  const tagCounts = {};
  allLearnings.forEach(l => {
    (l.tags || []).forEach(t => { tagCounts[t] = (tagCounts[t] || 0) + 1; });
  });
  const topTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 7).map(e => e[0]);

  const byMonthTag = {};
  months.forEach(m => { byMonthTag[m] = {}; });
  allLearnings.forEach(l => {
    const m = l.date.slice(0, 7);
    if (!byMonthTag[m]) return;
    (l.tags || []).forEach(t => {
      if (topTags.includes(t)) byMonthTag[m][t] = (byMonthTag[m][t] || 0) + 1;
    });
  });

  const cumulative = {};
  topTags.forEach(t => {
    let sum = 0;
    cumulative[t] = months.map(m => { sum += byMonthTag[m][t] || 0; return sum; });
  });

  const maxVal = Math.max(1, ...topTags.flatMap(t => cumulative[t]));

  const PAD_L = 32, PAD_R = 20, PAD_T = 16, PAD_B = 42;
  const W = Math.max(500, months.length * 52 + PAD_L + PAD_R);
  const H = 250;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const COLORS = ['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#79c0ff','#56d364'];

  let svg = `<svg class="timeline-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">`;

  for (let i = 0; i <= 4; i++) {
    const y = PAD_T + chartH - (i / 4) * chartH;
    svg += `<line x1="${PAD_L}" y1="${y.toFixed(1)}" x2="${W - PAD_R}" y2="${y.toFixed(1)}" stroke="var(--border)" stroke-width="1"/>`;
    svg += `<text x="${PAD_L - 4}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="var(--muted)" font-size="9" font-family="monospace">${Math.round(maxVal * i / 4)}</text>`;
  }

  months.forEach((m, i) => {
    const x = PAD_L + (i + 0.5) * (chartW / months.length);
    const [yr, mo] = m.split('-');
    const label = new Date(+yr, +mo - 1, 1).toLocaleString('default', { month: 'short' }) + '\\u2019' + yr.slice(2);
    svg += `<text x="${x.toFixed(1)}" y="${H - 6}" text-anchor="middle" fill="var(--muted)" font-size="9" font-family="monospace">${label}</text>`;
  });

  topTags.forEach((tag, ti) => {
    const color = COLORS[ti % COLORS.length];
    const pts = cumulative[tag].map((val, i) => {
      const x = PAD_L + (i + 0.5) * (chartW / months.length);
      const y = PAD_T + chartH - (val / maxVal) * chartH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    if (pts) svg += `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    cumulative[tag].forEach((val, i) => {
      const x = PAD_L + (i + 0.5) * (chartW / months.length);
      const y = PAD_T + chartH - (val / maxVal) * chartH;
      svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="${color}" stroke="var(--bg)" stroke-width="1.5"><title>${esc(tag)}: ${val} total by ${months[i]}</title></circle>`;
    });
  });

  svg += '</svg>';

  const legend = topTags.map((t, i) =>
    `<div class="timeline-legend-item"><div class="timeline-legend-swatch" style="background:${COLORS[i % COLORS.length]}"></div><span>${esc(t)}</span></div>`
  ).join('');

  container.innerHTML = `<div class="timeline-wrap">
    <div style="padding:.5rem 0 .5rem;font-size:.78rem;color:var(--muted)">Cumulative learnings by tag &#x00b7; all namespaces &#x00b7; hover dots for details</div>
    <div class="timeline-chart-area">${svg}</div>
    <div class="timeline-legend">${legend}</div>
  </div>`;
}

// ── Scorecard ─────────────────────────────────────────────────────────────────

function renderScorecard() {
  const container = document.getElementById('view-scorecard');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  const AXES = [
    { key: 'recency',    label: 'Recency',    tip: 'Days since last session (recent = high)' },
    { key: 'discipline', label: 'Discipline', tip: 'Avg goal completion %' },
    { key: 'maturity',   label: 'Maturity',   tip: 'Reality completeness score (% of bullets marked done)' },
    { key: 'learning',   label: 'Learning',   tip: 'Learnings per session' },
    { key: 'focus',      label: 'Focus',      tip: 'Low deferred items (fewer = high)' },
  ];

  // Raw scores
  const rows = NS.map(ns => {
    const days       = _daysSince(ns.open ? ns.lastOpen : ns.lastClose);
    const recency    = Math.max(0, Math.min(100, 100 - days * (100 / 30)));
    const discipline = (ns.goalRate !== null && ns.goalRate !== undefined) ? ns.goalRate : 50;
    const maturity   = ns.realityCompletenessScore != null ? ns.realityCompletenessScore : 50;
    const learning   = ns.sessionCount > 0 ? (ns.learnings || []).length / ns.sessionCount : 0;
    const focus      = 1 / (1 + (ns.deferred || []).length);
    return { ns, recency, discipline, maturity, learning, focus };
  });

  // Normalise maturity, learning, focus to 0–100
  ['maturity', 'learning', 'focus'].forEach(k => {
    const vals = rows.map(r => r[k]);
    const min = Math.min(...vals), max = Math.max(...vals), range = max - min;
    rows.forEach(r => { r[k] = range === 0 ? 100 : (r[k] - min) / range * 100; });
  });

  // Overall health = mean across axes
  rows.forEach(r => {
    r.health = AXES.reduce((s, a) => s + r[a.key], 0) / AXES.length;
  });
  rows.sort((a, b) => b.health - a.health);

  function healthColor(h) {
    return h >= 68 ? '#3fb950' : h >= 40 ? '#d29922' : '#f85149';
  }

  // ── Parallel coordinates SVG ─────────────────────────────────────────────

  const PAD_L = 150, PAD_R = 28, PAD_T = 48, PAD_B = 28;
  const W = 900, H = 370;
  const chartW = W - PAD_L - PAD_R, chartH = H - PAD_T - PAD_B;
  const axisX  = AXES.map((_, i) => PAD_L + i * chartW / (AXES.length - 1));

  function yFor(val) { return PAD_T + (1 - val / 100) * chartH; }

  let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block;overflow:visible">`;

  // Horizontal guides at 0, 50, 100
  [0, 50, 100].forEach(v => {
    const y = yFor(v);
    const dash = v === 50 ? ' stroke-dasharray="3,3"' : '';
    svg += `<line x1="${PAD_L}" y1="${y.toFixed(1)}" x2="${W - PAD_R}" y2="${y.toFixed(1)}" stroke="var(--border)" stroke-width="1"${dash}/>`;
    svg += `<text x="${PAD_L - 6}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="var(--subtle)" font-size="9" font-family="monospace">${v}</text>`;
  });

  // Vertical axis lines + labels
  AXES.forEach((ax, i) => {
    const x = axisX[i];
    svg += `<line x1="${x}" y1="${PAD_T}" x2="${x}" y2="${(PAD_T + chartH)}" stroke="var(--border)" stroke-width="1.5"/>`;
    svg += `<text x="${x}" y="${PAD_T - 10}" text-anchor="middle" fill="var(--muted)" font-size="11" font-family="monospace" font-weight="600"><title>${esc(ax.tip)}</title>${esc(ax.label)}</text>`;
  });

  // Namespace polylines (low opacity base; highlighted on hover)
  rows.forEach((r, ri) => {
    const pts = AXES.map((ax, i) => `${axisX[i].toFixed(1)},${yFor(r[ax.key]).toFixed(1)}`).join(' ');
    const col = healthColor(r.health);
    svg += `<polyline id="scard-line-${ri}" class="scard-line" points="${pts}" fill="none" stroke="${col}" stroke-width="1.8" stroke-opacity="0.5" stroke-linejoin="round"><title>${esc(r.ns.namespace)} — health: ${Math.round(r.health)}%</title></polyline>`;
  });

  // Namespace labels anchored to first axis (Recency)
  rows.forEach((r, ri) => {
    const y = yFor(r.recency);
    const col = healthColor(r.health);
    const name = r.ns.namespace.length > 17 ? r.ns.namespace.slice(0, 16) + '\\u2026' : r.ns.namespace;
    svg += `<text class="scard-label" data-ri="${ri}" x="${PAD_L - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="${col}" font-size="9.5" font-family="monospace" style="cursor:default">${esc(name)}</text>`;
  });

  svg += '</svg>';

  // ── Ranked table ──────────────────────────────────────────────────────────

  const headerCols = AXES.map(ax =>
    `<div class="scard-bar-col" style="font-size:.6rem;color:var(--subtle);text-align:center;padding-bottom:.1rem" title="${esc(ax.tip)}">${esc(ax.label)}</div>`
  ).join('');
  const header = `<div class="scard-header">
    <span style="min-width:1.4rem;flex-shrink:0"></span>
    <span style="min-width:10rem;flex-shrink:0">Namespace</span>
    <span style="min-width:2.8rem;flex-shrink:0;text-align:right">Health</span>
    <div class="scard-bars">${headerCols}</div>
  </div>`;

  const tableRows = rows.map((r, ri) => {
    const col  = healthColor(r.health);
    const bars = AXES.map(ax => {
      const pct = Math.round(r[ax.key]);
      return `<div class="scard-bar-col" title="${esc(ax.label)}: ${pct}%">
        <div class="scard-bar-bg"><div class="scard-bar-fg" style="width:${pct}%;background:${col}"></div></div>
      </div>`;
    }).join('');
    return `<div class="scard-row" id="scard-row-${ri}" data-ri="${ri}">
      <span class="scard-rank">${ri + 1}</span>
      <span class="scard-ns" style="color:${col}">${esc(r.ns.namespace)}</span>
      <span class="scard-score" style="color:${col}">${Math.round(r.health)}%</span>
      <div class="scard-bars">${bars}</div>
    </div>`;
  }).join('');

  container.innerHTML = `<div class="scard-wrap">
    <div style="font-size:.78rem;color:var(--muted);padding:.25rem 0 .75rem">
      Namespace fitness across 5 axes &#x00b7; hover row or line to highlight &#x00b7; sorted by overall health score
    </div>
    <div class="scard-chart-area">${svg}</div>
    ${header}
    <div class="scard-table">${tableRows}</div>
  </div>`;

  // ── Hover wiring ─────────────────────────────────────────────────────────

  const lines    = container.querySelectorAll('.scard-line');
  const labels   = container.querySelectorAll('.scard-label');
  const rowEls   = container.querySelectorAll('.scard-row');

  function highlightScard(ri, on) {
    lines.forEach((ln, i) => {
      ln.setAttribute('stroke-opacity', on ? (i === ri ? '1'   : '0.08') : '0.5');
      ln.setAttribute('stroke-width',   on ? (i === ri ? '2.8' : '1.2')  : '1.8');
    });
    labels.forEach((lb, i) => {
      lb.setAttribute('font-size', on && i === ri ? '10.5' : '9.5');
      lb.setAttribute('font-weight', on && i === ri ? '700' : '400');
    });
    rowEls.forEach((el, i) => { el.style.opacity = on ? (i === ri ? '1' : '0.35') : '1'; });
  }

  lines.forEach((ln, ri)  => { ln.addEventListener('mouseenter', () => highlightScard(ri, true)); ln.addEventListener('mouseleave', () => highlightScard(ri, false)); });
  rowEls.forEach(el => {
    const ri = parseInt(el.dataset.ri);
    el.addEventListener('mouseenter', () => highlightScard(ri, true));
    el.addEventListener('mouseleave', () => highlightScard(ri, false));
  });
}

// ── E18: Goal type stacked timeline ───────────────────────────────────────────

function renderGoalTypesPanel() {
  const container = document.getElementById('hpanel-goaltypes');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  // Collect per-namespace per-session E/X data
  const rows = NS.filter(ns => (ns.goalTypeBySession || []).length > 0);
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state" style="padding:2rem">No goal type data yet. Use P23 goal type tagging (E/X) during session open to populate this chart.</div>';
    return;
  }

  const BAR_W = 14, BAR_GAP = 3, NS_GAP = 24, LABEL_H = 16, BAR_MAX_H = 80, PAD_LEFT = 120, PAD_TOP = 12;

  let svgParts = [];
  let y = PAD_TOP;

  rows.forEach(ns => {
    const sessions = ns.goalTypeBySession;
    const maxTotal = Math.max(...sessions.map(s => s.exploit + s.explore), 1);

    // Namespace label
    svgParts.push(`<text x="${PAD_LEFT - 8}" y="${y + BAR_MAX_H / 2 + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${esc(ns.namespace)}</text>`);

    sessions.forEach((s, i) => {
      const total  = s.exploit + s.explore;
      const exH    = Math.round(s.exploit / maxTotal * BAR_MAX_H);
      const xpH    = Math.round(s.explore  / maxTotal * BAR_MAX_H);
      const x      = PAD_LEFT + i * (BAR_W + BAR_GAP);
      const exY    = y + (BAR_MAX_H - exH - xpH);
      const xpY    = y + (BAR_MAX_H - xpH);
      const tip    = `${esc(s.date)}: ${s.exploit} exploit, ${s.explore} explore`;

      if (xpH > 0)
        svgParts.push(`<rect x="${x}" y="${xpY}" width="${BAR_W}" height="${xpH}" fill="var(--blue)" opacity=".8"><title>${tip}</title></rect>`);
      if (exH > 0)
        svgParts.push(`<rect x="${x}" y="${exY}" width="${BAR_W}" height="${exH}" fill="var(--green)" opacity=".7"><title>${tip}</title></rect>`);
      if (total === 0)
        svgParts.push(`<rect x="${x}" y="${y + BAR_MAX_H - 2}" width="${BAR_W}" height="2" fill="var(--subtle)"><title>${esc(s.date)}: no type data</title></rect>`);

      // Date label on first and last bar only
      if (i === 0 || i === sessions.length - 1) {
        svgParts.push(`<text x="${x + BAR_W / 2}" y="${y + BAR_MAX_H + LABEL_H}" text-anchor="middle" font-size="9" fill="var(--muted)">${esc(s.date.slice(5))}</text>`);
      }
    });

    y += BAR_MAX_H + LABEL_H + NS_GAP;
  });

  const totalW = PAD_LEFT + Math.max(...rows.map(ns => ns.goalTypeBySession.length)) * (BAR_W + BAR_GAP) + 20;
  const totalH = y + 20;

  const legend = `<div style="display:flex;gap:1rem;font-size:.75rem;color:var(--muted);margin-bottom:.75rem">
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--green);opacity:.7;border-radius:2px;margin-right:4px"></span>exploit</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--blue);opacity:.8;border-radius:2px;margin-right:4px"></span>explore</span>
    <span style="color:var(--subtle)">bar height proportional to goal count per session</span>
  </div>`;

  container.innerHTML = `<div style="padding:1rem">
    <h3 style="font-size:.85rem;margin-bottom:.5rem">Goal type timeline — exploit vs explore per session</h3>
    ${legend}
    <div style="overflow-x:auto">
      <svg viewBox="0 0 ${totalW} ${totalH}" width="${totalW}" height="${totalH}" style="display:block">${svgParts.join('')}</svg>
    </div>
  </div>`;
}

// ── E15: Planning discipline — carry-forward trend ────────────────────────────

function renderPlanningPanel() {
  const container = document.getElementById('hpanel-planning');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  const rows = NS.filter(ns => (ns.carryForwardTrend || []).length > 0);
  if (!rows.length) {
    container.innerHTML = '<div class="empty-state" style="padding:2rem">No session history to analyse yet.</div>';
    return;
  }

  const BAR_W = 12, BAR_GAP = 3, NS_GAP = 24, LABEL_H = 16, BAR_MAX_H = 60, PAD_LEFT = 120, PAD_TOP = 12;

  let svgParts = [];
  let y = PAD_TOP;

  rows.forEach(ns => {
    const sessions  = ns.carryForwardTrend;
    const maxVal    = Math.max(...sessions.map(s => Math.max(s.carryForward, s.goalsCompleted)), 1);

    svgParts.push(`<text x="${PAD_LEFT - 8}" y="${y + BAR_MAX_H / 2 + 4}" text-anchor="end" font-size="11" fill="var(--muted)">${esc(ns.namespace)}</text>`);

    sessions.forEach((s, i) => {
      const cfH  = Math.round(s.carryForward   / maxVal * BAR_MAX_H);
      const gcH  = Math.round(s.goalsCompleted / maxVal * BAR_MAX_H);
      const x    = PAD_LEFT + i * (BAR_W + BAR_GAP);
      const tip  = `${esc(s.date)}: ${s.goalsCompleted} completed, ${s.carryForward} carried forward`;

      // completed bar (green, background)
      if (gcH > 0)
        svgParts.push(`<rect x="${x}" y="${y + BAR_MAX_H - gcH}" width="${BAR_W}" height="${gcH}" fill="var(--green)" opacity=".35"><title>${tip}</title></rect>`);
      // carry-forward bar (amber, overlay)
      if (cfH > 0)
        svgParts.push(`<rect x="${x}" y="${y + BAR_MAX_H - cfH}" width="${BAR_W}" height="${cfH}" fill="var(--amber)" opacity=".8"><title>${tip}</title></rect>`);

      if (i === 0 || i === sessions.length - 1) {
        svgParts.push(`<text x="${x + BAR_W / 2}" y="${y + BAR_MAX_H + LABEL_H}" text-anchor="middle" font-size="9" fill="var(--muted)">${esc(s.date.slice(5))}</text>`);
      }
    });

    y += BAR_MAX_H + LABEL_H + NS_GAP;
  });

  const totalW = PAD_LEFT + Math.max(...rows.map(ns => ns.carryForwardTrend.length)) * (BAR_W + BAR_GAP) + 20;
  const totalH = y + 20;

  const legend = `<div style="display:flex;gap:1rem;font-size:.75rem;color:var(--muted);margin-bottom:.75rem">
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--green);opacity:.35;border-radius:2px;margin-right:4px"></span>goals completed</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--amber);opacity:.8;border-radius:2px;margin-right:4px"></span>carried forward (incomplete)</span>
    <span style="color:var(--subtle)">lower amber = better planning discipline</span>
  </div>`;

  container.innerHTML = `<div style="padding:1rem">
    <h3 style="font-size:.85rem;margin-bottom:.5rem">Planning discipline — carry-forward vs goals completed</h3>
    ${legend}
    <div style="overflow-x:auto">
      <svg viewBox="0 0 ${totalW} ${totalH}" width="${totalW}" height="${totalH}" style="display:block">${svgParts.join('')}</svg>
    </div>
  </div>`;
}

// ── Session velocity chart (stacked bars, all namespaces) ────────────────────

function renderVelocityPanel() {
  const container = document.getElementById('hpanel-velocity');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  // Build month -> { ns: count } from all sessionDates, last 12 months
  const allMonths = new Set();
  NS.forEach(ns => (ns.sessionDates || []).forEach(d => allMonths.add(d.slice(0, 7))));
  const months = Array.from(allMonths).sort().slice(-12);
  if (!months.length) {
    container.innerHTML = '<p style="padding:1rem;color:var(--muted)">No session data available.</p>';
    return;
  }

  const activeNS = NS.filter(ns => !SYSTEM_NS.has(ns.namespace.toLowerCase()));

  // Tally counts per namespace per month
  const counts = {};  // ns.namespace -> [count per month]
  activeNS.forEach(ns => {
    const byMonth = {};
    (ns.sessionDates || []).forEach(d => {
      const m = d.slice(0, 7);
      if (allMonths.has(m)) byMonth[m] = (byMonth[m] || 0) + 1;
    });
    counts[ns.namespace] = months.map(m => byMonth[m] || 0);
  });

  // Stacked totals per month
  const totals = months.map((_, mi) =>
    activeNS.reduce((s, ns) => s + counts[ns.namespace][mi], 0)
  );
  const maxTotal = Math.max(1, ...totals);

  // Colour palette (CSS variable names fallback to fixed hues)
  const palette = [
    '#38bdf8','#34d399','#f59e0b','#f87171','#a78bfa',
    '#fb923c','#e879f9','#4ade80','#60a5fa','#fbbf24',
    '#94a3b8','#f472b6',
  ];

  const W = 600, H = 200, PL = 30, PB = 32, PT = 12, PR = 10;
  const chartW = W - PL - PR;
  const chartH = H - PT - PB;
  const barW   = Math.floor(chartW / months.length * 0.72);
  const gap    = chartW / months.length;

  // Build SVG bar segments per namespace (bottom-up stacking)
  let barsSvg = '';
  const nsStacks = months.map(() => 0);  // running y-offset per month slot

  activeNS.forEach((ns, ni) => {
    const colour = palette[ni % palette.length];
    months.forEach((m, mi) => {
      const c = counts[ns.namespace][mi];
      if (!c) return;
      const barH  = Math.round(c / maxTotal * chartH);
      const x     = PL + Math.round(mi * gap + (gap - barW) / 2);
      const yBase = PT + chartH - nsStacks[mi];
      const y     = yBase - barH;
      nsStacks[mi] += barH;
      // Use data attributes and title for tooltip — no inline event handlers
      barsSvg += `<rect class="vel-bar" x="${x}" y="${y}" width="${barW}" height="${barH}"
        fill="${colour}" rx="1"
        data-ns="${esc(ns.namespace)}" data-month="${esc(m)}" data-count="${c}">
        <title>${esc(ns.namespace)} · ${esc(m)}: ${c} session${c !== 1 ? 's' : ''}</title>
      </rect>`;
    });
  });

  // X-axis labels (month names)
  const monthLabels = months.map((m, mi) => {
    const x   = PL + Math.round(mi * gap + gap / 2);
    const lbl = m.slice(5);  // MM portion
    return `<text x="${x}" y="${H - 6}" text-anchor="middle" class="vel-label">${esc(lbl)}</text>`;
  }).join('');

  // Y-axis gridlines
  const gridLines = [0.25, 0.5, 0.75, 1].map(f => {
    const y   = PT + chartH - Math.round(f * chartH);
    const val = Math.round(f * maxTotal);
    return `<line x1="${PL}" y1="${y}" x2="${W - PR}" y2="${y}" class="vel-grid"/>
      <text x="${PL - 3}" y="${y + 4}" text-anchor="end" class="vel-label">${val}</text>`;
  }).join('');

  // Legend
  const legendItems = activeNS.map((ns, ni) => {
    const colour = palette[ni % palette.length];
    return `<span class="vel-legend-item">
      <span class="vel-legend-dot" style="background:${colour}"></span>${esc(ns.namespace)}
    </span>`;
  }).join('');

  container.innerHTML = `
    <div style="padding:.75rem 1rem 0">
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;display:block">
        <style>
          .vel-bar { opacity:.85; transition:opacity .15s; }
          .vel-bar:hover { opacity:1; }
          .vel-grid { stroke:var(--border); stroke-width:1; }
          .vel-label { fill:var(--muted); font-size:9px; font-family:inherit; }
        </style>
        ${gridLines}
        ${barsSvg}
        ${monthLabels}
      </svg>
      <div class="vel-legend">${legendItems}</div>
    </div>`;
}

// ── Goal completion heatmap ───────────────────────────────────────────────────

function renderGoalHeatmapPanel() {
  const container = document.getElementById('hpanel-goals');
  if (container.dataset.rendered) return;
  container.dataset.rendered = '1';

  const periodSet = new Set();
  const nsMap = {};
  NS.forEach(ns => {
    nsMap[ns.namespace] = ns.goalByMonth || {};
    Object.keys(nsMap[ns.namespace]).forEach(m => periodSet.add(m));
  });

  const periods = Array.from(periodSet).sort();
  if (!periods.length) {
    container.innerHTML = '<p style="padding:1rem;color:var(--muted)">No goal completion data yet — close a few sessions with goals to populate this view.</p>';
    return;
  }

  const nsSorted = NS.slice().sort((a, b) => (b.sessionCount || 0) - (a.sessionCount || 0));

  function qlevel(rate) {
    if (rate === undefined || rate === null) return 0;
    if (rate <= 25) return 1;
    if (rate <= 50) return 2;
    if (rate <= 75) return 3;
    return 4;
  }

  let html = `<div class="heatmap-wrap">
  <div class="heatmap-grid" style="grid-template-columns: minmax(120px,auto) repeat(${periods.length}, 28px)">`;

  html += '<div class="heatmap-corner"></div>';
  periods.forEach(p => {
    const [yr, mo] = p.split('-');
    const label = new Date(+yr, +mo - 1, 1).toLocaleString('default', { month: 'short' }) + '\\u2019' + yr.slice(2);
    html += `<div class="heatmap-col-label">${label}</div>`;
  });

  nsSorted.forEach(ns => {
    const openCls = ns.open ? ' open-ns' : '';
    const byMonth = nsMap[ns.namespace];
    html += `<div class="heatmap-ns-label${openCls}">${esc(ns.namespace)}</div>`;
    periods.forEach(p => {
      const rate = byMonth[p];
      const ql = qlevel(rate);
      const tipText = rate !== undefined
        ? `${ns.namespace} \\u00b7 ${p} \\u00b7 ${rate}% avg completion`
        : `${ns.namespace} \\u00b7 ${p} \\u00b7 no data`;
      html += `<div class="goal-cell" data-qlevel="${ql}" data-tip="${esc(tipText)}"></div>`;
    });
  });

  html += `</div>
  <div class="heatmap-legend">
    <span>0%</span>
    <div class="heatmap-legend-cell" style="background:var(--surface2)"></div>
    <div class="heatmap-legend-cell" style="background:#0d2847"></div>
    <div class="heatmap-legend-cell" style="background:#154075"></div>
    <div class="heatmap-legend-cell" style="background:#1a5ba0"></div>
    <div class="heatmap-legend-cell" style="background:#2679cc"></div>
    <span>100%</span>
    <span style="margin-left:1rem;color:var(--muted)">1 cell = 1 month &#x00b7; colour = avg goal completion %</span>
  </div>
</div>`;

  container.innerHTML = html;

  wireHeatmapTooltip(container, '.goal-cell');
}

function renderDAG() {
  if (_dag.raf) { cancelAnimationFrame(_dag.raf); _dag.raf = null; }

  // Re-activation: DOM already exists — resume sim from current positions, don't rebuild
  if (_dag.rendered) {
    if (_dag.tick < _dag.maxTick) _dag.raf = requestAnimationFrame(dagSimStep);
    dagUpdatePositions();
    return;
  }

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
  const W = _dag.svgW, H = _dag.svgH;
  Object.assign(_dag, { nodes: nodeData, edges: allEdges, nodeMap, tick: 0 });
  dagInitPositions();

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

  _dag.rendered = true;
  _dag.raf = requestAnimationFrame(dagSimStep);
  dagUpdatePositions();
}

function toggleDAGSystem() {
  _dagShowSystem = !_dagShowSystem;
  _dag.rendered = false;
  renderDAG();
}

// Seed positions using topological layers (depends/conflict edges determine depth).
// All nodes with no incoming directed edges become roots (top); leaves sink to bottom.
// Nodes sharing a layer are spread evenly across the full canvas width.
function dagInitPositions() {
  const { nodes, edges, nodeMap, svgW, svgH } = _dag;
  const W = svgW, H = svgH, N = nodes.length;
  const inDeg = new Array(N).fill(0);
  const adj   = Array.from({length: N}, () => []);
  edges.forEach(e => {
    if (e.type !== 'depends' && e.type !== 'conflict') return;
    const ai = nodeMap.get(e.source), bi = nodeMap.get(e.target);
    if (ai == null || bi == null) return;
    inDeg[bi]++; adj[ai].push(bi);
  });
  const layer = new Array(N).fill(0);
  const q = []; inDeg.forEach((d, i) => { if (d === 0) q.push(i); });
  for (let qi = 0; qi < q.length; qi++) {
    const cur = q[qi];
    adj[cur].forEach(nb => {
      layer[nb] = Math.max(layer[nb], layer[cur] + 1);
      inDeg[nb]--;
      if (inDeg[nb] === 0) q.push(nb);
    });
  }
  const maxLayer = Math.max(...layer, 0);
  const layerCount = new Array(maxLayer + 1).fill(0);
  layer.forEach(l => layerCount[l]++);
  const layerIdx = new Array(maxLayer + 1).fill(0);
  const PAD = 72;
  nodes.forEach((n, i) => {
    const l = layer[i], cnt = layerCount[l], idx = layerIdx[l]++;
    n.x = PAD + (W - PAD*2) * (idx + 0.5) / cnt + (Math.random() - 0.5) * 18;
    n.y = PAD + (H - PAD*2) * (maxLayer > 0 ? l / maxLayer : 0.5) + (Math.random() - 0.5) * 18;
    n.vx = 0; n.vy = 0;
  });
}

function dagSimStep() {
  const { nodes, edges, nodeMap, svgW, svgH } = _dag;
  const cx = svgW/2, cy = svgH/2;
  // Edge-type-aware spring lengths: tighter for hard dependencies, looser for concurrent/shared.
  const SPRING_LEN = { depends: 110, shared: 165, conflict: 90, concurrent: 195 };
  const SPRING_K   = { depends: 0.03, shared: 0.018, conflict: 0.038, concurrent: 0.012 };
  const REPEL = 14000, DAMP = 0.80, CENT = 0.002;

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
    const slen = SPRING_LEN[e.type] || 150;
    const sk   = SPRING_K[e.type]   || 0.02;
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx*dx + dy*dy) || 1;
    const f = sk * (d - slen), fx = dx/d*f, fy = dy/d*f;
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
  _dag.nodes.forEach(n => { n.fixed = false; });
  dagInitPositions();
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
