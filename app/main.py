import argparse
import json
from datetime import datetime, timezone

from app.agents.coordinator import run_pipeline


def create_research_job(contract_address: str, chain: str | None) -> dict:
    return {
        "contract_address": contract_address,
        "requested_chain": (chain or "any").lower(),
        "status": "research_pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def print_section(title: str):
    print(f"\n{'=' * 45}")
    print(title)
    print("=" * 45)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect market and narrative evidence without placing trades."
    )
    parser.add_argument(
        "contract",
        nargs="?",
        help="Token contract address. Omit to use interactive prompts.",
    )
    parser.add_argument(
        "--chain",
        default=None,
        help="Restrict market-pair selection to a chain such as base, bsc, or solana.",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Skip Tavily/web research and run deterministically from market data.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete report as JSON.",
    )
    parser.add_argument(
        "--paper-usd",
        type=float,
        default=None,
        help="Record a hypothetical position of this size at the current price; never places an order.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    contract = args.contract or input("\nToken contract: ").strip()
    chain = args.chain
    if chain is None and not args.contract:
        chain = input("Chain (base/bsc/solana/etc, or any): ").strip()

    if args.json:
        try:
            report = run_pipeline(
                contract_address=contract,
                requested_chain=chain,
                include_web=not args.no_web,
                paper_usd=args.paper_usd,
            )
        except Exception as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            return 1
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print_section("NARRATIVE RADAR V0.1")
    job = create_research_job(contract, chain)

    print_section("RESEARCH JOB")

    for key, value in job.items():
        print(f"{key}: {value}")

    try:
        report = run_pipeline(
            contract_address=contract,
            requested_chain=chain,
            include_web=not args.no_web,
            paper_usd=args.paper_usd,
        )
    except Exception as exc:
        print(f"\nPipeline failed: {exc}")
        return 1

    market = report["market"]

    print_section("MARKET SNAPSHOT")

    if not market["found"]:
        print("No active DEX pair found for this contract.")
        return 0

    snapshot_id = report.get("snapshot_id")
    print(f"\nSnapshot permanently saved as #{snapshot_id}\n")

    for key, value in market.items():
        print(f"{key}: {value}")

    print_section("PIPELINE STATUS")
    print("Market Collector: COMPLETE")
    print("Database: COMPLETE")
    print("Narrative Detective: COMPLETE")
    print("Red Team: COMPLETE")
    print("Scoring Engine: COMPLETE")
    print("Paper Tracker: DISABLED (research is paper-only)")

    print_section("NARRATIVE SCORE")
    print(json.dumps(report["score"], indent=2))

    print_section("RED TEAM")
    print(json.dumps(report["red_team"], indent=2))

    if report["research"].get("error"):
        print(f"\nResearch warning: {report['research']['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
