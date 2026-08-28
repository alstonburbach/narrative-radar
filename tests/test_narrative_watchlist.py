from datetime import datetime, timezone

from app.github_issue_discovery import (
    discovery_notification_state,
    render_discovery_report,
)
from app.narrative_watchlist import build_narrative_options


def _report():
    published = datetime.now(timezone.utc).isoformat()
    evidence = [
        {
            "claim": "Stablecoin payment rails developer release",
            "quote": "Builders released stablecoin payment rails.",
            "source_url": "https://official.example/rails",
            "source_type": "primary_candidate",
            "research_lens": "official_builders",
            "published_at": published,
            "confidence": 0.5,
        },
        {
            "claim": "Stablecoin payment rails adoption",
            "quote": "Customers are using stablecoin payment rails.",
            "source_url": "https://news.example/rails",
            "source_type": "secondary_lead",
            "research_lens": "adoption_usage",
            "published_at": published,
            "confidence": 0.5,
        },
        {
            "claim": "Stablecoin payment rails volume",
            "quote": "Stablecoin payment rails show transaction volume.",
            "source_url": "https://data.example/rails",
            "source_type": "onchain_data",
            "research_lens": "onchain_tokenomics",
            "published_at": published,
            "confidence": 0.5,
        },
    ]
    return {
        "topic": "crypto narratives",
        "status": "complete",
        "research_provider": "public_rss",
        "provider_warnings": [],
        "lead_count": 3,
        "independent_domain_count": 3,
        "searched_lenses": [
            "official_builders",
            "adoption_usage",
            "onchain_tokenomics",
            "counterevidence",
        ],
        "lenses": {"counterevidence": {"status": "complete"}},
        "candidate_signals": [
            {
                "label": "stablecoin rails",
                "signal_score": 80,
                "independent_domains": [
                    "official.example",
                    "news.example",
                    "data.example",
                ],
                "positive_lenses": [
                    "official_builders",
                    "adoption_usage",
                    "onchain_tokenomics",
                ],
                "evidence_urls": [item["source_url"] for item in evidence],
            }
        ],
        "evidence": evidence,
        "quality": {
            "quality_score": 65,
            "classification": "corroborated_leads",
            "freshness": {"recent_count": 3},
            "warnings": [],
        },
        "discovery_history": {
            "state": "mixed_or_stable",
            "run_count": 3,
            "recurring_signals": ["stablecoin rails"],
            "persisted_since_previous": ["stablecoin rails"],
        },
    }


def test_watchlist_ranks_researched_theme_but_blocks_buy_review():
    report = _report()
    options = build_narrative_options(report)
    option = options[0]

    assert option["status"] == "research_next"
    assert option["rank"] == 1
    assert option["strong_source_present"] is True
    assert option["durable_across_scans"] is True
    assert option["possible_buy_review_status"] == "blocked_pending_token_checks"
    assert "bundler_or_linked_wallet_concentration" in option["required_token_checks"]
    assert option["execution_enabled"] is False

    report["narrative_options"] = options
    markdown = render_discovery_report(report)
    assert "Automatic narrative watch options" in markdown
    assert "blocked until an exact token contract passes" in markdown
    assert "Scan a token" in markdown


def test_missing_freshness_withholds_researched_watch_option_notification():
    report = _report()
    for item in report["evidence"]:
        item["published_at"] = None
    report["narrative_options"] = build_narrative_options(report)

    assert report["narrative_options"][0]["status"] == "insufficient_evidence"
    assert discovery_notification_state(report) == {
        "notify": False,
        "reason": "no_researched_watch_options",
    }
