from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.narrative_detective import (
    build_narrative_report,
    build_research_query,
    results_to_evidence,
)
from app.agents.red_team import run_red_team, summarize_red_team
from app.collectors.market import fetch_market_data
from app.database.db import (
    initialize_database,
    save_evidence,
    save_market_snapshot,
)
from app.scoring.narrative_score import score_radar
from app.tracking.paper_tracker import project_paper_position


def run_analysis(
    contract_address: str,
    chain: str = "unknown",
    research_provider: Optional[Any] = None,
    research_limit: int = 5,
    paper_usd: Optional[float] = None,
    persist: bool = True,
) -> dict:
    if not contract_address or not contract_address.strip():
        raise ValueError("contract_address is required")
    contract_address = contract_address.strip()
    requested_chain = (chain or "unknown").strip().lower()
    started_at = datetime.now(timezone.utc).isoformat()

    if persist:
        initialize_database()

    market = fetch_market_data(
        contract_address,
        chain=None if requested_chain in {"unknown", "auto", "any"} else requested_chain,
    )
    market["requested_chain"] = requested_chain

    snapshot_id = None
    if persist and market.get("found"):
        snapshot_id = save_market_snapshot(market)

    evidence = []
    research = {
        "status": "not_configured" if research_provider is None else "pending",
        "query": None,
        "result_count": 0,
        "error": None,
    }

    if research_provider is not None and market.get("found"):
        query = build_research_query(
            contract_address=contract_address,
            chain=market.get("chain") or requested_chain,
            token_name=market.get("token_name"),
            token_symbol=market.get("token_symbol"),
        )
        research["query"] = query
        try:
            results = research_provider.search(
                query,
                limit=max(1, min(int(research_limit), 20)),
            )
            evidence = results_to_evidence(
                results,
                contract_address=contract_address,
                token_name=market.get("token_name"),
                token_symbol=market.get("token_symbol"),
            )
            research["status"] = "complete"
            research["result_count"] = len(evidence)
            if persist:
                for item in evidence:
                    save_evidence(contract_address, item)
        except Exception as exc:
            research["status"] = "failed"
            research["error"] = str(exc)
    elif not market.get("found"):
        research["status"] = "skipped_no_market_pair"

    flags = run_red_team(market, evidence)
    report = build_narrative_report(
        token_name=market.get("token_name") or "Unknown",
        token_symbol=market.get("token_symbol") or "Unknown",
        evidence=evidence,
    )
    score = score_radar(market, evidence, flags)
    paper = (
        project_paper_position(market, paper_usd)
        if paper_usd is not None
        else {"status": "not_requested", "paper_only": True}
    )

    return {
        "status": "complete" if market.get("found") else "no_market_pair",
        "started_at": started_at,
        "snapshot_id": snapshot_id,
        "market": market,
        "research": research,
        "narrative": report,
        "red_team": {
            **summarize_red_team(flags),
            "flags": flags,
        },
        "score": score,
        "paper": paper,
        "disclaimer": "Research and paper-analysis output only. No orders are placed and no return is guaranteed.",
    }
