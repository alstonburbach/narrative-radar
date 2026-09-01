"""Render a launch-watch JSON artifact for a phone alert and workflow state."""

import argparse
import json
from pathlib import Path

from app.github_issue_venue import render_venue_report, venue_notification_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a launch-watch report.")
    parser.add_argument("input")
    parser.add_argument("--markdown-output", default="launch-watch.md")
    parser.add_argument("--notification-output", default="launch-notification.json")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read launch-watch report: {type(exc).__name__}")
        return 2
    Path(args.markdown_output).write_text(
        render_venue_report(report), encoding="utf-8"
    )
    Path(args.notification_output).write_text(
        json.dumps(venue_notification_state(report), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
