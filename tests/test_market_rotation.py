from app.market_rotation import build_market_rotation, classify_rotation


def test_coming_up_requires_broad_acceleration():
    result = classify_rotation({
        "volume_usd": 600,
        "baseline_volume_usd": 100,
        "fees_usd": 500,
        "baseline_fees_usd": 100,
        "launches": 300,
        "baseline_launches": 100,
        "active_traders": 180,
        "baseline_active_traders": 100,
    })
    assert result["status"] == "coming_up"
    assert result["confidence"] == "high"


def test_one_spike_does_not_call_market_hot():
    result = classify_rotation({
        "volume_usd": 1000,
        "baseline_volume_usd": 100,
        "fees_usd": 100,
        "baseline_fees_usd": 100,
        "launches": 100,
        "baseline_launches": 100,
    })
    assert result["status"] not in {"hot", "coming_up"}


def test_cooling_detects_broad_contraction():
    result = classify_rotation({
        "volume_usd": 50,
        "baseline_volume_usd": 100,
        "fees_usd": 55,
        "baseline_fees_usd": 100,
        "active_traders": 60,
        "baseline_active_traders": 100,
    })
    assert result["status"] == "cooling"


def test_rotation_ranks_coming_up_venue_first():
    report = build_market_rotation([
        {
            "chain": "robinhood",
            "venue": "pons",
            "volume_usd": 500,
            "baseline_volume_usd": 100,
            "fees_usd": 500,
            "baseline_fees_usd": 100,
            "launches": 500,
            "baseline_launches": 100,
        },
        {
            "chain": "solana",
            "venue": "pump_fun",
            "volume_usd": 100,
            "baseline_volume_usd": 100,
            "fees_usd": 100,
            "baseline_fees_usd": 100,
            "launches": 100,
            "baseline_launches": 100,
        },
    ])
    assert report["venues"][0]["venue"] == "pons"
    assert report["execution_enabled"] is False
