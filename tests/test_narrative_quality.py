from app.agents.narrative_detective import results_to_evidence, run_lens_research
from app.agents.narrative_quality import assess_narrative_quality
from app.database.models import Evidence


def test_search_results_remain_unverified_and_keep_provenance():
    evidence = results_to_evidence(
        [
            {
                "title": "Project source",
                "url": "https://github.com/example/project/",
                "snippet": "contract 0xtest has public code",
            },
            {
                "title": "Social post",
                "url": "https://x.com/example/status/1",
                "snippet": "contract 0xtest is going up",
            },
        ],
        contract_address="0xtest",
        research_lens="official_builders",
        retrieved_at="2026-08-27T00:00:00+00:00",
    )

    assert evidence[0].source_type == "primary_candidate"
    assert evidence[0].verification_status == "unverified_search_lead"
    assert evidence[0].research_lens == "official_builders"
    assert evidence[0].retrieved_at == "2026-08-27T00:00:00+00:00"
    assert evidence[1].source_type == "social_lead"


def test_quality_requires_independent_lenses_and_domains():
    evidence = [
        Evidence(
            "Builder activity",
            "https://github.com/example/project",
            "primary_candidate",
            confidence=0.6,
            research_lens="official_builders",
        ),
        Evidence(
            "Usage report",
            "https://example-news.test/project",
            "secondary_lead",
            confidence=0.6,
            research_lens="adoption_usage",
        ),
        Evidence(
            "Token data",
            "https://solscan.io/token/abc",
            "onchain_data",
            confidence=0.6,
            research_lens="onchain_tokenomics",
        ),
    ]
    result = assess_narrative_quality(
        evidence,
        searched_lenses=[
            "official_builders",
            "adoption_usage",
            "onchain_tokenomics",
            "counterevidence",
        ],
    )

    assert result["independent_domain_count"] == 3
    assert result["positive_lenses_covered"] == [
        "adoption_usage",
        "official_builders",
        "onchain_tokenomics",
    ]
    assert result["classification"] == "corroborated_leads"
    assert result["verified_primary_sources"] == 0
    assert result["classification_only"] is True


def test_lens_research_is_partial_when_one_lens_fails():
    class Provider:
        def search(self, query, limit=10):
            if "scam exploit" in query:
                raise RuntimeError("temporary failure")
            return [
                {
                    "title": "A lead",
                    "url": f"https://example.test/{query.split()[-1]}",
                    "snippet": "contract 0xtest",
                }
            ]

    evidence, report = run_lens_research(
        Provider(),
        contract_address="0xtest",
        chain="base",
        token_name="Test",
        token_symbol="TEST",
        limit=1,
    )

    assert report["status"] == "partial"
    assert "counterevidence" not in report["searched_lenses"]
    assert len(evidence) == 4

def test_quality_collapses_subdomains_from_the_same_publisher_family():
    evidence = [
        Evidence(
            "Builder docs",
            "https://docs.example.com/project",
            "primary_candidate",
            confidence=0.6,
            research_lens="official_builders",
        ),
        Evidence(
            "Usage blog",
            "https://blog.example.com/usage",
            "secondary_lead",
            confidence=0.6,
            research_lens="adoption_usage",
        ),
        Evidence(
            "Independent data",
            "https://independent.org/report",
            "onchain_data",
            confidence=0.6,
            research_lens="onchain_tokenomics",
        ),
    ]

    result = assess_narrative_quality(evidence)

    assert result["independent_domains"] == ["example.com", "independent.org"]
    assert result["independent_domain_count"] == 2
