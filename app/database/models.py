from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Evidence:
    claim: str
    source_url: str
    source_type: str
    published_at: Optional[str] = None
    author: Optional[str] = None
    quote: Optional[str] = None
    relevance: Optional[str] = None
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)