from app.agents.red_team import run_red_team, summarize_red_team


def test_red_team_flags_thin_liquidity_and_missing_evidence():
    flags = run_red_team(
        {
            "found": True,
            "market_cap": 500_000,
            "liquidity_usd": 1_000,
            "volume_24h": 10_000,
            "price_change_24h": 0,
        }
    )
    codes = {flag["code"] for flag in flags}
    assert "very_thin_liquidity" in codes
    assert "no_independent_evidence" in codes
    assert summarize_red_team(flags)["risk_level"] == "high"
