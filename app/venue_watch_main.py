"""CLI entry point for the Pump.fun and Robinhood Chain launch watch."""

import argparse
import json

from app.venue_watch import run_venue_watch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch exact-contract Pump.fun and Robinhood Chain launch leads."
    )
    parser.add_argument(
        "--venues",
        default="pump_fun,robinhood_chain",
        help="Comma-separated launch venues",
    )
    parser.add_argument("--profile-limit-per-venue", type=int, default=12)
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--security-limit", type=int, default=8)
    parser.add_argument("--onchain-limit", type=int, default=1)
    parser.add_argument("--bundler-limit", type=int, default=1)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    venues = tuple(
        value.strip().lower() for value in args.venues.split(",") if value.strip()
    )
    try:
        report = run_venue_watch(
            venues=venues,
            profile_limit_per_venue=args.profile_limit_per_venue,
            candidate_limit=args.candidate_limit,
            security_limit=args.security_limit,
            onchain_limit=args.onchain_limit,
            bundler_limit=args.bundler_limit,
            persist=not args.no_persist,
        )
    except Exception as exc:  # noqa: BLE001 - scheduled public read must fail closed
        payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "execution_enabled": False,
            "note": "The launch watch failed safely; no candidate was promoted.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        notification = report.get("notification") or {}
        print(
            f"Launch watch: {report.get('candidate_count', 0)} candidates; "
            f"alerts={notification.get('candidate_count', 0)}"
        )
        for candidate in notification.get("candidates") or []:
            print(
                f"- {candidate.get('token_symbol') or 'unknown'} "
                f"{candidate.get('contract_address')} "
                f"({candidate.get('signal_status')})"
            )
        print("No order was created, signed, or submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
