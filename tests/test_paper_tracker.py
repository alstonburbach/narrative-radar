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
