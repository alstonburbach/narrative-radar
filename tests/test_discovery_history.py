from app.tracking.discovery_history import compare_discovery_history


def test_discovery_history_requires_two_scans():
    result = compare_discovery_history(
        [
            {
                "started_at": "2026-08-27T00:00:00+00:00",
                "candidate_signal_labels": ["stablecoin rails"],
            }
        ]
    )

    assert result["state"] == "insufficient_history"


def test_discovery_history_tracks_persisted_and_new_signals():
    result = compare_discovery_history(
        [
            {
                "started_at": "2026-08-27T00:00:00+00:00",
                "quality_score": 40,
                "independent_domain_count": 2,
                "lead_count": 8,
                "candidate_signal_labels": ["stablecoin rails", "payments"],
            },
            {
                "started_at": "2026-08-28T00:00:00+00:00",
                "quality_score": 52,
                "independent_domain_count": 3,
                "lead_count": 10,
                "candidate_signal_labels": ["stablecoin rails", "new users"],
            },
        ]
    )

    assert result["state"] == "strengthening"
    assert result["persisted_signals"] == ["stablecoin rails"]
    assert result["new_signals"] == ["new users"]
    assert result["dropped_signals"] == ["payments"]
