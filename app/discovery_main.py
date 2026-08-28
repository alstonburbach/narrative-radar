import argparse
import json

from app.collectors.web_research import build_default_research_provider
from app.discovery_pipeline import run_discovery


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
        provider = build_default_research_provider()
    except RuntimeError as exc:
        if args.as_json:
            print(json.dumps({"status": "not_configured", "error": str(exc)}))
        else:
            print(str(exc))
        return 2

    report = run_discovery(
        provider=provider,
        topic=args.topic,
        chain=args.chain,
        limit=args.limit,
        persist=not args.no_persist,
        history_limit=args.history_limit,
    )
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
    syndication = quality.get("syndication", {})
    print(
        "Syndicated copies excluded: "
        f"{syndication.get('collapsed_source_count', 0)} "
        f"across {syndication.get('cluster_count', 0)} cluster(s)"
    )
    freshness = quality.get("freshness", {})
    print(
        "Evidence freshness: "
        f"{freshness.get('status', 'unknown')} / "
        f"{freshness.get('recent_count', 0)} recent / "
        f"{freshness.get('undated_count', 0)} undated"
    )
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
