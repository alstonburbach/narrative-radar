from app.tracking.adoption_history import compare_adoption_history


def test_adoption_history_requires_two_snapshots():
    result = compare_adoption_history(
        [{"observed_at": "2026-08-27T00:00:00+00:00", "holder_count": 10}]
    )

    assert result["state"] == "insufficient_history"
    assert result["run_count"] == 1


def test_adoption_history_marks_holder_and_activity_growth_as_strengthening():
    result = compare_adoption_history(
        [
            {
                "observed_at": "2026-08-27T00:00:00+00:00",
                "holder_count": 10,
                "transfer_transaction_count_24h": 5,
                "transfer_event_count_24h": 8,
                "unique_active_wallets_24h": 4,
            },
            {
                "observed_at": "2026-08-28T00:00:00+00:00",
                "holder_count": 15,
                "transfer_transaction_count_24h": 7,
                "transfer_event_count_24h": 11,
                "unique_active_wallets_24h": 6,
            },
        ]
    )

    assert result["state"] == "strengthening"
    assert result["holder_count"]["delta"] == 5
    assert result["unique_active_wallets_24h"]["delta"] == 2


def test_adoption_history_does_not_invent_a_trend_from_missing_metrics():
    result = compare_adoption_history(
        [
            {"observed_at": "2026-08-27T00:00:00+00:00"},
            {"observed_at": "2026-08-28T00:00:00+00:00"},
        ]
    )

    assert result["state"] == "insufficient_data"
    assert result["holder_count"]["available"] is False
