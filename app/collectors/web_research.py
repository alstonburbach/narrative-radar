import os

import requests
from dotenv import load_dotenv

from app.collectors.research_provider import ResearchProvider, ResearchResult


load_dotenv()


class TavilyResearchProvider(ResearchProvider):
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise RuntimeError("TAVILY_API_KEY is missing. Check your .env file.")

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
