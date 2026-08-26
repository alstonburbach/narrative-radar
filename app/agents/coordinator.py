from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.agents.narrative_detective import (
    build_narrative_report,
    evidence_from_research_results,
)
from app.agents.red_team import build_red_team_report
from app.collectors.market import fetch_market_data
from app.collectors.research_provider import ResearchProvider
from app.collectors.web_research import TavilyResearchProvider
from app.database.db import initialize_database, save_evidence, save_market_snapshot
from app.scoring.narrative_score import score_narrative
from app.tracking.paper_tracker import PaperTracker


def _result_to_dict(result: Any) -> Dict[str, Any]:
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    if isinstance(result, dict):
        return dict(result)
    return {
        "title": getattr(result, "title", ""),
        "url": getattr(result, "url", ""),
        "snippet": getattr(result, "snippet", ""),
        "source": getattr(result, "source", None),
        "published_at": getattr(result, "published_at", None),
        "author": getattr(result, "author", None),
    }


def run_pipeline(
    contract_address: str,
    requested_chain: Optional[str] = None,
    include_web: bool = True,
    research_provider: Optional[ResearchProvider] = None,
    paper_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Run the safe research pipeline and return a JSON-serializable report."""

    initialize_database()
    created_at = datetime.now(timezone.utc).isoformat()
    market = fetch_market_data(contract_address, requested_chain=requested_chain)

    snapshot_id = None
    if market.get("found"):
        snapshot_id = save_market_snapshot(market)

    research: Dict[str, Any] = {
        "enabled": include_web,
        "query": None,
        "result_count": 0,
        "results": [],
        "error": None,
    }
    evidence = []

    if include_web and market.get("found"):
        token_name = market.get("token_name") or ""
        token_symbol = market.get("token_symbol") or ""
        query = f"{token_name} {token_symbol} {contract_address} crypto narrative".strip()
        research["query"] = query

        try:
            provider = research_provider or TavilyResearchProvider()
            raw_results = provider.search(query, limit=5)
            result_dicts = [_result_to_dict(item) for item in raw_results]
            research["results"] = result_dicts
            research["result_count"] = len(result_dicts)
            evidence = evidence_from_research_results(result_dicts)
        except Exception as exc:  # provider failure should not erase market data
            research["error"] = str(exc)

    evidence_ids = []
    for item in evidence:
        evidence_ids.append(save_evidence(contract_address, item))

    narrative = build_narrative_report(
        token_name=market.get("token_name") or "Unknown token",
        token_symbol=market.get("token_symbol") or "UNKNOWN",
        evidence=evidence,
    )
    red_team = build_red_team_report(
        market=market,
        evidence=evidence,
        requested_chain=requested_chain,
    )
    score = score_narrative(market=market, evidence=evidence, red_team=red_team)

    paper_position = None
    paper_error = None
    if paper_usd is not None:
        try:
            if not market.get("found"):
                raise ValueError("cannot open a paper position without market data")
            paper_position = PaperTracker().open_position(
                contract_address=contract_address,
                token_symbol=market.get("token_symbol"),
                entry_price_usd=market.get("price_usd"),
                invested_usd=paper_usd,
            )
        except Exception as exc:
            paper_error = str(exc)

    status = "complete"
    if research.get("error"):
        status = "complete_with_research_warning"
    if not market.get("found"):
        status = "complete_without_market_data"

    return {
        "status": status,
        "created_at": created_at,
        "contract_address": contract_address,
        "requested_chain": requested_chain,
        "market": market,
        "snapshot_id": snapshot_id,
        "research": research,
        "evidence_ids": evidence_ids,
        "narrative": narrative,
        "red_team": red_team,
        "score": score,
        "paper_position": paper_position,
        "paper_error": paper_error,
        "execution": {
            "paper_only": True,
            "live_orders": False,
        },
    }
