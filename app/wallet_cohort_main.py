"""Analyze a bounded, user-supplied wallet watchlist without execution."""

import argparse
import json
import sys

from app.collectors.wallet_provider import HeliusWalletProvider
from app.database.db import get_wallet_history, initialize_database, save_wallet_run
from app.tracking.wallet_history import compare_wallet_history
from app.wallets.monitor import analyze_wallet


def build_parser():
    parser = argparse.ArgumentParser(description="Analyze a Solana wallet watchlist.")
    parser.add_argument("--wallets", required=True, help="Newline-separated wallet addresses")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--history-limit", type=int, default=20)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def parse_wallets(value):
    wallets = []
    seen = set()
    for raw in value.splitlines():
        wallet = raw.split("#", 1)[0].strip()
        if wallet and wallet not in seen:
            wallets.append(wallet)
            seen.add(wallet)
    if not wallets:
        raise ValueError("No wallet addresses supplied")
    return wallets


def run(wallets, limit=500, history_limit=20, persist=True):
    if persist:
        initialize_database()
    provider = HeliusWalletProvider()
    results = []
    for wallet in wallets:
        try:
            report = analyze_wallet(wallet, provider, max_transactions=limit)
            if persist:
                report["wallet_run_id"] = save_wallet_run(report)
                report["wallet_history"] = compare_wallet_history(
                    get_wallet_history(wallet, limit=history_limit)
                )
            else:
                report["wallet_run_id"] = None
                report["wallet_history"] = {"state": "not_persisted", "strategy_classification": "not_yet_repeatable", "run_count": 0}
            results.append(report)
        except Exception as exc:  # keep one bad address from hiding the cohort
            results.append({"wallet_address": wallet, "error": str(exc), "execution_enabled": False})
    results.sort(key=lambda item: (item.get("wallet_history", {}).get("strategy_classification") == "repeatable_realized_candidate", item.get("quality_score", 0) or 0), reverse=True)
    return {"wallet_count": len(wallets), "execution_enabled": False, "wallets": results}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        wallets = parse_wallets(args.wallets)
        report = run(wallets, args.limit, args.history_limit, not args.no_persist)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("\nNARRATIVE RADAR WALLET WATCHLIST")
        print("=" * 45)
        for item in report["wallets"]:
            history = item.get("wallet_history", {})
            print(f"{item['wallet_address']}: {history.get('strategy_classification', 'error')} / {history.get('state', 'error')}")
        print("\nNo trades are copied or executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
