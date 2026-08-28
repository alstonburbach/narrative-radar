from app.tracking.paper_basket import evaluate_paper_basket


def _positions():
    positions = [
        {
            "label": "winner",
            "narrative_family": "ai",
            "entry_market_cap": 100_000,
            "exit_market_cap": 1_000_000,
            "outcome": "closed",
            "fees_usd": 0.5,
            "slippage_usd": 0.5,
        },
        {
            "label": "loss_one",
            "narrative_family": "gaming",
            "entry_market_cap": 100_000,
            "outcome": "lost",
            "fees_usd": 0.5,
            "slippage_usd": 0.5,
        },
        {
            "label": "loss_two",
            "narrative_family": "ai",
            "entry_market_cap": 100_000,
            "outcome": "lost",
            "fees_usd": 0.5,
            "slippage_usd": 0.5,
        },
        {
            "label": "open_runner",
            "narrative_family": "infrastructure",
            "entry_market_cap": 100_000,
            "mark_market_cap": 200_000,
            "outcome": "open",
            "fees_usd": 0.5,
            "slippage_usd": 0.5,
        },
        {
            "label": "flat",
            "narrative_family": "social",
            "entry_market_cap": 100_000,
            "exit_market_cap": 100_000,
            "outcome": "closed",
            "fees_usd": 0.5,
            "slippage_usd": 0.5,
        },
    ]
    for position in positions:
        position.update(
            {
                "signal_detected_at": "2026-08-01T12:00:00Z",
                "entry_recorded_at": "2026-08-01T12:15:00Z",
                "outcome_observed_at": "2026-08-08T12:15:00Z",
            }
        )
    return positions


def test_fixed_fifty_dollar_basket_reports_asymmetric_outcome():
    report = evaluate_paper_basket(
        _positions(),
        stake_usd=50,
        target_multiple=10,
        evaluated_at="2026-08-10T00:00:00Z",
    )

    assert report["status"] == "ready"
    assert report["aggregate"]["committed_usd"] == 250
    assert report["aggregate"]["gross_portfolio_value_usd"] == 650
    assert report["aggregate"]["pnl_after_known_costs_usd"] == 395
    assert report["aggregate"]["realized_gross_pnl_usd"] == 350
    assert report["target_metrics"]["realized_target_hit_count"] == 1
    assert report["target_metrics"]["realized_target_hit_rate_pct"] == 20.0
    assert report["break_even_winner_multiple_before_costs"] == 5.0
    assert report["execution_enabled"] is False
    distribution = report["outcome_distribution"]
    assert distribution["realized_winner_count"] == 1
    assert distribution["largest_winner_share_of_gross_winning_pnl_pct"] == 100.0
    assert any("winner supplies more than 75%" in warning for warning in report["warnings"])
    timing = report["temporal_integrity"]
    assert timing["verified_count"] == 5
    assert timing["timing_eligible_for_strategy_validation"] is True
    assert report["positions"][0]["temporal_integrity"]["signal_to_entry_minutes"] == 15


def test_basket_does_not_hide_missing_costs_or_correlation():
    positions = _positions()
    for position in positions:
        position.pop("fees_usd")
        position.pop("slippage_usd")
    positions[1]["narrative_family"] = "ai"

    report = evaluate_paper_basket(
        positions,
        stake_usd=50,
        target_multiple=10,
        evaluated_at="2026-08-10T00:00:00Z",
    )

    assert report["cost_coverage"]["complete"] is False
    assert len(report["missing_cost_positions"]) == 5
    assert report["max_narrative_family_share_pct"] == 60.0
    assert any("correlated" in warning for warning in report["warnings"])
    assert any("not an exact net result" in warning for warning in report["warnings"])


def test_invalid_position_withholds_aggregate_results():
    positions = _positions()
    positions[0].pop("exit_market_cap")

    report = evaluate_paper_basket(
        positions,
        stake_usd=50,
        evaluated_at="2026-08-10T00:00:00Z",
    )

    assert report["status"] == "incomplete"
    assert report["invalid_count"] == 1
    assert report["aggregate"]["gross_pnl_usd"] is None
    assert report["errors"]


def test_missing_timestamps_do_not_count_as_forward_tested():
    positions = _positions()
    for position in positions:
        position.pop("signal_detected_at")
        position.pop("entry_recorded_at")
        position.pop("outcome_observed_at")

    report = evaluate_paper_basket(
        positions,
        stake_usd=50,
        evaluated_at="2026-08-10T00:00:00Z",
    )

    timing = report["temporal_integrity"]
    assert report["status"] == "ready"
    assert timing["missing_count"] == 5
    assert timing["timing_eligible_for_strategy_validation"] is False
    assert any("not eligible as a forward-tested result" in item for item in report["warnings"])


def test_invalid_or_future_chronology_fails_forward_test_validation():
    positions = _positions()
    positions[0]["signal_detected_at"] = "2026-08-01T12:30:00Z"
    positions[1]["outcome_observed_at"] = "2026-08-11T00:00:00Z"

    report = evaluate_paper_basket(
        positions,
        stake_usd=50,
        evaluated_at="2026-08-10T00:00:00Z",
    )

    timing = report["temporal_integrity"]
    assert timing["invalid_count"] == 2
    assert timing["timing_eligible_for_strategy_validation"] is False
    assert any("signal_detected_at must not be after" in item for item in timing["issues"])
    assert any("must not be after evaluated_at" in item for item in timing["issues"])
