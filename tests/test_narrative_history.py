from app.tracking.narrative_history import compare_narrative_history


def test_history_requires_two_runs_before_calling_a_narrative_durable():
    result = compare_narrative_history(
        [
            {
                "started_at": "2026-08-27T00:00:00+00:00",
                "classification": "promising_leads",
                "quality_score": 45,
            }
        ]
    )

    assert result["state"] == "insufficient_history"
    assert result["run_count"] == 1


def test_history_marks_improving_adoption_evidence_as_strengthening():
    result = compare_narrative_history(
        [
            {
                "started_at": "2026-08-27T00:00:00+00:00",
                "classification": "promising_leads",
                "quality_score": 45,
                "independent_domain_count": 2,
                "positive_lens_count": 2,
                "adoption_evidence_count": 1,
                "adoption_content_matches": 0,
                "counterevidence_leads": 1,
            },
            {
                "started_at": "2026-08-29T00:00:00+00:00",
                "classification": "corroborated_leads",
                "quality_score": 65,
                "independent_domain_count": 4,
                "positive_lens_count": 4,
                "adoption_evidence_count": 3,
                "adoption_content_matches": 2,
                "counterevidence_leads": 1,
            },
        ]
    )

    assert result["state"] == "strengthening"
    assert result["quality_score"]["delta"] == 20
    assert result["adoption_usage"]["evidence_count"]["delta"] == 2
    assert result["adoption_usage"]["content_matches"]["delta"] == 2


def test_history_marks_more_counterevidence_without_adoption_as_weakening():
    result = compare_narrative_history(
        [
            {
                "started_at": "2026-08-27T00:00:00+00:00",
                "quality_score": 65,
                "independent_domain_count": 4,
                "positive_lens_count": 4,
                "adoption_evidence_count": 3,
                "adoption_content_matches": 2,
                "counterevidence_leads": 0,
            },
            {
                "started_at": "2026-08-29T00:00:00+00:00",
                "quality_score": 64,
                "independent_domain_count": 4,
                "positive_lens_count": 4,
                "adoption_evidence_count": 3,
                "adoption_content_matches": 2,
                "counterevidence_leads": 2,
            },
        ]
    )

    assert result["state"] == "weakening"
