"""Analyze a bounded, user-supplied wallet watchlist without execution."""

import argparse
import json
import sys

from app.collectors.wallet_provider import HeliusWalletProvider
from app.database.db import get_wallet_history, initialize_database, save_wallet_run
from app.tracking.wallet_history import compare_wallet_history
from app.wallets.monitor import analyze_wallet


MAX_WALLETS = 50
MAX_TRANSACTIONS = 10_000
MAX_HISTORY = 200


def _bounded_int(value, name, minimum, maximum):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


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
    if len(wallets) > MAX_WALLETS:
        raise ValueError(f"At most {MAX_WALLETS} wallets may be analyzed per run")
    return wallets


def run(wallets, limit=500, history_limit=20, persist=True):
    wallets = parse_wallets("\n".join(wallets))
    limit = _bounded_int(limit, "limit", 1, MAX_TRANSACTIONS)
    history_limit = _bounded_int(history_limit, "history_limit", 1, MAX_HISTORY)
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
    priority = {
        "repeatable_realized_candidate": 0,
        "promising_but_short_history": 1,
        "recent_performance_mixed": 2,
        "same_snapshot_repeated": 3,
        "contaminated_or_incomplete": 4,
        "not_yet_repeatable": 5,
        "error": 6,
    }

    def sort_key(item):
        history = item.get("wallet_history") or {}
        classification = history.get("strategy_classification", "error")
        try:
            quality = float(item.get("quality_score") or 0)
        except (TypeError, ValueError):
            quality = 0
        return (priority.get(classification, 6), -quality, item.get("wallet_address", ""))

    results.sort(key=sort_key)
    classifications = {}
    for item in results:
        classification = (item.get("wallet_history") or {}).get(
            "strategy_classification", "error"
        )
        classifications[classification] = classifications.get(classification, 0) + 1
        item["watchlist_status"] = (
            "strong_candidate"
            if classification == "repeatable_realized_candidate"
            else "early_watch"
            if classification == "promising_but_short_history"
            else "do_not_rank"
        )

    return {
        "wallet_count": len(wallets),
        "execution_enabled": False,
        "wallets": results,
        "summary": {
            "classification_counts": classifications,
            "strong_candidate_count": classifications.get(
                "repeatable_realized_candidate", 0
            ),
            "early_watch_count": classifications.get("promising_but_short_history", 0),
            "excluded_from_ranking_count": sum(
                count
                for classification, count in classifications.items()
                if classification
                not in {"repeatable_realized_candidate", "promising_but_short_history"}
            ),
            "note": (
                "Strong candidates have repeated clean realized-PnL evidence. Early-watch "
                "wallets need more history. Contaminated, mixed, unchanged, and failed "
                "results are deliberately not ranked as strategy candidates."
            ),
        },
    }


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
        summary = report["summary"]
        print(
            f"Strong candidates: {summary['strong_candidate_count']} | "
            f"Early watch: {summary['early_watch_count']} | "
            f"Excluded: {summary['excluded_from_ranking_count']}"
        )
        for item in report["wallets"]:
            history = item.get("wallet_history", {})
            print(
                f"{item['wallet_address']}: "
                f"{history.get('strategy_classification', 'error')} / "
                f"{history.get('state', 'error')} / {item['watchlist_status']}"
            )
        print("\nNo trades are copied or executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
