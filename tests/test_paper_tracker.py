from app.tracking.paper_tracker import project_paper_position


def test_paper_position_uses_market_cap_multiple():
    result = project_paper_position(
        {"market_cap": 100_000},
        100,
        target_market_caps=[200_000, 500_000],
    )
    assert result["paper_only"] is True
    assert result["projections"][0]["estimated_value_usd"] == 200
    assert result["projections"][1]["estimated_pnl_usd"] == 400

def test_paper_position_surfaces_liquidity_risk_without_adjusting_the_projection():
    result = project_paper_position(
        {"market_cap": 100_000, "liquidity_usd": 1_000},
        100,
        target_market_caps=[200_000],
    )

    assert result["entry_liquidity_context"]["position_to_liquidity_pct"] == 10.0
    assert result["entry_liquidity_context"]["liquidity_risk"] == "high"
    assert result["projections"][0]["target_to_current_liquidity"]["position_to_liquidity_pct"] == 20.0
    assert result["projections"][0]["target_to_current_liquidity"]["liquidity_risk"] == "very_high"
    assert result["projections"][0]["estimated_value_usd"] == 200
