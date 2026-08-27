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
    assert result["recurring_signals"] == ["stablecoin rails"]
    assert result["recurring_signal_counts"]["stablecoin rails"] == 2


def test_discovery_history_finds_middle_scan_recurring_signal():
    result = compare_discovery_history(
        [
            {"started_at": "2026-08-27", "candidate_signal_labels": ["payments"]},
            {"started_at": "2026-08-28", "candidate_signal_labels": ["stablecoin rails"]},
            {"started_at": "2026-08-29", "candidate_signal_labels": ["stablecoin rails"]},
            {"started_at": "2026-08-30", "candidate_signal_labels": ["new"]},
        ]
    )

    assert result["persisted_signals"] == []
    assert result["recurring_signals"] == ["stablecoin rails"]
