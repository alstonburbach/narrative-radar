from dataclasses import asdict, dataclass
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
    claim_type: str = "lead"
    verification_status: str = "unverified_search_lead"
    research_lens: Optional[str] = None
    retrieved_at: Optional[str] = None

    def to_dict(self):
        return asdict(self)
