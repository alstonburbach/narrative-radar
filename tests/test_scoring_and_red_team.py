from app.agents.red_team import build_red_team_report
from app.database.models import Evidence
from app.scoring.narrative_score import score_narrative


def test_red_team_flags_thin_liquidity_and_missing_primary_source():
    market = {
        "found": True,
        "liquidity_usd": 5000,
        "volume_24h": 100000,
        "price_change_24h": -30,
        "market_cap": 100000,
        "fdv": 300000,
    }
    evidence = [
        Evidence(
            claim="A secondary article mentions the token",
            source_url="https://example.com",
            source_type="web_research",
            confidence=0.55,
        )
    ]

    report = build_red_team_report(market, evidence)
    codes = {warning["code"] for warning in report["warnings"]}

    assert report["risk_level"] == "high"
    assert "very_thin_liquidity" in codes
    assert "no_primary_source" in codes


def test_score_is_bounded_and_never_execution_signal():
    result = score_narrative(
        market={
            "found": True,
            "liquidity_usd": 1_000_000,
            "volume_24h": 2_000_000,
            "price_change_24h": 20,
        },
        evidence=[],
        red_team={"warnings": []},
    )

    assert 0 <= result["score"] <= 100
    assert "not financial advice" in result["disclaimer"]
