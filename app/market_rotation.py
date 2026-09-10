"""Market-level chain and launchpad rotation scoring.

This module sits above token ranking.  It deliberately does not produce buy
signals: it classifies whether an ecosystem is hot, accelerating, stable,
cooling, or cold from normalized observations supplied by collectors.
"""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Iterable, Mapping


STATUS_ORDER = {
    "hot": 0,
    "coming_up": 1,
    "active": 2,
    "watch": 3,
    "cooling": 4,
    "cold": 5,
    "insufficient_data": 6,
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _growth(current: Any, baseline: Any) -> float | None:
    current_n, baseline_n = _num(current), _num(baseline)
    if current_n is None or baseline_n is None or baseline_n <= 0:
        return None
    return (current_n / baseline_n) - 1.0


def classify_rotation(observation: Mapping[str, Any]) -> dict:
    """Classify one chain/venue using activity plus acceleration.

    Expected fields are intentionally generic so chain-specific collectors can
    normalize their data without leaking provider assumptions into ranking.
    Current/baseline pairs may include volume_usd, fees_usd, launches,
    active_traders, liquidity_usd, and graduations.
    """
    growth = {}
    for metric in (
        "volume_usd",
        "fees_usd",
        "launches",
        "active_traders",
        "liquidity_usd",
        "graduations",
    ):
        value = _growth(observation.get(metric), observation.get(f"baseline_{metric}"))
        if value is not None:
            growth[metric] = value

    if len(growth) < 2:
        return {
            "status": "insufficient_data",
            "score": 0,
            "growth": growth,
            "confidence": "low",
            "note": "At least two comparable activity dimensions are required.",
        }

    positive = sum(1 for value in growth.values() if value >= 0.25)
    explosive = sum(1 for value in growth.values() if value >= 1.0)
    negative = sum(1 for value in growth.values() if value <= -0.25)
    average_growth = sum(growth.values()) / len(growth)

    # Score rewards breadth: one giant metric cannot single-handedly call an
    # ecosystem hot. This helps avoid mistaking one whale/token for rotation.
    score = 50 + min(30, positive * 7 + explosive * 5) - min(35, negative * 10)
    score += max(-15, min(15, average_growth * 12))
    score = max(0, min(100, round(score)))

    if negative >= max(2, len(growth) // 2) and average_growth < -0.20:
        status = "cooling"
    elif explosive >= 2 and positive >= 3:
        status = "coming_up"
    elif positive >= 3 and average_growth >= 0.35:
        status = "hot"
    elif positive >= 2:
        status = "active"
    elif negative >= 2:
        status = "cooling"
    elif average_growth < -0.40:
        status = "cold"
    else:
        status = "watch"

    return {
        "status": status,
        "score": score,
        "growth": {key: round(value, 4) for key, value in growth.items()},
        "confidence": "high" if len(growth) >= 4 else "medium",
        "note": "Rotation context is research evidence, never a token buy signal.",
    }


def build_market_rotation(observations: Iterable[Mapping[str, Any]]) -> dict:
    """Rank normalized chain and launchpad observations independently."""
    chains: dict[str, list[dict]] = defaultdict(list)
    venues: list[dict] = []
    for raw in observations:
        item = dict(raw)
        chain = str(item.get("chain") or "unknown").strip().lower()
        venue = str(item.get("venue") or "").strip().lower()
        result = {**item, "rotation": classify_rotation(item)}
        if venue:
            venues.append(result)
        else:
            chains[chain].append(result)

    chain_rows = [row for rows in chains.values() for row in rows]
    key = lambda row: (
        STATUS_ORDER.get(row["rotation"]["status"], 99),
        -row["rotation"]["score"],
    )
    return {
        "chains": sorted(chain_rows, key=key),
        "venues": sorted(venues, key=key),
        "execution_enabled": False,
    }
