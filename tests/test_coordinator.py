from pathlib import Path

import app.database.db as db
from app.agents.coordinator import run_pipeline
from app.collectors import market
from app.collectors.research_provider import ResearchResult


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "pairs": [
                {
                    "chainId": "base",
                    "dexId": "uniswap",
                    "pairAddress": "0xpair",
                    "url": "https://dex.example/pair",
                    "baseToken": {"name": "Example Cat", "symbol": "CAT"},
                    "quoteToken": {"symbol": "WETH"},
                    "priceUsd": "2.00",
                    "liquidity": {"usd": 100000},
                    "volume": {"h24": 50000},
                    "priceChange": {"h24": 5},
                }
            ]
        }


class FakeProvider:
    def search(self, query, limit=10):
        return [
            ResearchResult(
                title="Example primary announcement",
                url="https://example.com/announcement",
                snippet="The project announced a launch.",
                source="primary",
            )
        ]


def test_run_pipeline_saves_market_and_evidence(monkeypatch, tmp_path: Path):
    original_path = db.DATABASE_PATH
    db.DATABASE_PATH = tmp_path / "pipeline.db"
    monkeypatch.setattr(market.requests, "get", lambda *args, **kwargs: FakeResponse())

    try:
        report = run_pipeline(
            contract_address="0xtest",
            requested_chain="base",
            include_web=True,
            research_provider=FakeProvider(),
            paper_usd=25,
        )

        assert report["status"] == "complete"
        assert report["snapshot_id"] == 1
        assert report["evidence_ids"] == [1]
        assert report["narrative"]["evidence_count"] == 1
        assert report["execution"]["live_orders"] is False
        assert report["paper_position"]["invested_usd"] == 25
    finally:
        db.DATABASE_PATH = original_path
