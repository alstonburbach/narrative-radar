"""Run narrative discovery from an owner-submitted GitHub issue."""

import argparse
import json
import os
from pathlib import Path

from app.collectors.web_research import build_default_research_provider
from app.discovery_pipeline import run_discovery
from app.github_issue_discovery import (
    discovery_notification_state,
    render_discovery_error,
    render_discovery_report,
    validate_owner_discovery_event,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run owner-only narrative discovery from a GitHub issue."
    )
    parser.add_argument(
        "--event",
        default=os.getenv("GITHUB_EVENT_PATH"),
        help="Path to a GitHub issues event JSON payload",
    )
    parser.add_argument("--json-output", default="narrative-discovery.json")
    parser.add_argument("--markdown-output", default="narrative-discovery.md")
    parser.add_argument("--notification-output", default="discovery-notification.json")
    parser.add_argument("--no-persist", action="store_true")
    return parser


def _write_outputs(
    json_path: str,
    markdown_path: str,
    notification_path: str,
    payload: dict,
    markdown: str,
) -> None:
    Path(json_path).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(markdown_path).write_text(markdown, encoding="utf-8")
    Path(notification_path).write_text(
        json.dumps(discovery_notification_state(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.event:
        message = "A GitHub event payload is required."
        payload = {"status": "invalid_request", "error": message}
        _write_outputs(
            args.json_output,
            args.markdown_output,
            args.notification_output,
            payload,
            render_discovery_error(message),
        )
        return 2

    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        request = validate_owner_discovery_event(event)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        payload = {"status": "invalid_request", "error": str(exc)}
        _write_outputs(
            args.json_output,
            args.markdown_output,
            args.notification_output,
            payload,
            render_discovery_error(str(exc)),
        )
        return 2

    try:
        report = run_discovery(
            provider=build_default_research_provider(),
            topic=request["topic"],
            chain=request["chain"],
            limit=request["limit"],
            persist=not args.no_persist,
        )
        markdown = render_discovery_report(report)
    except Exception as exc:  # noqa: BLE001 - public workflow must fail closed
        message = (
            "Discovery failed safely. Review the workflow log and retry the issue."
        )
        payload = {
            "status": "discovery_failed",
            "request": request,
            "error_type": type(exc).__name__,
        }
        _write_outputs(
            args.json_output,
            args.markdown_output,
            args.notification_output,
            payload,
            render_discovery_error(message),
        )
        return 1

    _write_outputs(
        args.json_output,
        args.markdown_output,
        args.notification_output,
        report,
        markdown,
    )
    return 0 if report.get("status") in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
