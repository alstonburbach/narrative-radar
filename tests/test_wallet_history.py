from app.tracking.wallet_history import compare_wallet_history


def _run(analyzed_at, pnl, candidate=True, flags=None, quality=80):
    return {
        "analyzed_at": analyzed_at,
        "quality_score": quality,
        "research_candidate": candidate,
        "primary_realized_pnl": pnl,
        "primary_quote_asset": "USD",
        "closed_trades": 25,
        "external_inflow_usd": 0,
        "flags": flags or [],
    }


def test_wallet_history_requires_repeat_runs():
    result = compare_wallet_history([_run("2026-08-27", 100)])

    assert result["state"] == "insufficient_history"
    assert result["strategy_classification"] == "not_yet_repeatable"


def test_wallet_history_identifies_three_clean_positive_runs_as_candidate():
    result = compare_wallet_history(
        [
            _run("2026-08-27", 100),
            _run("2026-08-28", 120),
            _run("2026-08-29", 140),
        ]
    )

    assert result["state"] == "strengthening"
    assert result["strategy_classification"] == "repeatable_realized_candidate"
    assert result["positive_realized_candidate_runs"] == 3
    assert result["primary_realized_pnl"]["delta"] == 40


def test_wallet_history_downgrades_deposit_or_cost_basis_contamination():
    result = compare_wallet_history(
        [
            _run("2026-08-27", 100, flags=["incomplete_cost_basis_or_inbound_tokens"]),
            _run("2026-08-28", 120),
            _run("2026-08-29", 140),
        ]
    )

    assert result["strategy_classification"] == "contaminated_or_incomplete"
    assert result["contaminated_or_incomplete_runs"] == 1


def test_wallet_history_does_not_compare_different_quote_assets():
    first = _run("2026-08-27", 100)
    last = _run("2026-08-28", 2)
    last["primary_quote_asset"] = "SOL"

    result = compare_wallet_history([first, last])

    assert result["same_primary_quote_asset"] is False
    assert result["primary_realized_pnl"]["available"] is False
