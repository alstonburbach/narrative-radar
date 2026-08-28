"""Run a Narrative Radar analysis from an owner-submitted GitHub issue."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.collectors.web_research import TavilyResearchProvider
from app.github_issue_scan import (
    render_issue_error,
    render_issue_report,
    validate_owner_event,
)
from app.pipeline import run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an owner-only GitHub issue token scan."
    )
    parser.add_argument(
        "--event",
        default=os.getenv("GITHUB_EVENT_PATH"),
        help="Path to a GitHub issues event JSON payload",
    )
    parser.add_argument("--json-output", default="analysis.json")
    parser.add_argument("--markdown-output", default="report.md")
    parser.add_argument("--no-persist", action="store_true")
    return parser


def _research_provider_or_none() -> tuple[Any | None, str | None]:
    try:
        return TavilyResearchProvider(), None
    except RuntimeError as exc:
        return None, str(exc)


def _write_outputs(
    json_path: str,
    markdown_path: str,
    payload: dict,
    markdown: str,
) -> None:
    Path(json_path).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path(markdown_path).write_text(markdown, encoding="utf-8")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.event:
        message = "A GitHub event payload is required."
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {"status": "invalid_request", "error": message},
            render_issue_error(message),
        )
        return 2

    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        request = validate_owner_event(event)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {"status": "invalid_request", "error": str(exc)},
            render_issue_error(str(exc)),
        )
        return 2

    provider, provider_error = _research_provider_or_none()
    try:
        report = run_analysis(
            contract_address=request["contract_address"],
            chain=request["chain"],
            research_provider=provider,
            paper_usd=request["paper_usd"],
            order_preview_usd=request["order_preview_usd"],
            order_side=request["order_side"],
            persist=not args.no_persist,
        )
        if provider_error:
            report["research"]["error"] = provider_error
        markdown = render_issue_report(report)
    except Exception as exc:  # noqa: BLE001 - the public workflow must fail closed
        message = "The scan failed safely. Review the workflow log and retry the issue."
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {
                "status": "scan_failed",
                "request": request,
                "error_type": type(exc).__name__,
            },
            render_issue_error(message),
        )
        return 1

    _write_outputs(args.json_output, args.markdown_output, report, markdown)
    return 0 if report.get("status") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
