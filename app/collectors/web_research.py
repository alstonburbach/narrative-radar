import os

import requests
from dotenv import load_dotenv

from app.collectors.research_provider import ResearchProvider, ResearchResult


load_dotenv()


class TavilyResearchProvider(ResearchProvider):
    provider_name = "tavily"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is missing. Check your .env file.")
        self.requested_provider = "tavily"
        self.deep_research_active = True
        self.fallback_reason = None
        self.warnings = []

    def search(self, query: str, limit: int = 10) -> list[ResearchResult]:
        if not query or not query.strip():
            raise ValueError("query is required")
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query.strip(),
                "search_depth": "basic",
                "max_results": max(1, min(int(limit), 20)),
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        results = []
        for item in (response.json().get("results") or []):
            results.append(
                ResearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source="tavily",
                    published_at=item.get("published_date"),
                )
            )
        return results


def build_default_research_provider(
    api_key=None,
    session=None,
    preferred: str | None = None,
) -> ResearchProvider:
    """Choose Tavily or bounded public RSS with an explicit spend-aware mode."""
    mode = str(
        preferred or os.getenv("NARRATIVE_RESEARCH_PROVIDER") or "auto"
    ).strip().lower()
    if mode not in {"auto", "tavily", "public_rss"}:
        raise ValueError(
            "NARRATIVE_RESEARCH_PROVIDER must be auto, tavily, or public_rss."
        )
    if mode == "public_rss":
        from app.collectors.public_feed_research import PublicFeedResearchProvider

        provider = PublicFeedResearchProvider(session=session)
        provider.requested_provider = "public_rss"
        return provider

    resolved_key = api_key or os.getenv("TAVILY_API_KEY")
    if resolved_key:
        provider = TavilyResearchProvider(api_key=resolved_key)
        provider.requested_provider = mode
        return provider
    if mode == "tavily":
        raise RuntimeError("TAVILY_API_KEY is required for Tavily research mode.")

    from app.collectors.public_feed_research import PublicFeedResearchProvider

    provider = PublicFeedResearchProvider(session=session)
    provider.requested_provider = "auto"
    provider.fallback_reason = "tavily_key_missing"
    provider.warnings.append(
        "Deep Tavily research was requested in auto mode, but TAVILY_API_KEY "
        "is not configured; this run used public RSS only."
    )
    return provider
