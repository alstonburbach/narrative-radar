from app.collectors.research_provider import ResearchResult
from app.pipeline import run_analysis


class FakeProvider:
    def search(self, query, limit=10):
        assert "contract" in query
        return [
            ResearchResult(
                title="Token discussion",
                url="https://example.com/token",
                snippet="Some public discussion.",
                source="fake",
            )
        ][:limit]


def test_run_analysis_connects_market_research_and_paper(monkeypatch):
    market = {
        "found": True,
        "contract_address": "0xtest",
        "token_name": "Test Token",
        "token_symbol": "TEST",
        "chain": "base",
        "dex": "uniswap",
        "pair_address": "0xpair",
        "price_usd": 0.01,
        "market_cap": 100_000,
        "fdv": 100_000,
        "liquidity_usd": 50_000,
        "volume_24h": 200_000,
        "price_change_24h": 15,
    }
    monkeypatch.setattr("app.pipeline.fetch_market_data", lambda *args, **kwargs: dict(market))
    monkeypatch.setattr("app.pipeline.initialize_database", lambda: None)
    monkeypatch.setattr("app.pipeline.save_market_snapshot", lambda value: 7)
    monkeypatch.setattr("app.pipeline.save_evidence", lambda *args: 1)
    monkeypatch.setattr("app.pipeline.save_narrative_run", lambda value: 8)
    monkeypatch.setattr("app.pipeline.get_narrative_history", lambda address: [])

    report = run_analysis(
        "0xtest",
        chain="base",
        research_provider=FakeProvider(),
        paper_usd=100,
    )

    assert report["status"] == "complete"
    assert report["snapshot_id"] == 7
    assert report["narrative_run_id"] == 8
    assert report["narrative_history"]["state"] == "no_history"
    assert report["research"]["result_count"] == 1
    assert report["narrative"]["evidence_count"] == 1
    assert report["paper"]["projections"][0]["estimated_value_usd"] == 200
