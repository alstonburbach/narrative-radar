from app.agents.narrative_discovery import (
    build_discovery_queries,
    build_signal_follow_up_queries,
    cluster_signal_terms,
    discover_narratives,
)


def test_discovery_queries_keep_research_lenses_separate():
    queries = build_discovery_queries(topic="stablecoin rails", chain="base")

    assert set(queries) == {
        "official_builders",
        "adoption_usage",
        "funding_backers",
        "onchain_tokenomics",
        "counterevidence",
    }
    assert all("stablecoin rails" in query for query in queries.values())
    assert all("base" in query for query in queries.values())


def test_signal_follow_up_queries_keep_the_theme_and_chain_in_each_lens():
    queries = build_signal_follow_up_queries("stablecoin rails", chain="base")

    assert set(queries) == {
        "official_builders",
        "adoption_usage",
        "funding_backers",
        "onchain_tokenomics",
        "counterevidence",
    }
    assert all('"stablecoin rails"' in query for query in queries.values())
    assert all("base" in query for query in queries.values())


def test_signal_clustering_requires_multiple_domains_and_lenses():
    evidence = [
        {
            "claim": "Public search result references crypto: Stablecoin rails",
            "quote": "stablecoin rails are being used by customers",
            "source_url": "https://github.com/example/project",
            "research_lens": "official_builders",
        },
        {
            "claim": "Public search result references crypto: Stablecoin rails",
            "quote": "stablecoin rails processed payments",
            "source_url": "https://coindesk.com/example",
            "research_lens": "adoption_usage",
        },
        {
            "claim": "Public search result references crypto: Stablecoin rails",
            "quote": "stablecoin rails have measurable volume",
            "source_url": "https://solscan.io/token/example",
            "research_lens": "onchain_tokenomics",
        },
    ]

    signals = cluster_signal_terms(evidence)
    labels = {signal["label"] for signal in signals}

    assert "stablecoin rails" in labels
    stablecoin_rails = next(signal for signal in signals if signal["label"] == "stablecoin rails")
    assert stablecoin_rails["independent_domains"] == [
        "coindesk.com",
        "github.com",
        "solscan.io",
    ]
    assert len(stablecoin_rails["lenses"]) == 3


def test_discovery_deduplicates_urls_and_reports_failed_lens():
    class Provider:
        def search(self, query, limit=10):
            if "scam exploit" in query:
                raise RuntimeError("temporary failure")
            return [
                {
                    "title": "Stablecoin rails",
                    "url": "https://example.com/shared",
                    "snippet": "stablecoin rails are growing",
                }
            ]

    report = discover_narratives(Provider(), topic="stablecoin", limit=1)

    assert report["status"] == "partial"
    assert report["lead_count"] == 1
    assert report["quality"]["classification"] == "insufficient_evidence"
    assert report["quality"]["counterevidence_leads"] == 0


def test_signal_clustering_rejects_social_only_or_counterevidence_only_terms():
    social_only = [
        {
            "claim": "social hype",
            "quote": "secret launch narrative",
            "source_url": "https://x.com/example/1",
            "source_type": "social_lead",
            "research_lens": "adoption_usage",
        },
        {
            "claim": "social hype",
            "quote": "secret launch narrative",
            "source_url": "https://reddit.com/example/1",
            "source_type": "social_lead",
            "research_lens": "counterevidence",
        },
    ]
    counter_only = [
        {
            "claim": "security warning",
            "quote": "security warning exploit risk",
            "source_url": "https://example.com/warning",
            "source_type": "secondary_lead",
            "research_lens": "counterevidence",
        },
        {
            "claim": "security warning",
            "quote": "security warning criticism",
            "source_url": "https://example.org/warning",
            "source_type": "secondary_lead",
            "research_lens": "counterevidence",
        },
    ]

    assert cluster_signal_terms(social_only) == []
    assert cluster_signal_terms(counter_only) == []


def test_signal_clustering_requires_two_positive_research_lenses():
    evidence = [
        {
            "claim": "AI agents adoption",
            "quote": "AI agents handle crypto lending",
            "source_url": "https://example.com/adoption",
            "source_type": "secondary_lead",
            "research_lens": "adoption_usage",
        },
        {
            "claim": "AI agents warning",
            "quote": "AI agents caused an unrelated security warning",
            "source_url": "https://example.org/warning",
            "source_type": "secondary_lead",
            "research_lens": "counterevidence",
        },
    ]

    assert cluster_signal_terms(evidence) == []

def test_signal_clustering_does_not_treat_subdomains_as_independent_sources():
    evidence = [
        {
            "claim": "Stablecoin rails adoption",
            "quote": "stablecoin rails processed payments",
            "source_url": "https://docs.example.com/usage",
            "source_type": "primary_candidate",
            "research_lens": "official_builders",
        },
        {
            "claim": "Stablecoin rails adoption",
            "quote": "stablecoin rails processed payments",
            "source_url": "https://blog.example.com/metrics",
            "source_type": "secondary_lead",
            "research_lens": "adoption_usage",
        },
    ]

    labels = {signal["label"] for signal in cluster_signal_terms(evidence)}

    assert "stablecoin rails" not in labels


def test_signal_clustering_does_not_count_syndicated_copy_as_corroboration():
    copied = (
        "stablecoin rails now settle enterprise payments across supported "
        "networks for twelve customers according to the company announcement"
    )
    evidence = [
        {
            "claim": "Stablecoin rails adoption",
            "quote": copied,
            "source_url": "https://one.example/story",
            "source_type": "secondary_lead",
            "research_lens": "adoption_usage",
        },
        {
            "claim": "Stablecoin rails adoption",
            "quote": copied,
            "source_url": "https://two.example/story",
            "source_type": "secondary_lead",
            "research_lens": "funding_backers",
        },
    ]

    labels = {signal["label"] for signal in cluster_signal_terms(evidence)}

    assert "stablecoin rails" not in labels
