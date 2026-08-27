from typing import Any, Optional

from app.pipeline import run_analysis


def analyze_token(
    contract_address: str,
    chain: str = "unknown",
    research_provider: Optional[Any] = None,
    research_limit: int = 5,
    paper_usd: Optional[float] = None,
    persist: bool = True,
) -> dict:
    """Coordinate the market, research, red-team, scoring, and paper stages."""
    return run_analysis(
        contract_address=contract_address,
        chain=chain,
        research_provider=research_provider,
        research_limit=research_limit,
        paper_usd=paper_usd,
        persist=persist,
    )
