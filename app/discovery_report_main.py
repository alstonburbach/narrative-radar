"""Render a saved discovery JSON report for GitHub summaries and alerts."""

import argparse
import json
from pathlib import Path

from app.github_issue_discovery import (
    discovery_notification_state,
    render_discovery_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a discovery report.")
    parser.add_argument("input")
    parser.add_argument("--markdown-output", default="narrative-discovery.md")
    parser.add_argument("--notification-output", default="discovery-notification.json")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read discovery report: {type(exc).__name__}")
        return 2
    Path(args.markdown_output).write_text(
        render_discovery_report(report),
        encoding="utf-8",
    )
    Path(args.notification_output).write_text(
        json.dumps(discovery_notification_state(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
