from app.collectors.source_verifier import PublicSourceFetcher, verify_source_leads
from app.database.models import Evidence


class FakeFetcher:
    def __init__(self, documents):
        self.documents = documents
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        value = self.documents[url]
        if isinstance(value, Exception):
            raise value
        return value


def test_source_verifier_checks_identity_and_preserves_unverified_status():
    evidence = [
        Evidence(
            "Official lead",
            "https://github.com/example/project",
            "primary_candidate",
            quote="search snippet",
            confidence=0.6,
        ),
        Evidence(
            "On-chain lead",
            "https://solscan.io/token/example",
            "onchain_data",
            confidence=0.6,
        ),
        Evidence(
            "Social lead",
            "https://x.com/example/status/1",
            "social_lead",
            confidence=0.6,
        ),
    ]
    fetcher = FakeFetcher(
        {
            "https://github.com/example/project": {
                "text": "Project TEST documentation. Contract: 0xtest.",
                "retrieved_at": "2026-08-27T00:00:00+00:00",
            },
            "https://solscan.io/token/example": {
                "text": "Unrelated token page.",
                "retrieved_at": "2026-08-27T00:00:01+00:00",
            },
        }
    )

    result, summary = verify_source_leads(
        evidence,
        identity_terms=["0xtest", "Test"],
        fetcher=fetcher,
        max_sources=8,
    )

    assert result[0].verification_status == "content_match"
    assert result[0].claim_type == "observed_identity_match"
    assert "0xtest" in result[0].quote
    assert result[0].retrieved_at == "2026-08-27T00:00:00+00:00"
    assert result[1].verification_status == "no_identity_match"
    assert result[1].confidence == 0.15
    assert result[2].verification_status == "unverified_search_lead"
    assert summary["checked"] == 2
    assert summary["content_matches"] == 1
    assert summary["no_identity_match"] == 1
    assert len(fetcher.urls) == 2


def test_source_verifier_records_fetch_failures_without_promoting_claims():
    evidence = [
        Evidence(
            "Lead",
            "https://github.com/example/project",
            "primary_candidate",
            confidence=0.6,
        )
    ]
    result, summary = verify_source_leads(
        evidence,
        identity_terms=["0xtest"],
        fetcher=FakeFetcher(
            {"https://github.com/example/project": RuntimeError("blocked")}
        ),
    )

    assert result[0].verification_status == "fetch_failed"
    assert summary["fetch_failures"] == 1
    assert summary["status"] == "partial"


def test_public_source_fetcher_rejects_local_urls():
    fetcher = PublicSourceFetcher(session=None)
    try:
        fetcher.fetch("http://127.0.0.1/internal")
    except ValueError as exc:
        assert "private or local" in str(exc)
    else:
        raise AssertionError("local URL should not be fetched")
