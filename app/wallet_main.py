import argparse
import json

from app.collectors.wallet_provider import HeliusWalletProvider
from app.wallets.monitor import analyze_wallet


def build_parser():
    parser = argparse.ArgumentParser(description="Analyze a Solana wallet using realized, paper-only accounting.")
    parser.add_argument("wallet", help="Solana wallet address")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    provider = HeliusWalletProvider()
    report = analyze_wallet(args.wallet, provider, max_transactions=args.limit)
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
        print(f"Research candidate: {report['research_candidate']}")
        for flag in report["flags"]:
            print(f"- {flag}")
        print("\nNo trades are copied or executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
