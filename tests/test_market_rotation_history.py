from app.market_rotation_history import with_historical_baseline
from app.market_rotation import classify_rotation


def test_history_builds_multi_metric_baseline():
    history = [
        {"coverage_status": "complete", "volume_usd": 100, "launches": 10, "active_traders": 20},
        {"coverage_status": "complete", "volume_usd": 120, "launches": 12, "active_traders": 22},
        {"coverage_status": "partial", "volume_usd": 80, "launches": 8, "active_traders": 18},
    ]
    current = {"chain": "robinhood", "venue": "pons", "volume_usd": 600, "launches": 60, "active_traders": 100}
    enriched = with_historical_baseline(current, history)
    assert enriched["baseline_status"] == "ready"
    assert enriched["baseline_volume_usd"] == 100
    assert enriched["baseline_launches"] == 10
    assert enriched["baseline_active_traders"] == 20
    assert classify_rotation(enriched)["status"] == "coming_up"


def test_failed_history_is_not_used_as_zero_activity():
    history = [
        {"coverage_status": "failed", "volume_usd": 0, "launches": 0},
        {"coverage_status": "complete", "volume_usd": 100, "launches": 10},
        {"coverage_status": "complete", "volume_usd": 100, "launches": 10},
    ]
    enriched = with_historical_baseline({"chain": "solana", "volume_usd": 150, "launches": 12}, history)
    assert enriched["baseline_status"] == "insufficient_history"


def test_missing_metric_never_gets_fake_baseline():
    history = [
        {"coverage_status": "complete", "volume_usd": 100},
        {"coverage_status": "complete", "volume_usd": 110},
        {"coverage_status": "complete", "volume_usd": 90},
    ]
    enriched = with_historical_baseline({"chain": "base", "volume_usd": 140}, history)
    assert "baseline_launches" not in enriched
    assert enriched["baseline_status"] == "insufficient_dimensions"
