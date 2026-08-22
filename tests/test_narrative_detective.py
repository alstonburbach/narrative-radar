from app.agents.narrative_detective import build_narrative_report
from app.database.models import Evidence


def test_narrative_report():

    evidence = [
        Evidence(
            claim="Example primary-source post exists",
            source_url="https://example.com/source",
            source_type="primary",
            author="Example",
            relevance="Possible narrative origin",
            confidence=0.95,
        ),
        Evidence(
            claim="Token is officially endorsed",
            source_url="https://example.com/speculation",
            source_type="social_speculation",
            relevance="Unverified interpretation",
            confidence=0.30,
        ),
    ]

    report = build_narrative_report(
        token_name="Test Token",
        token_symbol="TEST",
        evidence=evidence,
    )

    assert report["evidence_count"] == 2
    assert len(report["verified_evidence"]) == 1
    assert len(report["uncertain_evidence"]) == 1