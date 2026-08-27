from app.database.models import Evidence
from app.scoring.narrative_score import score_radar


def test_score_is_penalized_by_red_flags():
    market = {
        "found": True,
        "market_cap": 1_000_000,
        "liquidity_usd": 2_000,
        "volume_24h": 500_000,
        "price_change_24h": 200,
        "pair_address": "pair",
        "price_usd": 0.01,
    }
    evidence = [Evidence("claim", "https://example.com", "web_search", confidence=0.5)]
    result = score_radar(market, evidence)
    assert result["radar_score"] < 50
    assert result["red_team"]["risk_level"] == "high"
