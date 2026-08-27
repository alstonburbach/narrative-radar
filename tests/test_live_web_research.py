import os

import pytest

from app.collectors.web_research import TavilyResearchProvider


def test_tavily_search_normalizes_results(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Example result",
                        "url": "https://example.com/result",
                        "content": "A short snippet.",
                        "published_date": "2026-01-01",
                    }
                ]
            }

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())
    provider = TavilyResearchProvider(api_key="test-key")
    results = provider.search("test token", limit=5)

    assert len(results) == 1
    assert results[0].title == "Example result"
    assert results[0].source == "tavily"


@pytest.mark.integration
def test_live_search():
    if not os.getenv("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY is not configured")
    provider = TavilyResearchProvider()
    results = provider.search("Bicat Binance Flap crypto", limit=5)
    assert len(results) > 0
