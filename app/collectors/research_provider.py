from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ResearchResult:
    title: str
    url: str
    snippet: str
    source: str | None = None
    published_at: str | None = None
    source_type: str | None = None


class ResearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[ResearchResult]:
        raise NotImplementedError
