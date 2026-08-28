"""Shared narrative-discovery pipeline for CLI and phone workflows."""

from typing import Any

from app.agents.narrative_discovery import discover_narratives
from app.database.db import (
    get_discovery_history,
    initialize_database,
    save_discovery_run,
)
from app.tracking.discovery_history import compare_discovery_history


def run_discovery(
    provider: Any,
    topic: str = "crypto narratives",
    chain: str = "unknown",
    limit: int = 5,
    persist: bool = True,
    history_limit: int = 20,
) -> dict:
    """Discover leads and attach a durability comparison when persistence is on."""
    report = discover_narratives(
        provider=provider,
        topic=topic,
        chain=chain,
        limit=limit,
    )
    if persist and report["status"] != "failed":
        initialize_database()
        report["discovery_run_id"] = save_discovery_run(report)
        history = get_discovery_history(
            topic=report["topic"],
            chain=report["chain"],
            limit=history_limit,
        )
        report["discovery_history"] = compare_discovery_history(history)
    else:
        report["discovery_run_id"] = None
        report["discovery_history"] = {
            "state": "not_persisted" if not persist else "not_available",
            "run_count": 0,
        }
    return report
