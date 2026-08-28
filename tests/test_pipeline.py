from datetime import datetime, timezone

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
        "collected_at": datetime.now(timezone.utc).isoformat(),
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
        order_preview_usd=100,
    )

    assert report["status"] == "complete"
    assert "decision_gate" in report
    assert report["decision_gate"]["execution_enabled"] is False
    assert report["decision_gate"]["order_preview_requested"] is True
    assert report["order_preview"]["status"] == "ready_for_manual_review"
    assert report["snapshot_id"] == 7
    assert report["narrative_run_id"] == 8
    assert report["narrative_history"]["state"] == "no_history"
    assert report["research"]["result_count"] == 1
    assert report["narrative"]["evidence_count"] == 1
    assert report["paper"]["projections"][0]["estimated_value_usd"] == 200


def test_run_analysis_persists_optional_solana_activity_snapshot(monkeypatch):
    market = {
        "found": True,
        "contract_address": "mint",
        "token_name": "Solana Test",
        "token_symbol": "SOLT",
        "chain": "solana",
        "dex": "raydium",
        "pair_address": "pair",
        "price_usd": 0.01,
        "market_cap": 100_000,
        "fdv": 100_000,
        "liquidity_usd": 50_000,
        "volume_24h": 200_000,
        "price_change_24h": 15,
    }
    monkeypatch.setattr("app.pipeline.fetch_market_data", lambda *args, **kwargs: dict(market))
    monkeypatch.setattr("app.pipeline.initialize_database", lambda: None)
    monkeypatch.setattr("app.pipeline.save_market_snapshot", lambda value: 1)
    monkeypatch.setattr("app.pipeline.save_onchain_activity_snapshot", lambda value: 2)
    monkeypatch.setattr("app.pipeline.get_onchain_activity_history", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.pipeline.save_narrative_run", lambda value: 3)
    monkeypatch.setattr("app.pipeline.get_narrative_history", lambda address: [])

    class AdoptionProvider:
        def fetch_snapshot(self, **kwargs):
            assert kwargs["token_address"] == "mint"
            assert kwargs["chain"] == "solana"
            return {
                "token_address": "mint",
                "chain": "solana",
                "observed_at": "2026-08-27T00:00:00+00:00",
                "status": "complete",
                "holder_count": 20,
                "transfer_transaction_count_24h": 10,
                "unique_active_wallets_24h": 8,
            }

    report = run_analysis(
        "mint",
        chain="solana",
        adoption_provider=AdoptionProvider(),
    )

    assert report["onchain_activity"]["status"] == "complete"
    assert report["onchain_activity"]["snapshot_id"] == 2
    assert report["onchain_activity"]["history"]["state"] == "no_history"
    assert report["onchain_activity"]["holder_count"] == 20
