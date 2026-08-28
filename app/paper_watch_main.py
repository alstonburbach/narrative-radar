"""Mark open GitHub paper signals against later sampled market data."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Any, Mapping

from app.collectors.market import fetch_market_data
from app.github_issue_paper import (
    extract_paper_state,
    render_paper_alert,
    render_paper_signal_report,
)
from app.paper_signal import mark_paper_signal_state, summarize_paper_signal_states


MAX_OPEN_SIGNALS = 25
MAX_WORKERS = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update bounded, open, non-executing paper signals."
    )
    parser.add_argument("--input", required=True, help="JSON paper-comment input")
    parser.add_argument("--output", default="paper-watch.json")
    return parser


def _items(payload: Any) -> list[Mapping[str, Any]]:
    items = payload.get("signals") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Paper watch input must be a list or contain a signals list.")
    if len(items) > MAX_OPEN_SIGNALS:
        raise ValueError(f"Paper watch accepts at most {MAX_OPEN_SIGNALS} signals.")
    return items


def _mark_one(item: Mapping[str, Any]) -> dict:
    issue_number = int(item.get("issue_number") or 0)
    comment_id = int(item.get("comment_id") or 0)
    if issue_number <= 0 or comment_id <= 0:
        raise ValueError("Paper signal issue and comment identifiers must be positive.")
    state = extract_paper_state(str(item.get("body") or ""))
    if int(state.get("source_issue_number") or 0) != issue_number:
        raise ValueError("Paper signal state does not match its source issue.")
    market = fetch_market_data(
        str(state["contract_address"]),
        chain=str(state.get("chain") or "unknown"),
    )
    updated, notification = mark_paper_signal_state(state, market)
    return {
        "issue_number": issue_number,
        "comment_id": comment_id,
        "body": render_paper_signal_report(updated),
        "alert_body": render_paper_alert(notification) if notification else None,
        "notification": notification,
        "state": updated,
        "execution_enabled": False,
    }


def run_watch(payload: Any) -> dict:
    items = _items(payload)
    updates = []
    errors = []
    if items:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(items))) as executor:
            future_items = {executor.submit(_mark_one, item): item for item in items}
            for future in as_completed(future_items):
                item = future_items[future]
                try:
                    updates.append(future.result())
                except Exception as exc:  # noqa: BLE001 - isolate each scheduled signal
                    errors.append(
                        {
                            "issue_number": item.get("issue_number"),
                            "error_type": type(exc).__name__,
                        }
                    )
    updates.sort(key=lambda item: item["issue_number"])
    states = [item["state"] for item in updates]
    return {
        "status": "complete" if not errors else "partial",
        "updates": updates,
        "errors": errors,
        "aggregate": summarize_paper_signal_states(states),
        "execution_enabled": False,
    }


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = run_watch(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "status": "invalid_request",
            "error": str(exc),
            "updates": [],
            "errors": [],
            "execution_enabled": False,
        }
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return 2
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
