#!/usr/bin/env python3
"""
Regenerates tests/js/fixtures/dashboard_fixture.json.

Builds two synthetic namespaces using load_namespace()'s real field shapes (never
real namespace content — everything here is placeholder text), then runs them
through the actual _js_data()/_js_community() functions so the fixture always
matches production's camelCase JS shape exactly, not a hand-guessed one.

Run from the repo root: python3 tests/js/fixtures/generate_fixture.py
"""
import json
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("compass_dashboard", REPO_ROOT / "scripts" / "compass-dashboard.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def dt(s):
    return mod._parse_iso(s)


def make_ns(name, **overrides):
    base = {
        "namespace": name, "open_session": False, "last_close": dt("2026-08-01T09:00:00Z"),
        "last_open": dt("2026-08-01T08:00:00Z"), "planned_actions": ["Example goal one", "Example goal two"],
        "deferred": {"widget-x": {"defer_count": 1, "opportunity_text": "Build widget X"}},
        "intent": "# Reality\nExample intent for " + name, "intent_summary": "Example intent summary",
        "reality": "# Reality\n## What exists and works\n- Feature A shipped\n- Feature B shipped\n\n## Backlog\n### Tactical\n- Do thing [source: example]\n",
        "learnings": [
            {"learning_id": "l1", "text": "Example learning about tooling", "tags": ["tooling", "dashboard"],
             "weight": 3, "date": "2026-07-01T00:00:00Z", "learning_type": "fact", "zone": "golden",
             "confidence": "high", "times_surfaced": 5, "status": "active"},
            {"learning_id": "l2", "text": "Example hypothesis learning", "tags": ["architecture"],
             "weight": 1, "date": "2026-07-15T00:00:00Z", "learning_type": "hypothesis",
             "confidence": "medium", "status": "active"},
            {"learning_id": "l4", "text": "Example warning-zone learning", "tags": ["process"],
             "weight": 2, "date": "2026-07-18T00:00:00Z", "learning_type": "fact", "zone": "warning",
             "confidence": "medium", "status": "active"},
        ],
        "superseded_count": 1, "decisions": [
            {"decision": "Chose approach A", "rationale": "Simpler", "alternatives": "Approach B",
             "complexity_domain": "complicated", "decision_date": "2026-07-10T00:00:00Z"},
        ],
        "code_context": "## Last updated: 2026-08-01\nNext step: keep going",
        "history": [
            {"filename": "2026-08-01T0800.md", "completed": ["did x"], "incomplete": ["y [blocked: waiting]"],
             "planned": ["did x", "y"]},
        ],
        "session_dates": ["2026-07-01", "2026-07-15", "2026-08-01"],
        "goal_rate": 80.0, "goal_dots": [1, 1, 0, 1],
        "goal_by_month": {"2026-07": 75.0, "2026-08": 80.0},
        # _top_tags() returns a flat list of tag-name strings, NOT [tag, count] pairs —
        # dagInitPositions() does `topTags[0].localeCompare(...)`, so getting this shape
        # wrong here silently passed every other test but threw in the DAG smoke test.
        "top_tags": ["tooling", "architecture"],
        "session_count": 3, "cycle_history": [{"opened_at": "2026-08-01T08:00:00Z", "closed_at": "2026-08-01T08:20:00Z", "minutes": 20}],
        "last_cycle_minutes": 20,
        "sessions_since_dream": 2, "dream_due": False,
        "reality_completeness_score": 55.0, "suggested_goal_count": {"count": 4, "basis": "example"},
        "research_due": False, "code_review_due": False,
        "code_review_status": {"due": False, "sessions_since_review": 1, "interval_sessions": 5,
                                "last_review_at": None, "days_since_review": None, "interval_days": 7,
                                "pulled_forward_by_complexity": False,
                                "complexity_signal": {"lines_changed": 0, "new_files": 0, "new_design_docs": 0, "complex_decisions": 0, "score": 0.0, "high": False}},
        "watches": [], "watch_signals": {"bootstrapped": False, "signals": [], "total_signals": 0, "empty": True},
        "intent_version": 1, "stale_bullet_count": 0,
        "back_refs_by_text": {}, "conflicts_by_text": {}, "intent_history": [],
        "corpus_health": {"score": 80, "unvalidatedHypotheses": 1, "lowWeightCount": 1, "totalActive": 3, "supersededCount": 1},
        "zone_distribution": {"golden": 1, "warning": 1, "preference": 0, "unclassified": 1},
        "goal_contracts": [
            {"goal_hash": "abc123", "goal_text": "Ship the verification-contracts panel",
             "criteria": [{"text": "coverage chip renders", "met": True}, {"text": "criteria list renders", "met": True}],
             "evidence_type": "document", "stopping_condition": "n/a",
             "created_at": "2026-08-01T00:00:00Z", "verified_at": "2026-08-02T00:00:00Z",
             "criteria_hit_rate": 1.0, "status": "verified"},
        ],
        "contract_coverage": 1.0, "criteria_hit_rate": 1.0,
        "decision_guidance": [
            {"guidance_id": "g1", "context_summary": "Choosing a sync strategy for the community feed",
             "preferred_decision_text": "Use event-driven append-to-feed.jsonl",
             "avoided_decision_text": "Poll feed.jsonl on a fixed interval",
             "evidence": {"preferred_quality": 0.86, "avoided_quality": 0.61},
             "status": "active", "created_at": "2026-08-25T09:12:03Z"},
        ],
        "retrieval_stale_count": 0, "external_signals": [],
        "exploration_ratio": {"ratio": 25.0, "sessionsWithTypes": 4, "explore": 1, "total": 4, "low": False},
        "last_reality_score": 50.0, "outcome_rate": 0.5,
        "goal_outcomes": [], "goal_type_by_session": [{"date": "2026-08-01", "exploit": 1, "explore": 0}],
        "carry_forward_trend": [{"date": "2026-08-01", "carryForward": 1, "goalsCompleted": 1}],
        "quality_dist": {"high": 2, "neutral": 1, "poor": 0}, "decay_history": [],
        "code_review_defer_count": 0, "research_defer_count": 0,
        "artefacts": [{"title": "Example diagram", "type": "svg", "tags": ["dashboard"], "description": "x",
                       "file": "artefacts/example.svg", "abs_file": None, "linked_pcode": None, "created_at": "2026-07-01T00:00:00Z"}],
        "all_incomplete_items": ["y [blocked: waiting]"],
        "skill_feedback": [
            {"text": "Something was slow", "step_ref": "ooda:orient", "weight": 2, "status": "open",
             "failure_dimension": "cadence-timing"},
            {"text": "Something else", "step_ref": "general", "weight": 1, "status": "open"},
        ],
        "sessions_since_skill_opt": 3, "skill_opt_due": False,
        "quality_history": [{"session_id": "s1", "score": 0.7, "components": {}, "recorded_at": "2026-07-01T00:00:00Z"},
                             {"session_id": "s2", "score": 0.75, "components": {}, "recorded_at": "2026-07-15T00:00:00Z"},
                             {"session_id": "s3", "score": 0.8, "weakest_component": "reality_freshness",
                              "components": {"goal_completion_rate": 0.9, "outcome_rate": 0.8,
                                             "learnings_density": 0.85, "reality_freshness": 0.6},
                              "recorded_at": "2026-08-01T00:00:00Z"}],
        "skillopt_holdout_frozen": True, "skillopt_holdout_mean": 0.72,
        "skillopt_rounds_completed": 1, "skillopt_rwi": 0,
        "quality_plateau": {"plateaued": False, "insufficient_sample": False, "sessions_checked": 3, "trend": "improving", "delta": 0.1},
        "cadence_pull_forward": {"review": False, "skill_opt": False},
        "skill_opt_friction_gate": {"open_feedback_count": 2, "threshold": 3, "sufficient_signal": False},
        "assumption_audit_due": False, "assumption_audit_candidates": [],
        "claude_review_due": False, "dream_defer_count": 0,
        "complexity_clustering_signals": [],
    }
    base.update(overrides)
    return base


def build():
    ns_list = [
        make_ns("example-ns-one"),
        make_ns("example-ns-two", open_session=True, planned_actions=["Do a thing"], learnings=[
            {"learning_id": "l3", "text": "Shared tooling insight", "tags": ["tooling"], "weight": 2,
             "date": "2026-07-20T00:00:00Z", "learning_type": "fact", "status": "active"},
        ], zone_distribution={"golden": 0, "warning": 0, "preference": 0, "unclassified": 1},
           goal_contracts=[], contract_coverage=None, criteria_hit_rate=None, decision_guidance=[]),
    ]

    for n in ns_list:
        n["mindmap"] = mod._mindmap_data(n)

    community = {
        "enabled": True,
        "feed": [
            {"learning_id": "l1", "source_loop_id": "example-ns-one", "event_type": "community.learning_published",
             "text": "Shared learning", "tags": ["tooling"], "published_at": "2026-07-05T00:00:00Z", "trust_level": "high"},
        ],
        "inbox": [],
        "adoptions": [
            {"community_id": "c1", "namespace": "example-ns-two", "adopted_at": "2026-07-06T00:00:00Z"},
        ],
        "subscriptions": [],
        "trust_registry": [
            {"peer_id": "example-ns-one", "trust_level": "high", "registered_at": "2026-07-01T00:00:00Z", "notes": ""},
        ],
    }

    adoption_counts_by_community_id = {"c1": 1}
    published_ids_by_ns = {"example-ns-one": {"l1"}}
    for n in ns_list:
        published_ids = published_ids_by_ns.get(n["namespace"], set())
        for l in n["learnings"]:
            lid = l.get("learning_id")
            l["communityShared"] = bool(lid and lid in published_ids)
            l["communityAdoptedByCount"] = adoption_counts_by_community_id.get(lid, 0) if lid else 0

    ns_js = json.loads(mod._js_data(ns_list))
    community_js = json.loads(mod._js_community(community))
    blocking_js = mod._extract_blocking_edges(ns_list) if hasattr(mod, "_extract_blocking_edges") else []

    return {"NS": ns_js, "COMMUNITY": community_js, "BLOCKING_EDGES": blocking_js}


if __name__ == "__main__":
    out = build()
    out_path = Path(__file__).parent / "dashboard_fixture.json"
    out_path.write_text(json.dumps(out))
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
