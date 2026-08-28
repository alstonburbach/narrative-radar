"""Start a forward-time paper signal from an owner-submitted GitHub issue."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.collectors.web_research import build_default_research_provider
from app.github_issue_paper import (
    extract_paper_state,
    render_paper_signal_error,
    render_paper_signal_report,
    validate_owner_paper_event,
)
from app.paper_signal import create_paper_signal_state
from app.pipeline import run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start an owner-only, non-executing GitHub paper signal."
    )
    parser.add_argument(
        "--event",
        default=os.getenv("GITHUB_EVENT_PATH"),
        help="Path to a GitHub issues event JSON payload",
    )
    parser.add_argument(
        "--existing-comment",
        help="Optional existing bot report; preserves its original entry on reruns",
    )
    parser.add_argument("--json-output", default="paper-signal.json")
    parser.add_argument("--markdown-output", default="paper-signal.md")
    parser.add_argument("--no-persist", action="store_true")
    return parser


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


def _research_provider_or_none() -> tuple[Any | None, str | None]:
    try:
        return build_default_research_provider(), None
    except RuntimeError as exc:
        return None, str(exc)


def _preserved_state(
    comment_path: str | None,
    issue_number: int,
    contract_address: str,
) -> dict | None:
    if not comment_path:
        return None
    path = Path(comment_path)
    if not path.exists() or not path.is_file():
        return None
    body = path.read_text(encoding="utf-8")
    if "<!-- narrative-radar-paper-state:" not in body:
        return None
    state = extract_paper_state(body)
    if int(state.get("source_issue_number") or 0) != issue_number:
        raise ValueError("Existing paper state belongs to a different issue.")
    if str(state.get("contract_address") or "").casefold() != contract_address.casefold():
        raise ValueError("Existing paper state contract does not match this issue.")
    return state


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.event:
        message = "A GitHub event payload is required."
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {"status": "invalid_request", "error": message},
            render_paper_signal_error(message),
        )
        return 2

    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        request = validate_owner_paper_event(event)
        issue = event.get("issue") or {}
        issue_number = int(issue.get("number"))
        issue_created_at = str(issue.get("created_at") or "")
        if issue_number <= 0 or not issue_created_at:
            raise ValueError("A numbered GitHub issue with a creation time is required.")
        existing = _preserved_state(
            args.existing_comment,
            issue_number,
            request["contract_address"],
        )
    except (OSError, TypeError, json.JSONDecodeError, ValueError) as exc:
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {"status": "invalid_request", "error": str(exc)},
            render_paper_signal_error(str(exc)),
        )
        return 2

    if existing is not None:
        payload = {
            "status": "existing_entry_preserved",
            "state": existing,
            "execution_enabled": False,
        }
        _write_outputs(
            args.json_output,
            args.markdown_output,
            payload,
            render_paper_signal_report(existing),
        )
        return 0

    provider, provider_error = _research_provider_or_none()
    try:
        report = run_analysis(
            contract_address=request["contract_address"],
            chain=request["chain"],
            research_provider=provider,
            paper_usd=request["stake_usd"],
            order_preview_usd=request["stake_usd"],
            order_side="buy",
            persist=not args.no_persist,
        )
        if provider_error:
            report["research"]["error"] = provider_error
        state = create_paper_signal_state(
            request=request,
            analysis=report,
            issue_number=issue_number,
            issue_created_at=issue_created_at,
        )
        payload = {
            "status": "paper_signal_started",
            "state": state,
            "entry_analysis": report,
            "execution_enabled": False,
        }
        markdown = render_paper_signal_report(state)
    except Exception as exc:  # noqa: BLE001 - public workflow must fail closed
        message = "The paper signal failed safely. Review the workflow log and retry."
        _write_outputs(
            args.json_output,
            args.markdown_output,
            {
                "status": "paper_signal_failed",
                "request": request,
                "error_type": type(exc).__name__,
                "execution_enabled": False,
            },
            render_paper_signal_error(message),
        )
        return 1

    _write_outputs(args.json_output, args.markdown_output, payload, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
