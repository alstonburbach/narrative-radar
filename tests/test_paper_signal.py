from app.paper_signal import (
    create_paper_signal_state,
    mark_paper_signal_state,
    summarize_paper_signal_states,
)


def _analysis(market_cap=100_000, collected_at="2026-08-01T12:01:00Z"):
    return {
        "started_at": collected_at,
        "market": {
            "found": True,
            "contract_address": "0x1111111111111111111111111111111111111111",
            "token_name": "Signal Token",
            "token_symbol": "SIG",
            "chain": "base",
            "market_cap": market_cap,
            "price_usd": 0.001,
            "liquidity_usd": 50_000,
            "volume_24h": 25_000,
            "pair_address": "entry-pair",
            "dex": "testdex",
            "dex_url": "https://dexscreener.com/base/entry-pair",
            "collected_at": collected_at,
        },
        "decision_gate": {
            "status": "research_only",
            "failed_requirements": ["verified_primary_evidence"],
        },
        "narrative_quality": {
            "quality_score": 42,
            "classification": "weak_evidence",
        },
        "score": {"radar_score": 37},
        "red_team": {"risk_level": "high"},
    }


def _request():
    return {
        "contract_address": "0x1111111111111111111111111111111111111111",
        "chain": "base",
        "stake_usd": 50,
        "target_multiple": 10,
        "narrative_family": "ai agents",
        "signal_source": "narrative_radar",
    }


def _state():
    return create_paper_signal_state(
        _request(),
        _analysis(),
        issue_number=12,
        issue_created_at="2026-08-01T12:00:00Z",
    )


def _market(market_cap, observed_at="2026-08-01T13:00:00Z", chain="base"):
    return {
        "found": True,
        "chain": chain,
        "market_cap": market_cap,
        "price_usd": 0.0025,
        "liquidity_usd": 60_000,
        "volume_24h": 30_000,
        "pair_address": "entry-pair",
        "dex": "testdex",
        "dex_url": "https://dexscreener.com/base/entry-pair",
        "collected_at": observed_at,
    }


def test_create_state_freezes_entry_timing_and_safety_evidence():
    state = _state()

    assert state["signal_detected_at"] == "2026-08-01T12:00:00+00:00"
    assert state["entry_recorded_at"] == "2026-08-01T12:01:00+00:00"
    assert state["entry_delay_seconds"] == 60
    assert state["entry_market_cap"] == 100_000
    assert state["stake_usd"] == 50
    assert state["entry_decision_gate"] == "research_only"
    assert state["entry_failed_requirements"] == ["verified_primary_evidence"]
    assert state["execution_enabled"] is False
    assert state["paper_only"] is True


def test_mark_crosses_one_milestone_and_preserves_sampled_high():
    state, notification = mark_paper_signal_state(_state(), _market(250_000))

    assert state["current_multiple"] == 2.5
    assert state["highest_sampled_multiple"] == 2.5
    assert state["gross_marked_value_usd"] == 125
    assert state["milestones_reached"] == [2.0]
    assert notification["reason"] == "sampled_milestone_reached"
    assert notification["multiple"] == 2.0

    later, second_notification = mark_paper_signal_state(
        state,
        _market(150_000, observed_at="2026-08-01T14:00:00Z"),
    )

    assert later["current_multiple"] == 1.5
    assert later["highest_sampled_multiple"] == 2.5
    assert later["highest_sampled_market_cap"] == 250_000
    assert second_notification is None


def test_target_hit_is_sampled_once_and_never_enables_execution():
    state, notification = mark_paper_signal_state(_state(), _market(1_050_000))

    assert state["status"] == "target_reached"
    assert state["target_reached_at"] == "2026-08-01T13:00:00+00:00"
    assert state["milestones_reached"] == [2.0, 3.0, 5.0, 10.0]
    assert notification["reason"] == "sampled_target_reached"
    assert state["execution_enabled"] is False

    later, second_notification = mark_paper_signal_state(
        state,
        _market(1_100_000, observed_at="2026-08-01T14:00:00Z"),
    )
    assert later["target_reached_at"] == state["target_reached_at"]
    assert second_notification is None


def test_unavailable_or_wrong_chain_marks_fail_closed():
    unavailable, notification = mark_paper_signal_state(
        _state(),
        {"found": False, "collected_at": "2026-08-01T13:00:00Z"},
    )
    assert unavailable["mark_status"] == "market_unavailable"
    assert unavailable["sample_count"] == 1
    assert notification is None
    assert unavailable["execution_enabled"] is False

    mismatch, notification = mark_paper_signal_state(
        _state(),
        _market(200_000, chain="solana"),
    )
    assert mismatch["mark_status"] == "chain_mismatch"
    assert notification is None
    assert mismatch["execution_enabled"] is False


def test_aggregate_labels_open_sampled_values_as_non_realized():
    first, _ = mark_paper_signal_state(_state(), _market(200_000))
    second = _state()
    second["source_issue_number"] = 13
    report = summarize_paper_signal_states([first, second, {"bad": "state"}])

    assert report["signal_count"] == 2
    assert report["committed_usd"] == 100
    assert report["gross_sampled_value_usd"] == 150
    assert report["gross_sampled_pnl_usd"] == 50
    assert report["execution_enabled"] is False
    assert "not realized" in report["note"]
