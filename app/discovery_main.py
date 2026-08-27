import argparse
import json

from app.agents.narrative_discovery import discover_narratives
from app.collectors.web_research import TavilyResearchProvider
from app.database.db import (
    get_discovery_history,
    initialize_database,
    save_discovery_run,
)
from app.tracking.discovery_history import compare_discovery_history


def build_parser():
    parser = argparse.ArgumentParser(
        description="Discover and stress-test crypto narrative leads."
    )
    parser.add_argument(
        "--topic",
        default="crypto narratives",
        help="Optional sector or theme to investigate",
    )
    parser.add_argument("--chain", default="unknown")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--history-limit",
        type=int,
        default=20,
        help="Number of prior scans to use for durability comparison",
    )
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        provider = TavilyResearchProvider()
    except RuntimeError as exc:
        if args.as_json:
            print(json.dumps({"status": "not_configured", "error": str(exc)}))
        else:
            print(str(exc))
        return 2

    report = discover_narratives(
        provider=provider,
        topic=args.topic,
        chain=args.chain,
        limit=args.limit,
    )
    if not args.no_persist and report["status"] != "failed":
        initialize_database()
        report["discovery_run_id"] = save_discovery_run(report)
        history = get_discovery_history(
            topic=report["topic"],
            chain=report["chain"],
            limit=args.history_limit,
        )
        report["discovery_history"] = compare_discovery_history(history)
    else:
        report["discovery_run_id"] = None
        report["discovery_history"] = {
            "state": "not_persisted" if args.no_persist else "not_available",
            "run_count": 0,
        }
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] != "failed" else 1

    print("\nNARRATIVE RADAR DISCOVERY")
    print("=" * 45)
    print(f"Topic: {report['topic']}")
    print(f"Status: {report['status']}")
    quality = report["quality"]
    print(
        "Evidence quality: "
        f"{quality['quality_score']}/100 ({quality['classification']})"
    )
    print(f"Independent domains: {report['independent_domain_count']}")
    history = report.get("discovery_history", {})
    print(
        "Scan durability: "
        f"{history.get('state', 'not_available')} "
        f"({history.get('run_count', 0)} scans)"
    )
    print("\nCandidate signals:")
    if report["candidate_signals"]:
        for signal in report["candidate_signals"]:
            print(
                f"- {signal['label']} "
                f"({signal['independent_domains']}, lenses={signal['lenses']})"
            )
    else:
        print("- No repeated cross-source signal met the minimum threshold.")
    print("\nWarnings:")
    for warning in quality["warnings"]:
        print(f"- {warning}")
    print("\nNo trade signal or order is produced.")
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
