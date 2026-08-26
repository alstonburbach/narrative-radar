from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ResearchResult:
    title: str
    url: str
    snippet: str
    source: Optional[str] = None
    published_at: Optional[str] = None
    author: Optional[str] = None


class ResearchProvider(ABC):

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[ResearchResult]:
        """
        Search public information and return normalized results.
        """
        raise NotImplementedError
