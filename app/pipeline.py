from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.agents.narrative_detective import (
    build_narrative_report,
    build_research_query,
    run_lens_research,
)
from app.agents.narrative_quality import assess_narrative_quality
from app.agents.red_team import run_red_team, summarize_red_team
from app.collectors.adoption_provider import is_solana_chain
from app.collectors.market import fetch_market_data
from app.collectors.source_verifier import verify_source_leads
from app.collectors.token_security import GoPlusTokenSecurityProvider
from app.database.db import (
    get_narrative_history,
    get_onchain_activity_history,
    initialize_database,
    save_evidence,
    save_market_snapshot,
    save_narrative_run,
    save_onchain_activity_snapshot,
)
from app.execution.order_preview import build_order_preview
from app.scoring.decision_gate import evaluate_manual_review_gate
from app.scoring.narrative_score import score_radar
from app.tracking.adoption_history import compare_adoption_history
from app.tracking.narrative_history import compare_narrative_history
from app.tracking.paper_tracker import project_paper_position


def run_analysis(
    contract_address: str,
    chain: str = "unknown",
    research_provider: Optional[Any] = None,
    research_limit: int = 5,
    paper_usd: Optional[float] = None,
    order_preview_usd: Optional[float] = None,
    order_side: str = "buy",
    persist: bool = True,
    adoption_provider: Optional[Any] = None,
    adoption_holder_limit: int = 2_000,
    adoption_transfer_limit: int = 100,
    adoption_window_hours: int = 24,
    collect_onchain: bool = True,
    security_provider: Optional[Any] = None,
    collect_security: bool = True,
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
        "provider": (
            getattr(research_provider, "provider_name", None)
            if research_provider is not None
            else None
        ),
        "provider_warnings": [],
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
        research["provider_warnings"] = list(
            getattr(research_provider, "warnings", []) or []
        )
        if persist:
            for item in evidence:
                save_evidence(contract_address, item)
    elif not market.get("found"):
        research["status"] = "skipped_no_market_pair"

    token_security = {
        "status": "not_requested" if not collect_security else "pending",
        "provider": None,
        "chain": market.get("chain") or requested_chain,
        "contract_address": contract_address,
        "risk_level": "unknown",
        "hard_blockers": [],
        "promotion_eligible": False,
        "bundler_analysis": {
            "status": "not_available",
            "note": "No linked-wallet or funding-cluster adapter is configured.",
        },
        "execution_enabled": False,
    }
    if collect_security:
        if not market.get("found"):
            token_security.update(
                {
                    "status": "skipped_no_market_pair",
                    "hard_blockers": ["token_security_not_run"],
                }
            )
        else:
            provider = security_provider or GoPlusTokenSecurityProvider()
            try:
                security_result = provider.fetch(
                    contract_address=contract_address,
                    chain=market.get("chain") or requested_chain,
                )
                if not isinstance(security_result, Mapping):
                    raise RuntimeError("token security provider returned invalid data")
                token_security = dict(security_result)
            except Exception as exc:  # noqa: BLE001 - fail closed on provider errors
                token_security.update(
                    {
                        "status": "failed",
                        "provider": getattr(provider, "provider_name", "custom"),
                        "error_type": type(exc).__name__,
                        "hard_blockers": ["token_security_unavailable"],
                        "note": (
                            "Token-security collection failed closed; no safety "
                            "inference was made."
                        ),
                    }
                )

    onchain_activity = {
        "status": "not_requested" if not collect_onchain else "pending",
        "snapshot_id": None,
        "history": {
            "state": "not_requested" if not collect_onchain else "not_collected",
            "run_count": 0,
        },
        "note": (
            "On-chain activity metrics are optional and are kept separate from market volume."
        ),
    }
    if collect_onchain:
        if not market.get("found"):
            onchain_activity.update(
                {
                    "status": "skipped_no_market_pair",
                    "note": "No market pair was found, so on-chain activity collection was skipped.",
                }
            )
        elif not is_solana_chain(market.get("chain")):
            onchain_activity.update(
                {
                    "status": "unsupported_chain",
                    "chain": market.get("chain"),
                    "note": "The current on-chain activity adapter supports Solana mainnet only.",
                }
            )
        else:
            provider = adoption_provider
            provider_error = None
            if provider is None:
                try:
                    from app.collectors.adoption_provider import HeliusAdoptionProvider

                    provider = HeliusAdoptionProvider()
                except RuntimeError as exc:
                    provider_error = str(exc)
            if provider is None:
                onchain_activity.update(
                    {
                        "status": "not_configured",
                        "provider": "helius",
                        "error": provider_error,
                        "note": "Set HELIUS_API_KEY to collect Solana holder and transfer activity.",
                    }
                )
            else:
                try:
                    snapshot = provider.fetch_snapshot(
                        token_address=contract_address,
                        chain=market.get("chain") or requested_chain,
                        holder_limit=adoption_holder_limit,
                        transfer_limit=adoption_transfer_limit,
                        activity_window_hours=adoption_window_hours,
                    )
                    if hasattr(snapshot, "to_dict"):
                        snapshot = snapshot.to_dict()
                    if not isinstance(snapshot, dict):
                        raise RuntimeError("on-chain provider returned an invalid snapshot")
                    onchain_activity.update(snapshot)
                    if persist and snapshot.get("status") in {"complete", "partial"}:
                        onchain_activity["snapshot_id"] = save_onchain_activity_snapshot(snapshot)
                        history = get_onchain_activity_history(
                            contract_address,
                            chain=market.get("chain") or requested_chain,
                        )
                        onchain_activity["history"] = compare_adoption_history(history)
                    elif not persist:
                        onchain_activity["history"] = {
                            "state": "not_persisted",
                            "run_count": 0,
                            "note": "Enable persistence to compare on-chain activity across runs.",
                        }
                except Exception as exc:
                    onchain_activity.update(
                        {
                            "status": "failed",
                            "error": str(exc),
                            "note": "The on-chain collector failed closed; no activity signal was inferred.",
                        }
                    )

    narrative_quality = assess_narrative_quality(
        evidence,
        searched_lenses=research.get("searched_lenses", []),
    )
    flags = run_red_team(market, evidence, token_security=token_security)
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
    red_team_report = {
        **summarize_red_team(flags),
        "flags": flags,
    }
    order_preview = (
        build_order_preview(
            market,
            side=order_side,
            amount_usd=order_preview_usd,
        )
        if order_preview_usd is not None
        else None
    )
    decision_gate = evaluate_manual_review_gate(
        market=market,
        score=score,
        narrative_quality=narrative_quality,
        red_team=red_team_report,
        token_security=token_security,
        order_preview=order_preview,
    )

    report = {
        "status": "complete" if market.get("found") else "no_market_pair",
        "started_at": started_at,
        "snapshot_id": snapshot_id,
        "market": market,
        "research": research,
        "narrative": report,
        "narrative_quality": narrative_quality,
        "red_team": red_team_report,
        "decision_gate": decision_gate,
        "score": score,
        "paper": paper,
        "order_preview": order_preview,
        "onchain_activity": onchain_activity,
        "token_security": token_security,
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
