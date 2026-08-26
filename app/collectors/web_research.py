import os
from typing import List, Optional

import requests
from dotenv import load_dotenv

from app.collectors.research_provider import ResearchProvider, ResearchResult


load_dotenv()


class TavilyResearchProvider(ResearchProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 20,
    ):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is missing. Check your .env file."
            )

    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[ResearchResult]:
        if not query or not query.strip():
            raise ValueError("query cannot be empty")

        limit = max(1, min(int(limit), 20))

        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": limit,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()
        payload = response.json()

        results = []

        for item in payload.get("results", []):
            results.append(
                ResearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    source="tavily",
                    published_at=item.get("published_date"),
                    author=item.get("author"),
                )
            )

        return results
