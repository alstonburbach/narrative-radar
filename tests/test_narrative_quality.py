from datetime import datetime, timezone

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

def test_quality_reports_recent_stale_and_undated_evidence_separately():
    evidence = [
        Evidence(
            "Recent usage",
            "https://recent.example/report",
            "secondary_lead",
            published_at="2026-08-20T00:00:00Z",
            retrieved_at="2026-08-27T00:00:00Z",
            confidence=0.6,
        ),
        Evidence(
            "Old docs",
            "https://old.example/docs",
            "primary_candidate",
            published_at="2025-01-01",
            confidence=0.6,
        ),
        Evidence(
            "Undated page",
            "https://undated.example/page",
            "web_search",
            retrieved_at="2026-08-27T00:00:00Z",
            confidence=0.4,
        ),
    ]

    result = assess_narrative_quality(
        evidence,
        as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )
    freshness = result["freshness"]

    assert freshness["status"] == "recent_evidence_present"
    assert freshness["dated_count"] == 2
    assert freshness["undated_count"] == 1
    assert freshness["recent_count"] == 1
    assert freshness["stale_count"] == 1


def test_quality_does_not_treat_retrieval_time_as_publication_time():
    result = assess_narrative_quality(
        [
            Evidence(
                "Undated page",
                "https://example.com/page",
                "web_search",
                retrieved_at="2026-08-27T00:00:00Z",
            )
        ],
        as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    assert result["freshness"]["status"] == "unknown"
    assert result["freshness"]["recent_count"] == 0
    assert any("freshness is unknown" in warning for warning in result["warnings"])


def test_quality_marks_all_old_dated_evidence_as_stale_only():
    result = assess_narrative_quality(
        [
            Evidence(
                "Old report",
                "https://example.com/report",
                "secondary_lead",
                published_at="2025-01-01",
            )
        ],
        as_of=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    assert result["freshness"]["status"] == "stale_only"
    assert result["freshness"]["stale_count"] == 1


def test_quality_excludes_syndicated_excerpts_from_independence():
    copied = (
        "Acme announced its payment rails now process settlement for twelve "
        "enterprise customers across three supported networks this quarter."
    )
    evidence = [
        Evidence(
            "Acme announcement",
            "https://acme.example/news",
            "primary_candidate",
            quote=copied,
            confidence=0.6,
            research_lens="official_builders",
        ),
        Evidence(
            "Wire copy",
            "https://news-one.example/acme",
            "secondary_lead",
            quote=copied,
            confidence=0.6,
            research_lens="adoption_usage",
        ),
        Evidence(
            "Another wire copy",
            "https://news-two.example/acme",
            "secondary_lead",
            quote=copied,
            confidence=0.6,
            research_lens="funding_backers",
        ),
    ]

    result = assess_narrative_quality(evidence)

    assert result["raw_independent_domain_count"] == 3
    assert result["independent_domain_count"] == 1
    assert result["syndication"]["cluster_count"] == 1
    assert result["syndication"]["collapsed_source_count"] == 2
    assert result["classification"] == "insufficient_evidence"
    assert any("syndicated" in warning for warning in result["warnings"])


def test_quality_keeps_short_or_distinct_excerpts_independent():
    evidence = [
        Evidence(
            "Usage report",
            "https://one.example/report",
            "secondary_lead",
            quote="Acme usage grew.",
            confidence=0.6,
            research_lens="adoption_usage",
        ),
        Evidence(
            "Builder report",
            "https://two.example/report",
            "primary_candidate",
            quote=(
                "Developers shipped a separate open source release with audited "
                "code and documented upgrade controls for the protocol."
            ),
            confidence=0.6,
            research_lens="official_builders",
        ),
    ]

    result = assess_narrative_quality(evidence)

    assert result["independent_domain_count"] == 2
    assert result["syndication"]["collapsed_source_count"] == 0
