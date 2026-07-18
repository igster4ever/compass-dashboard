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

# Local copy of compass/reality.py's _NON_ACHIEVEMENT_HEADERS (stdlib-only constraint
# means this can't be imported — see CLAUDE.md "Constants sync"). Sections like
# "External signals — directional" hold research findings, not shippable work — they're
# neither achieved nor backlog, so they shouldn't enter the completeness denominator at
# all. Originally a dashboard-local-only fix (2026-07-11); ported upstream to
# compass/reality.py 2026-07-18 — this copy must now be kept in sync with that one.
_NON_ACHIEVEMENT_HEADERS = frozenset({
    "external signals",
})


def _iter_reality_bullets(reality_md):
    """Yield (text, excluded) for every non-empty, non-underscore bullet in reality_md.

    `excluded` bullets (backlog sections or non-achievement sections like directional
    research signals) are skipped from the P22 completeness denominator entirely.
    """
    excluded = False
    for line in reality_md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if level == 2:
                header = s.lstrip("#").strip().lower()
                excluded = any(k in header for k in _BACKLOG_HEADERS | _NON_ACHIEVEMENT_HEADERS)
        elif s.startswith("- ") or s.startswith("* "):
            text = s[2:].strip()
            if not text or text.startswith("_"):
                continue
            yield text, excluded


def _reality_completeness(reality_md):
    total = 0
    achieved = 0
    for text, excluded in _iter_reality_bullets(reality_md):
        if excluded:
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


_RETRIEVAL_STALE_SURFACED_THRESHOLD = 10  # P58: local copy of compass's retrieval_stale_surfaced_threshold
_MINDMAP_CROSS_NS_GATE = 50  # E25e: min active-learning corpus size for a namespace to qualify as a bridge target


def _retrieval_stale_texts(active_learnings, surfaced_threshold=_RETRIEVAL_STALE_SURFACED_THRESHOLD):
    """Active, non-hypothesis learnings surfaced often (times_surfaced) but never reinforced past weight 1.

    Mirrors compass's own _get_retrieval_stale_candidates() (P58) — kept as a local copy since
    the dashboard reads namespace directories directly rather than shelling out to compass.py.
    """
    texts = set()
    for l in active_learnings:
        if l.get("learning_type") == "hypothesis":
            continue
        if (l.get("weight") or 1) > 1:
            continue
        if l.get("times_surfaced", 0) >= surfaced_threshold:
            texts.add(l.get("text", ""))
    return texts


def _stale_bullet_count(reality_md, state, days=30):
    """Count reality bullets not verified within `days` days (mirrors compass logic)."""
    validation = state.get("reality_validation", {})
    now = _now_utc()
    stale = 0
    for text, _ in _iter_reality_bullets(reality_md):
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


def _load_watch_signals(ns_dir, config, state):
    """P54: tag-overlap-scored decisions/learnings from watched namespaces since last_close.
    Mirrors compass's cmd_watch_signals (scripts/compass/_monolith.py) — the dashboard reads
    namespace directories directly rather than shelling out to compass.py, so the scoring
    logic (weighted tag overlap, bootstrap fallback, top-3/top-5 caps) is duplicated here
    and must be kept in sync if compass's algorithm changes.
    """
    watches = config.get("watches", [])
    if not watches:
        return {"bootstrapped": False, "signals": [], "total_signals": 0, "empty": True}

    last_close = state.get("last_close") or ""

    my_learnings = _read_jsonl(ns_dir / "learnings.jsonl")
    active = [l for l in my_learnings if l.get("status") not in ("archived", "superseded")]
    top = sorted(active, key=lambda l: -l.get("weight", 1))[:15]
    tag_freq = {}
    for l in top:
        for t in l.get("tags", []):
            tag_freq[t] = tag_freq.get(t, 0) + l.get("weight", 1)

    bootstrapped = not tag_freq

    def _overlap(tags):
        if bootstrapped:
            return 1 if tags else 0
        return sum(tag_freq.get(t, 0) for t in tags)

    signals = []
    total = 0
    for watched_ns in watches:
        wd = LOOP_DIR / watched_ns
        if not wd.exists():
            continue

        new_decisions = [
            dec for dec in _read_jsonl(wd / "decisions.jsonl")
            if (dec.get("date") or "") > last_close
        ]
        scored_decisions = [
            {**dec, "overlap_score": ov}
            for dec in new_decisions
            if (ov := _overlap(dec.get("tags", []))) >= 1
        ]
        scored_decisions.sort(key=lambda x: -x["overlap_score"])
        scored_decisions = scored_decisions[:3]

        new_learnings = [
            l for l in _read_jsonl(wd / "learnings.jsonl")
            if (l.get("date") or "") > last_close and l.get("status") not in ("archived", "superseded")
        ]
        scored_learnings = [
            {**l, "overlap_score": ov}
            for l in new_learnings
            if (ov := _overlap(l.get("tags", []))) >= 1
        ]
        scored_learnings.sort(key=lambda x: -x["overlap_score"])
        scored_learnings = scored_learnings[:5]

        signals.append({
            "watched_namespace": watched_ns,
            "new_since":         last_close,
            "decisions":         scored_decisions,
            "learnings":         scored_learnings,
        })
        total += len(scored_decisions) + len(scored_learnings)

    return {
        "bootstrapped":   bootstrapped,
        "signals":        signals,
        "total_signals":  total,
        "empty":          total == 0,
    }


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

    retrieval_stale_texts = _retrieval_stale_texts(active_learnings)
    for l in active_learnings:
        l["retrievalStale"] = l.get("text", "") in retrieval_stale_texts
    retrieval_stale_count = len(retrieval_stale_texts)

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

    watches       = config.get("watches", [])
    watch_signals = _load_watch_signals(ns_dir, config, state)

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

    # All sessions' incomplete items, deduped — used by _extract_blocking_edges()
    _seen_items: set = set()
    all_incomplete_items: list = []
    for _hf in history_files:
        for _item in _hf.get("incomplete", []):
            if _item not in _seen_items:
                _seen_items.add(_item)
                all_incomplete_items.append(_item)

    # Intent drift timeline
    intent_history = _read_jsonl(ns_dir / "intent_history.jsonl")

    # Decay history — corpus maintenance events (newest first)
    decay_history = list(reversed(_read_jsonl(ns_dir / "decay_history.jsonl")))

    # Deferral escalation counts (used in Priorities scoring)
    code_review_defer_count  = len(_read_jsonl(ns_dir / "code_review_deferrals.jsonl"))
    research_defer_count     = len(_read_jsonl(ns_dir / "research_deferrals.jsonl"))

    # External research signals
    external_signals = list(reversed(_read_jsonl(ns_dir / "external_signals.jsonl")))

    # P51–P53: skill feedback + skillopt cadence + quality history + holdout state
    skill_feedback           = _read_jsonl(ns_dir / "skill_feedback.jsonl")
    sessions_since_skill_opt = state.get("sessions_since_skill_opt", 0)
    skill_opt_due            = sessions_since_skill_opt >= 10
    quality_history          = state.get("quality_history", [])
    holdout_session_ids      = state.get("holdout_session_ids", [])
    skillopt_rounds          = state.get("skillopt_rounds", [])
    skillopt_rwi             = state.get("skillopt_rounds_without_improvement", 0)
    holdout_score_map        = {e["session_id"]: e["score"] for e in quality_history}
    holdout_scores           = [holdout_score_map[s] for s in holdout_session_ids if s in holdout_score_map]
    holdout_mean             = round(sum(holdout_scores) / len(holdout_scores), 3) if holdout_scores else None

    # Session artefacts (P41) — resolve abs_file so JS can open/preview via file://
    artefacts = []
    for _a in _read_jsonl(ns_dir / "artefacts.jsonl"):
        _ac = dict(_a)
        _rel = _a.get("file", "")
        if _rel:
            _abs = ns_dir / _rel
            _ac["abs_file"] = str(_abs) if _abs.exists() else None
        else:
            _ac["abs_file"] = None
        artefacts.append(_ac)

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
        "watches":                   watches,
        "watch_signals":             watch_signals,
        "intent_version":            intent_version,
        "stale_bullet_count":        stale_bullet_count,
        "back_refs_by_text":         back_refs_by_text,
        "conflicts_by_text":         conflicts_by_text,
        "intent_history":            intent_history,
        "corpus_health":             corpus_health,
        "retrieval_stale_count":     retrieval_stale_count,
        "external_signals":          external_signals,
        "exploration_ratio":         exploration_ratio,
        "last_reality_score":        last_reality_score,
        "goal_type_by_session":      goal_type_by_session,
        "carry_forward_trend":       carry_forward_trend,
        "quality_dist":              quality_dist,
        "decay_history":             decay_history,
        "code_review_defer_count":    code_review_defer_count,
        "research_defer_count":       research_defer_count,
        "artefacts":                  artefacts,
        "all_incomplete_items":       all_incomplete_items,
        "skill_feedback":             skill_feedback,
        "sessions_since_skill_opt":   sessions_since_skill_opt,
        "skill_opt_due":              skill_opt_due,
        "quality_history":            quality_history,
        "skillopt_holdout_frozen":    bool(holdout_session_ids),
        "skillopt_holdout_mean":      holdout_mean,
        "skillopt_rounds_completed":  len(skillopt_rounds),
        "skillopt_rwi":               skillopt_rwi,
    }


def load_community():
    """Parse _community/*.jsonl files and return COMMUNITY data object (P40-Dashboard Phase 1)."""
    community_dir = LOOP_DIR / "_community"
    enabled = community_dir.is_dir() and any(community_dir.glob("*.jsonl"))
    if not enabled:
        return {
            "enabled":      False,
            "feed":         [],
            "inbox":        [],
            "adoptions":    [],
            "subscriptions": [],
            "trust_registry": [],
        }
    return {
        "enabled":        True,
        "feed":           _read_jsonl(community_dir / "feed.jsonl"),
        "inbox":          _read_jsonl(community_dir / "inbox.jsonl"),
        "adoptions":      _read_jsonl(community_dir / "adoptions.jsonl"),
        "subscriptions":  _read_jsonl(community_dir / "subscriptions.jsonl"),
        "trust_registry": _read_jsonl(community_dir / "trust_registry.jsonl"),
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

def _card_html(n, i, community_published=None):
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

    watching_html = ""
    if n.get("watches"):
        ws = n["watch_signals"]
        title = f'watching: {", ".join(n["watches"])}'
        if ws["total_signals"] > 0:
            watching_html = f'<span class="cadence-chip watching" title="{_e(title)}">📡 {ws["total_signals"]} watch signal{"s" if ws["total_signals"] != 1 else ""}</span>'
        else:
            watching_html = f'<span class="cadence-chip watching" style="color:var(--muted)" title="{_e(title)}">👁 watching</span>'

    community_html = ""
    if community_published:
        published = community_published.get(n["namespace"], 0)
        if published > 0:
            community_html = f'<span class="community-chip">📡 {published} shared</span>'

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
        {watching_html}
        {community_html}
      </div>
      <div class="card-tags">{tags_html}</div>
    </div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Cross-namespace blocking edge extraction (E24a)
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKED_RE = re.compile(r'\[(?::\s*)?blocked:\s*(.+?)\]', re.IGNORECASE)


def _extract_blocking_edges(namespaces):
    """Return cross-namespace blocking edges parsed from carry-forward incomplete items.

    Each edge: {source, target, reason, carryForward, pcodes, tags}
    source  — namespace whose carry-forward item is blocked
    target  — namespace named as the blocker in the [blocked: ...] annotation
    """
    # Build name lookup sorted longest-first to avoid "compass" matching inside
    # "compass-dashboard" when both are present.
    ns_by_len = sorted(
        ((n["namespace"].lower(), n["namespace"]) for n in namespaces),
        key=lambda t: -len(t[0]),
    )

    edges = []
    for ns in namespaces:
        for item in ns.get("all_incomplete_items", []):
            m = _BLOCKED_RE.search(item)
            if not m:
                continue
            reason = m.group(1).strip()
            reason_lower = reason.lower()

            blocker = None
            for name_lower, name_orig in ns_by_len:
                if name_lower == ns["namespace"].lower():
                    continue
                if name_lower in reason_lower:
                    blocker = name_orig
                    break

            if not blocker:
                continue

            pcodes = list(dict.fromkeys(re.findall(r'\bP\d+\b', item)))
            edges.append({
                "source":       ns["namespace"],
                "target":       blocker,
                "reason":       reason,
                "carryForward": item,
                "pcodes":       pcodes,
                "tags":         [p.lower() for p in pcodes],
            })

    return edges


def _js_blocking_edges(namespaces):
    raw = json.dumps(_extract_blocking_edges(namespaces), ensure_ascii=False, default=str)
    return raw.replace("</script>", r"<\/script>").replace("<!--", r"<\!--")


# ─────────────────────────────────────────────────────────────────────────────
# Mind map data layer (E25a)
# ─────────────────────────────────────────────────────────────────────────────

def _mindmap_data(n: dict) -> dict:
    """Return a D3-ready nested hierarchy for namespace n (E25a data layer)."""
    ns_name = n["namespace"]

    # ── Learnings branch: clustered by primary tag ────────────────────────────
    tag_clusters: dict[str, list] = {}
    for i, l in enumerate(n["learnings"]):
        tag = (l.get("tags") or ["untagged"])[0]
        tag_clusters.setdefault(tag, []).append(
            {
                "id":    f"l-{i}",
                "label": l["text"][:60] + ("…" if len(l["text"]) > 60 else ""),
                "type":  "leaf",
                "meta":  {
                    "weight":        l.get("weight", 1),
                    "learning_type": l.get("learning_type", "fact"),
                    "confidence":    l.get("confidence"),
                    "date":          l.get("date", ""),
                    "full_text":     l["text"],
                },
            }
        )
    learning_children = [
        {
            "id":       f"cluster-{tag}",
            "label":    f"{tag} ({len(leaves)})",
            "type":     "cluster",
            "tag":      tag,
            "children": leaves,
        }
        for tag, leaves in sorted(tag_clusters.items(), key=lambda kv: -len(kv[1]))
    ]
    learnings_branch = {
        "id":       "learnings",
        "label":    f"Learnings ({len(n['learnings'])})",
        "type":     "branch",
        "children": learning_children,
    }

    # ── Decisions branch: flat, newest first ─────────────────────────────────
    decision_leaves = [
        {
            "id":    f"d-{i}",
            "label": (d.get("decision") or "")[:60] + ("…" if len(d.get("decision") or "") > 60 else ""),
            "type":  "leaf",
            "meta":  {
                "rationale":    d.get("rationale", ""),
                "alternatives": d.get("alternatives", ""),
                "date":         d.get("date", ""),
                "full_text":    d.get("decision", ""),
            },
        }
        for i, d in enumerate(n["decisions"])
    ]
    decisions_branch = {
        "id":       "decisions",
        "label":    f"Decisions ({len(n['decisions'])})",
        "type":     "branch",
        "children": decision_leaves,
    }

    # ── Goals branch: last 5 sessions → completed items as leaves ────────────
    session_nodes = []
    for hi, h in enumerate(n["history"][:5]):
        date_label = (h.get("opened") or h.get("filename", ""))[:10]
        completed  = h.get("completed") or []
        session_nodes.append(
            {
                "id":    f"s-{hi}",
                "label": date_label or f"session-{hi+1}",
                "type":  "session",
                "children": [
                    {
                        "id":    f"s-{hi}-g-{gi}",
                        "label": g[:60] + ("…" if len(g) > 60 else ""),
                        "type":  "leaf",
                        "meta":  {"full_text": g},
                    }
                    for gi, g in enumerate(completed)
                ],
            }
        )
    goals_branch = {
        "id":       "goals",
        "label":    "Goals (recent)",
        "type":     "branch",
        "children": session_nodes,
    }

    # ── Reality branch: top-level ## sections ────────────────────────────────
    reality_sections: list[dict] = []
    current_title = None
    current_bullets: list = []
    for line in (n.get("reality") or "").splitlines():
        if line.startswith("## "):
            if current_title is not None:
                reality_sections.append(
                    {"title": current_title, "bullets": current_bullets}
                )
            current_title   = line[3:].strip()
            current_bullets = []
        elif current_title and line.strip().startswith(("- ", "* ")):
            current_bullets.append(line.strip()[2:].strip())
    if current_title is not None:
        reality_sections.append({"title": current_title, "bullets": current_bullets})

    reality_leaves = [
        {
            "id":    f"r-{i}",
            "label": sec["title"][:50] + ("…" if len(sec["title"]) > 50 else ""),
            "type":  "leaf",
            "meta":  {"bullet_count": len(sec["bullets"]), "bullets": sec["bullets"]},
        }
        for i, sec in enumerate(reality_sections)
    ]
    reality_branch = {
        "id":       "reality",
        "label":    "Reality",
        "type":     "branch",
        "children": reality_leaves,
    }

    # ── Artefacts branch: flat list ───────────────────────────────────────────
    artefact_leaves = [
        {
            "id":    f"a-{i}",
            "label": a.get("title", "")[:60] + ("…" if len(a.get("title", "")) > 60 else ""),
            "type":  "leaf",
            "meta":  {
                "artefact_type": a.get("type", ""),
                "created_at":    a.get("created_at", ""),
                "description":   a.get("description", ""),
                "tags":          a.get("tags", []),
            },
        }
        for i, a in enumerate(n["artefacts"])
    ]
    artefacts_branch = {
        "id":       "artefacts",
        "label":    f"Artefacts ({len(n['artefacts'])})",
        "type":     "branch",
        "children": artefact_leaves,
    }

    return {
        "id":       "root",
        "label":    ns_name,
        "type":     "root",
        "children": [
            learnings_branch,
            decisions_branch,
            goals_branch,
            reality_branch,
            artefacts_branch,
        ],
    }


def _add_mindmap_bridges(data: list) -> None:
    """E25e: annotate each namespace's mind-map tag clusters with cross-namespace
    'bridge' info — other namespaces (above the corpus gate) that also have active
    learnings tagged with the same tag. Mutates `data` (the JS-serialisation list
    built in `_js_data()`, each entry already carrying its own `mindmap` tree) in place.
    Must run after each entry's `mindmap` key is populated — `_mindmap_data(n)` builds
    a fresh tree per call rather than caching it on the namespace dict itself.

    Bridge targets are gated at _MINDMAP_CROSS_NS_GATE active learnings: a namespace
    needs enough corpus for its tag clusters to be a meaningful comparison point, not
    a single stray learning matching by coincidence.
    """
    qualifying = [n for n in data if len(n["learnings"]) >= _MINDMAP_CROSS_NS_GATE]
    if not qualifying:
        return

    # tag -> {namespace: count}, built only from qualifying namespaces
    tag_owners: dict[str, dict[str, int]] = {}
    for n in qualifying:
        counts: dict[str, int] = {}
        for l in n["learnings"]:
            for tag in (l.get("tags") or ["untagged"])[:1]:  # primary tag only, matches cluster grouping
                counts[tag] = counts.get(tag, 0) + 1
        for tag, count in counts.items():
            tag_owners.setdefault(tag, {})[n["namespace"]] = count

    for n in data:
        learning_clusters = n["mindmap"]["children"][0]["children"]
        for cluster in learning_clusters:
            tag = cluster.get("tag")
            if not tag:
                continue
            others = {
                ns: count for ns, count in tag_owners.get(tag, {}).items()
                if ns != n["namespace"]
            }
            if others:
                cluster["bridge_namespaces"] = sorted(
                    ({"namespace": ns, "count": c} for ns, c in others.items()),
                    key=lambda b: -b["count"],
                )


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
            "watches":                 n.get("watches", []),
            "watchSignals":            n.get("watch_signals", {"bootstrapped": False, "signals": [], "total_signals": 0, "empty": True}),
            "intentVersion":           n["intent_version"],
            "staleBulletCount":        n["stale_bullet_count"],
            "backRefsByText":          n["back_refs_by_text"],
            "conflictsByText":         n["conflicts_by_text"],
            "intentHistory":           n["intent_history"],
            "corpusHealth":            n["corpus_health"],
            "retrievalStaleCount":     n["retrieval_stale_count"],
            "externalSignals":         n["external_signals"],
            "explorationRatio":        n["exploration_ratio"],
            "lastRealityScore":        n["last_reality_score"],
            "goalTypeBySession":       n["goal_type_by_session"],
            "carryForwardTrend":       n["carry_forward_trend"],
            "qualityDist":             n["quality_dist"],
            "decayHistory":            n["decay_history"],
            "codeReviewDeferCount":    n["code_review_defer_count"],
            "researchDeferCount":      n["research_defer_count"],
            "artefacts":               n["artefacts"],
            "skillFeedback":           n["skill_feedback"],
            "sessionsSinceSkillOpt":   n["sessions_since_skill_opt"],
            "skillOptDue":             n["skill_opt_due"],
            "qualityHistory":          n["quality_history"],
            "skilloptHoldoutFrozen":   n["skillopt_holdout_frozen"],
            "skilloptHoldoutMean":     n["skillopt_holdout_mean"],
            "skilloptRoundsCompleted": n["skillopt_rounds_completed"],
            "skilloptRwi":             n["skillopt_rwi"],
            "mindmap":                 _mindmap_data(n),
        })
    _add_mindmap_bridges(data)  # E25e: cross-namespace tag-cluster bridges — needs the
                                # already-built mindmap trees, so this runs here, not in generate()
    raw = json.dumps(data, ensure_ascii=False, default=str)
    # Prevent </script> from breaking the embedding
    return raw.replace("</script>", r"<\/script>").replace("<!--", r"<\!--")




# ─────────────────────────────────────────────────────────────────────────────
# HTML assembly
# ─────────────────────────────────────────────────────────────────────────────

def _js_community(community):
    raw = json.dumps(community, ensure_ascii=False, default=str)
    return raw.replace("</script>", r"<\/script>").replace("<!--", r"<\!--")


def generate(namespaces):
    now         = _now_utc().strftime("%d %b %Y %H:%M UTC")
    n_open      = sum(1 for n in namespaces if n["open_session"])
    n_learnings = sum(len(n["learnings"]) for n in namespaces)
    n_sessions  = sum(n["session_count"] for n in namespaces)

    community = load_community()
    community_published: dict[str, int] = {}
    if community["enabled"]:
        for entry in community.get("feed", []):
            ns_id = entry.get("source_loop_id", "")
            if ns_id:
                community_published[ns_id] = community_published.get(ns_id, 0) + 1
    cards = "".join(_card_html(n, i, community_published) for i, n in enumerate(namespaces))

    html = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    html = html.replace("[[GENERATED_AT]]",   now)
    html = html.replace("[[N_NS]]",           str(len(namespaces)))
    html = html.replace("[[N_OPEN]]",         str(n_open))
    html = html.replace("[[N_LEARNINGS]]",    str(n_learnings))
    html = html.replace("[[N_SESSIONS]]",     str(n_sessions))
    html = html.replace("[[CARDS]]",          cards)
    html = html.replace("[[NS_DATA]]",           _js_data(namespaces))
    html = html.replace("[[COMMUNITY_DATA]]",    _js_community(community))
    html = html.replace("[[BLOCKING_EDGES]]",    _js_blocking_edges(namespaces))

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

    html      = generate(namespaces)
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
