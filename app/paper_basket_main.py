import argparse
import json
from pathlib import Path

from app.tracking.paper_basket import evaluate_paper_basket


def build_parser():
    parser = argparse.ArgumentParser(
        description="Evaluate a fixed-stake paper basket without placing orders."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="JSON file containing a list of positions or an object with a positions list",
    )
    parser.add_argument("--stake-usd", type=float, default=50.0)
    parser.add_argument("--target-multiple", type=float, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _load_positions(path: str):
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
        return payload["positions"]
    raise ValueError("input JSON must be a list or an object with a positions list")


def _print_human(report: dict):
    aggregate = report["aggregate"]
    target = report["target_metrics"]
    print("\nPAPER BASKET")
    print("=" * 45)
    print(f"Status: {report['status']}")
    print(f"Positions: {report['position_count']} at {report['stake_usd']:.2f} USD each")
    print(f"Committed: {aggregate['committed_usd']:.2f} USD")
    print(
        "Gross marked value: "
        + (
            f"{aggregate['gross_portfolio_value_usd']:.2f} USD"
            if aggregate["gross_portfolio_value_usd"] is not None
            else "unavailable"
        )
    )
    print(
        "PnL after known costs: "
        + (
            f"{aggregate['pnl_after_known_costs_usd']:.2f} USD"
            if aggregate["pnl_after_known_costs_usd"] is not None
            else "unavailable"
        )
    )
    print(
        "Break-even winner multiple before costs: "
        f"{report['break_even_winner_multiple_before_costs']:.2f}x"
    )
    if target["target_multiple"] is not None:
        print(
            "Realized target hits: "
            f"{target['realized_target_hit_count']} / {report['position_count']} "
            f"({target['realized_target_hit_rate_pct']}%)"
        )
    print(
        "Narrative concentration: "
        f"{report['max_narrative_family_share_pct']}% largest family"
    )
    for warning in report["warnings"]:
        print(f"- {warning}")
    print("\nNo orders are placed. This is paper analysis only.")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        positions = _load_positions(args.input)
        report = evaluate_paper_basket(
            positions,
            stake_usd=args.stake_usd,
            target_multiple=args.target_multiple,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if args.as_json:
            print(json.dumps({"status": "invalid_input", "error": str(exc)}))
        else:
            print(f"Invalid basket input: {exc}")
        return 2

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
