import argparse
import json

from app.collectors.wallet_provider import HeliusWalletProvider
from app.database.db import (
    get_wallet_history,
    initialize_database,
    save_wallet_run,
)
from app.tracking.wallet_history import compare_wallet_history
from app.wallets.monitor import analyze_wallet


def build_parser():
    parser = argparse.ArgumentParser(description="Analyze a Solana wallet using realized, paper-only accounting.")
    parser.add_argument("wallet", help="Solana wallet address")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--history-limit", type=int, default=20)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.no_persist:
        initialize_database()
    provider = HeliusWalletProvider()
    report = analyze_wallet(args.wallet, provider, max_transactions=args.limit)
    if not args.no_persist:
        report["wallet_run_id"] = save_wallet_run(report)
        report["wallet_history"] = compare_wallet_history(
            get_wallet_history(args.wallet, limit=args.history_limit)
        )
    else:
        report["wallet_run_id"] = None
        report["wallet_history"] = {
            "state": "not_persisted",
            "strategy_classification": "not_yet_repeatable",
            "run_count": 0,
        }
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        pnl = report["pnl"]
        print("\nNARRATIVE RADAR WALLET REPORT")
        print("=" * 45)
        print(f"Wallet: {report['wallet_address']}")
        print(f"Transactions fetched: {report['transaction_count_fetched']}")
        print(f"Closed trades: {pnl['closed_trades']}")
        print(f"Realized PnL by quote asset: {pnl['realized_pnl_by_quote_asset']}")
        print(
            "Profit concentration: "
            f"{(pnl.get('trade_pnl_stats') or {}).get('largest_win_share_pct', 'n/a')}% "
            "from largest winning trade"
        )
        profile = pnl.get("strategy_profile") or {}
        print(
            "Observed strategy window: "
            f"{profile.get('observed_span_days', 'n/a')} days / "
            f"{profile.get('profitable_months', 'n/a')} profitable months / "
            f"{profile.get('style', 'n/a')}"
        )
        flow = report.get("external_flow") or {}
        print(
            "External flow sources: "
            f"{flow.get('external_inflow_counterparty_count', 0)} known inflow source(s); "
            f"largest share {flow.get('largest_inflow_source_share_pct', 'n/a')}%"
        )
        print(f"Research candidate: {report['research_candidate']}")
        history = report["wallet_history"]
        print(
            "Strategy repeatability: "
            f"{history.get('strategy_classification')} / {history.get('state')} "
            f"({history.get('run_count', 0)} runs)"
        )
        for flag in report["flags"]:
            print(f"- {flag}")
        print("\nNo trades are copied or executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
