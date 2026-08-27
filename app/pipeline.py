from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.narrative_detective import (
    build_narrative_report,
    build_research_query,
    run_lens_research,
)
from app.agents.narrative_quality import assess_narrative_quality
from app.agents.red_team import run_red_team, summarize_red_team
from app.collectors.market import fetch_market_data
from app.collectors.source_verifier import verify_source_leads
from app.database.db import (
    get_narrative_history,
    initialize_database,
    save_evidence,
    save_market_snapshot,
    save_narrative_run,
)
from app.scoring.narrative_score import score_radar
from app.tracking.narrative_history import compare_narrative_history
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
        "verification": {"status": "not_run"},
    }

    if research_provider is not None and market.get("found"):
        query = build_research_query(
            contract_address=contract_address,
            chain=market.get("chain") or requested_chain,
            token_name=market.get("token_name"),
            token_symbol=market.get("token_symbol"),
        )
        research["query"] = query
        evidence, lens_research = run_lens_research(
            provider=research_provider,
            contract_address=contract_address,
            chain=market.get("chain") or requested_chain,
            token_name=market.get("token_name"),
            token_symbol=market.get("token_symbol"),
            limit=research_limit,
        )
        research.update(lens_research)
        if research["status"] == "complete":
            research["error"] = None
        else:
            research["error"] = lens_research.get("error")
        evidence, verification = verify_source_leads(
            evidence,
            identity_terms=[
                contract_address,
                market.get("token_name"),
                market.get("token_symbol"),
            ],
        )
        research["verification"] = verification
        if persist:
            for item in evidence:
                save_evidence(contract_address, item)
    elif not market.get("found"):
        research["status"] = "skipped_no_market_pair"

    narrative_quality = assess_narrative_quality(
        evidence,
        searched_lenses=research.get("searched_lenses", []),
    )
    flags = run_red_team(market, evidence)
    report = build_narrative_report(
        token_name=market.get("token_name") or "Unknown",
        token_symbol=market.get("token_symbol") or "Unknown",
        evidence=evidence,
        quality=narrative_quality,
    )
    score = score_radar(
        market,
        evidence,
        flags,
        narrative_quality=narrative_quality,
    )
    paper = (
        project_paper_position(market, paper_usd)
        if paper_usd is not None
        else {"status": "not_requested", "paper_only": True}
    )

    report = {
        "status": "complete" if market.get("found") else "no_market_pair",
        "started_at": started_at,
        "snapshot_id": snapshot_id,
        "market": market,
        "research": research,
        "narrative": report,
        "narrative_quality": narrative_quality,
        "red_team": {
            **summarize_red_team(flags),
            "flags": flags,
        },
        "score": score,
        "paper": paper,
        "disclaimer": "Research and paper-analysis output only. No orders are placed and no return is guaranteed.",
    }
    if persist and market.get("found"):
        report["narrative_run_id"] = save_narrative_run(report)
        history = get_narrative_history(contract_address)
        report["narrative_history"] = compare_narrative_history(history)
    else:
        report["narrative_run_id"] = None
        report["narrative_history"] = {
            "state": "not_persisted",
            "run_count": 0,
            "note": "Enable persistence to compare evidence across repeated runs.",
        }
    return report
