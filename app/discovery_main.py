import argparse
import json

from app.agents.narrative_discovery import discover_narratives
from app.collectors.web_research import TavilyResearchProvider


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
