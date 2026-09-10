"""SQLite persistence and baseline building for ecosystem rotation.

Snapshots are descriptive research data. Historical averages provide the
comparison required by ``market_rotation.classify_rotation``; they never
authorize execution or bypass token-level safety checks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from app.database.db import get_connection
from app.venue_registry import normalize_chain


_METRICS = (
    "volume_usd",
    "fees_usd",
    "launches",
    "active_traders",
    "liquidity_usd",
    "graduations",
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0 else None


def initialize_rotation_history() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ecosystem_activity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                chain TEXT NOT NULL,
                venue TEXT NOT NULL DEFAULT '',
                observed_at TEXT NOT NULL,
                volume_usd REAL,
                fees_usd REAL,
                launches REAL,
                active_traders REAL,
                liquidity_usd REAL,
                graduations REAL,
                source TEXT NOT NULL,
                coverage_status TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ecosystem_activity_history
            ON ecosystem_activity_snapshots (
                entity_type, chain, venue, observed_at DESC
            )
            """
        )


def save_activity_snapshot(snapshot: Mapping[str, Any]) -> int:
    initialize_rotation_history()
    chain = normalize_chain(snapshot.get("chain"))
    venue = str(snapshot.get("venue") or "").strip().lower()
    entity_type = "venue" if venue else "chain"
    if not chain:
        raise ValueError("chain is required")
    observed_at = str(
        snapshot.get("observed_at") or datetime.now(timezone.utc).isoformat()
    )
    source = str(snapshot.get("source") or "unknown")[:120]
    coverage = str(snapshot.get("coverage_status") or "partial")[:40]
    metrics = {metric: _number(snapshot.get(metric)) for metric in _METRICS}
    normalized = {
        "entity_type": entity_type,
        "chain": chain,
        "venue": venue,
        "observed_at": observed_at,
        "source": source,
        "coverage_status": coverage,
        **metrics,
    }
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ecosystem_activity_snapshots (
                entity_type, chain, venue, observed_at,
                volume_usd, fees_usd, launches, active_traders,
                liquidity_usd, graduations, source, coverage_status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_type, chain, venue, observed_at,
                metrics["volume_usd"], metrics["fees_usd"], metrics["launches"],
                metrics["active_traders"], metrics["liquidity_usd"],
                metrics["graduations"], source, coverage, json.dumps(normalized),
            ),
        )
        return cursor.lastrowid


def history_for(*, chain: str, venue: str | None = None, limit: int = 32) -> list[dict]:
    initialize_rotation_history()
    normalized_chain = normalize_chain(chain)
    normalized_venue = str(venue or "").strip().lower()
    entity_type = "venue" if normalized_venue else "chain"
    limit = max(1, min(int(limit), 500))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT entity_type, chain, venue, observed_at,
                   volume_usd, fees_usd, launches, active_traders,
                   liquidity_usd, graduations, source, coverage_status
            FROM ecosystem_activity_snapshots
            WHERE entity_type = ? AND chain = ? AND venue = ?
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (entity_type, normalized_chain, normalized_venue, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def with_historical_baseline(
    current: Mapping[str, Any],
    history: list[Mapping[str, Any]],
    *,
    minimum_samples: int = 3,
) -> dict:
    """Attach per-metric historical means without fabricating missing data."""
    result = dict(current)
    usable = [row for row in history if row.get("coverage_status") != "failed"]
    result["baseline_sample_count"] = len(usable)
    if len(usable) < minimum_samples:
        result["baseline_status"] = "insufficient_history"
        return result

    baseline_dimensions = 0
    for metric in _METRICS:
        values = [_number(row.get(metric)) for row in usable]
        clean = [value for value in values if value is not None]
        if len(clean) < minimum_samples:
            continue
        result[f"baseline_{metric}"] = sum(clean) / len(clean)
        baseline_dimensions += 1

    result["baseline_status"] = (
        "ready" if baseline_dimensions >= 2 else "insufficient_dimensions"
    )
    result["baseline_dimension_count"] = baseline_dimensions
    return result


def prepare_rotation_observation(snapshot: Mapping[str, Any], *, history_limit: int = 28) -> dict:
    chain = normalize_chain(snapshot.get("chain"))
    venue = str(snapshot.get("venue") or "").strip().lower() or None
    prior = history_for(chain=chain or "unknown", venue=venue, limit=history_limit)
    # Do not compare a sample against itself if a caller persisted it first.
    observed_at = str(snapshot.get("observed_at") or "")
    prior = [row for row in prior if str(row.get("observed_at") or "") != observed_at]
    return with_historical_baseline(snapshot, prior)
