from datetime import datetime, timezone

from app.scoring.decision_gate import evaluate_manual_review_gate


AS_OF = datetime(2026, 8, 27, 19, 0, tzinfo=timezone.utc)


def _ready_inputs():
    return {
        "market": {
            "found": True,
            "price_usd": 1.0,
            "liquidity_usd": 50_000,
            "collected_at": "2026-08-27T18:59:30Z",
        },
        "score": {"radar_score": 62},
        "narrative_quality": {
            "quality_score": 72,
            "classification": "corroborated_leads",
            "independent_domain_count": 3,
            "positive_lenses_covered": [
                "official_builders",
                "adoption_usage",
                "funding_backers",
            ],
            "freshness": {
                "status": "recent_evidence_present",
                "future_dated_count": 0,
            },
            "fetch_failures": 0,
            "counterevidence_leads": 0,
        },
        "red_team": {"risk_level": "medium"},
        "token_security": {
            "status": "complete",
            "promotion_eligible": True,
            "hard_blockers": [],
            "bundler_analysis": {"status": "complete", "hard_blockers": []},
            "execution_enabled": False,
        },
    }


def test_gate_marks_research_candidate_ready_for_manual_review():
    gate = evaluate_manual_review_gate(**_ready_inputs(), as_of=AS_OF)

    assert gate["status"] == "manual_review_ready"
    assert gate["manual_review_ready"] is True
    assert gate["order_preview_requested"] is False
    assert gate["order_preview_ready"] is False
    assert gate["failed_requirements"] == []
    assert gate["execution_enabled"] is False
    assert gate["decision_only"] is True


def test_gate_stays_research_only_for_weak_or_stale_evidence():
    inputs = _ready_inputs()
    inputs["score"] = {"radar_score": 48}
    inputs["narrative_quality"]["freshness"] = {
        "status": "stale_only",
        "future_dated_count": 0,
    }

    gate = evaluate_manual_review_gate(**inputs, as_of=AS_OF)

    assert gate["status"] == "research_only"
    assert "radar_score" in gate["review_requirements"]
    assert "evidence_freshness" in gate["review_requirements"]
    assert gate["blocking_failures"] == []


def test_gate_blocks_future_evidence_high_risk_and_blocked_preview():
    inputs = _ready_inputs()
    inputs["narrative_quality"]["freshness"] = {
        "status": "recent_evidence_present",
        "future_dated_count": 1,
    }
    inputs["red_team"] = {"risk_level": "high"}
    inputs["order_preview"] = {
        "status": "blocked",
        "manual_approval_required": True,
        "execution_enabled": False,
    }

    gate = evaluate_manual_review_gate(**inputs, as_of=AS_OF)

    assert gate["status"] == "blocked"
    assert "evidence_freshness" in gate["blocking_failures"]
    assert "risk_level" in gate["blocking_failures"]
    assert "order_preview" in gate["blocking_failures"]
    assert gate["execution_enabled"] is False


def test_gate_requires_explicitly_disabled_execution_for_preview():
    inputs = _ready_inputs()
    inputs["order_preview"] = {
        "status": "ready_for_manual_review",
        "manual_approval_required": True,
        "execution_enabled": True,
    }

    gate = evaluate_manual_review_gate(**inputs, as_of=AS_OF)

    assert gate["status"] == "blocked"
    assert "execution_safety" in gate["blocking_failures"]


def test_gate_blocks_security_risk_and_holds_for_missing_bundler_analysis():
    inputs = _ready_inputs()
    inputs["token_security"] = {
        "status": "complete",
        "promotion_eligible": False,
        "hard_blockers": ["honeypot_detected"],
        "bundler_analysis": {"status": "not_available"},
        "execution_enabled": False,
    }

    blocked = evaluate_manual_review_gate(**inputs, as_of=AS_OF)
    assert blocked["status"] == "blocked"
    assert "token_security" in blocked["blocking_failures"]
    assert "bundler_concentration" in blocked["review_requirements"]

    inputs = _ready_inputs()
    inputs["token_security"]["bundler_analysis"] = {"status": "not_available"}
    research_only = evaluate_manual_review_gate(**inputs, as_of=AS_OF)
    assert research_only["status"] == "research_only"
    assert "bundler_concentration" in research_only["review_requirements"]
