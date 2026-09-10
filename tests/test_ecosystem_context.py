from app.ecosystem_context import apply_ecosystem_context, sort_by_research_priority


def _rotation(status):
    return {"rotation": {"status": status, "score": 80}}


def test_hot_ecosystem_boost_is_bounded():
    candidate = {"signal_status": "research_now", "market_screen": {"score": 70}}
    result = apply_ecosystem_context(
        candidate,
        chain_rotation=_rotation("hot"),
        venue_rotation=_rotation("coming_up"),
    )
    assert result["research_priority_score"] == 80
    assert result["ecosystem_context"]["adjustment"] == 10
    assert result["research_priority_eligible"] is True


def test_hot_ecosystem_never_unblocks_security_failure():
    candidate = {"signal_status": "blocked_security", "market_screen": {"score": 90}}
    result = apply_ecosystem_context(
        candidate,
        chain_rotation=_rotation("hot"),
        venue_rotation=_rotation("coming_up"),
    )
    assert result["research_priority_eligible"] is False
    assert result["research_priority_reason"] == "hard_block_preserved"


def test_cooling_ecosystem_reduces_priority_without_blocking_safe_token():
    candidate = {"signal_status": "research_now", "market_screen": {"score": 70}}
    result = apply_ecosystem_context(
        candidate,
        chain_rotation=_rotation("cooling"),
        venue_rotation=_rotation("cold"),
    )
    assert result["research_priority_score"] == 60
    assert result["research_priority_eligible"] is True


def test_sort_sinks_blocked_candidate_even_with_higher_raw_score():
    safe = {"symbol": "SAFE", "research_priority_score": 65, "research_priority_eligible": True}
    blocked = {"symbol": "NOPE", "research_priority_score": 99, "research_priority_eligible": False}
    rows = sort_by_research_priority([blocked, safe])
    assert rows[0]["symbol"] == "SAFE"
