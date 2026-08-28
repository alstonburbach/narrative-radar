import argparse
import json
from typing import Optional

from app.pipeline import run_analysis


def create_research_job(contract_address: str, chain: str) -> dict:
    from datetime import datetime, timezone

    return {
        "contract_address": contract_address,
        "requested_chain": chain.lower(),
        "status": "research_pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a paper-only Narrative Radar analysis.")
    parser.add_argument("contract", nargs="?", help="Token contract address")
    parser.add_argument(
        "--contract",
        dest="contract_option",
        help="Token contract address (named form for GitHub Actions)",
    )
    parser.add_argument("--chain", default="unknown", help="Chain id, such as base or solana")
    parser.add_argument("--research-limit", type=int, default=5)
    parser.add_argument("--paper-usd", type=float, default=None)
    parser.add_argument(
        "--order-preview-usd",
        type=float,
        default=None,
        help="Build a manual-review order preview without submitting an order",
    )
    parser.add_argument(
        "--order-side",
        choices=("buy", "sell"),
        default="buy",
        help="Side used for the non-executing order preview",
    )
    parser.add_argument("--no-research", action="store_true")
    parser.add_argument(
        "--no-onchain",
        action="store_true",
        help="Skip optional Solana holder and transfer-activity collection",
    )
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _provider_or_none():
    from app.collectors.web_research import build_default_research_provider

    try:
        return build_default_research_provider(), None
    except RuntimeError as exc:
        return None, str(exc)


def _print_human(report: dict, provider_error: Optional[str] = None):
    market = report["market"]
    print("\nNARRATIVE RADAR")
    print("=" * 45)
    print(f"Status: {report['status']}")
    if market.get("found"):
        print(f"Token: {market.get('token_name')} ({market.get('token_symbol')})")
        print(f"Chain / DEX: {market.get('chain')} / {market.get('dex')}")
        print(f"Market cap: ${market.get('market_cap'):,.2f}" if market.get("market_cap") else "Market cap: n/a")
        print(f"Liquidity: ${market.get('liquidity_usd'):,.2f}" if market.get("liquidity_usd") else "Liquidity: n/a")
        print(f"24h volume: ${market.get('volume_24h'):,.2f}" if market.get("volume_24h") else "24h volume: n/a")
    print(f"Radar score: {report['score']['radar_score']} ({report['score']['rating']})")
    narrative_quality = report.get("narrative_quality", {})
    print(
        "Narrative evidence: "
        f"{narrative_quality.get('quality_score', 0)}/100 "
        f"({narrative_quality.get('classification', 'insufficient_evidence')})"
    )
    syndication = narrative_quality.get("syndication", {})
    print(
        "Syndicated copies excluded: "
        f"{syndication.get('collapsed_source_count', 0)} "
        f"across {syndication.get('cluster_count', 0)} cluster(s)"
    )
    freshness = narrative_quality.get("freshness", {})
    print(
        "Evidence freshness: "
        f"{freshness.get('status', 'unknown')} / "
        f"{freshness.get('recent_count', 0)} recent / "
        f"{freshness.get('undated_count', 0)} undated"
    )
    verification = report.get("research", {}).get("verification", {})
    print(
        "Source checks: "
        f"{verification.get('content_matches', 0)} content matches / "
        f"{verification.get('fetch_failures', 0)} fetch failures"
    )
    history = report.get("narrative_history", {})
    print(
        "Evidence trend: "
        f"{history.get('state', 'not_persisted')} "
        f"({history.get('run_count', 0)} runs)"
    )
    onchain = report.get("onchain_activity", {})
    if onchain.get("status") not in {None, "not_requested", "unsupported_chain"}:
        print(
            "On-chain activity proxy: "
            f"{onchain.get('holder_count', 'n/a')} holders / "
            f"{onchain.get('transfer_transaction_count_24h', 'n/a')} transfer txns / "
            f"{onchain.get('unique_active_wallets_24h', 'n/a')} active owners "
            f"({onchain.get('status')})"
        )
        if onchain.get("scanned_supply_coverage_pct") is not None:
            qualifier = " lower-bound" if onchain.get("holder_concentration_is_lower_bound") else ""
            print(
                "Holder distribution proxy: "
                f"{onchain['scanned_supply_coverage_pct']:.2f}% supply scanned / "
                f"largest scanned owner {onchain.get('largest_scanned_owner_share_pct', 'n/a')}%"
                f"{qualifier}"
            )
        activity_history = onchain.get("history", {})
        print(
            "On-chain trend: "
            f"{activity_history.get('state', 'not_collected')} "
            f"({activity_history.get('run_count', 0)} snapshots)"
        )
        for warning in onchain.get("warnings", []):
            print(f"- [on-chain] {warning}")
    elif onchain.get("status") == "not_configured":
        print(f"On-chain activity: not configured ({onchain.get('note')})")
    for warning in narrative_quality.get("warnings", []):
        print(f"- [evidence] {warning}")
    print(f"Risk level: {report['red_team']['risk_level']}")
    decision_gate = report.get("decision_gate") or {}
    print(f"Decision gate: {decision_gate.get('status', 'not_evaluated')}")
    security = report.get("token_security") or {}
    print(
        "Token security: "
        f"{security.get('status', 'not_available')} / "
        f"{security.get('risk_level', 'unknown')} / "
        f"blockers={len(security.get('hard_blockers') or [])}"
    )
    bundler = security.get("bundler_analysis") or {}
    print(f"Bundler/link analysis: {bundler.get('status', 'not_available')}")
    gate_requirements = {
        item.get("name"): item
        for item in decision_gate.get("requirements", [])
    }
    for requirement_name in decision_gate.get("failed_requirements", []):
        requirement = gate_requirements.get(requirement_name, {})
        print(
            f"- [gate] {requirement_name}: "
            f"{requirement.get('detail', 'Requirement needs review.')}"
        )
    for flag in report["red_team"]["flags"]:
        print(f"- [{flag['severity']}] {flag['message']}")
    print(f"Research: {report['research']['status']} ({report['research']['result_count']} results)")
    if provider_error:
        print(f"Research note: {provider_error}")
    if report["paper"].get("status") == "ready":
        print("\nPaper projections:")
        for row in report["paper"]["projections"]:
            print(f"- ${row['target_market_cap']:,.0f} MC -> ${row['estimated_value_usd']:,.2f} value / ${row['estimated_pnl_usd']:,.2f} PnL")
    preview = report.get("order_preview")
    if preview:
        print("\nOrder preview:")
        print(
            "- "
            + preview["side"].upper()
            + " "
            + str(preview["notional_usd"])
            + " ("
            + preview["status"]
            + ")"
        )
        print("- Estimated token amount: " + str(preview.get("estimated_token_amount", "n/a")))
        print(
            "- Manual approval required: "
            + str(preview["manual_approval_required"])
            + "; execution enabled: "
            + str(preview["execution_enabled"])
        )
        for check in preview["checks"]:
            print(
                "- ["
                + check["status"]
                + "] "
                + check["name"]
                + ": "
                + check["detail"]
            )
    print("\nNo orders are placed. This is research and paper-analysis output only.")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    contract = args.contract or args.contract_option or input("Token contract: ").strip()
    if not contract:
        print("A token contract is required.")
        return 2
    chain = args.chain

    provider = None
    provider_error = None
    if not args.no_research:
        provider, provider_error = _provider_or_none()

    report = run_analysis(
        contract_address=contract,
        chain=chain,
        research_provider=provider,
        research_limit=args.research_limit,
        paper_usd=args.paper_usd,
        order_preview_usd=args.order_preview_usd,
        order_side=args.order_side,
        persist=not args.no_persist,
        collect_onchain=not args.no_onchain,
    )
    if provider_error:
        report["research"]["error"] = provider_error

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, provider_error)
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
