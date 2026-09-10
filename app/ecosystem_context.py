"""Apply market-rotation context to token research ordering.

Ecosystem momentum is a tie-breaker/context signal, never a safety override.
Hard-blocked candidates stay blocked regardless of how hot their chain or
launchpad is.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


_ROTATION_BONUS = {
    "coming_up": 8,
    "hot": 6,
    "active": 3,
    "watch": 0,
    "cooling": -4,
    "cold": -7,
    "insufficient_data": 0,
}

_HARD_BLOCKED = {
    "blocked_security",
    "blocked_linked_wallets",
    "blocked_market_risk",
}


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if isfinite(number) else 0.0


def _rotation_status(row: Mapping[str, Any] | None) -> str:
    if not row:
        return "insufficient_data"
    rotation = row.get("rotation") or {}
    return str(rotation.get("status") or "insufficient_data").strip().lower()


def apply_ecosystem_context(
    candidate: Mapping[str, Any],
    *,
    chain_rotation: Mapping[str, Any] | None = None,
    venue_rotation: Mapping[str, Any] | None = None,
) -> dict:
    """Return a research-priority score with a deliberately small context adjustment."""
    result = dict(candidate)
    signal_status = str(result.get("signal_status") or "").strip().lower()
    base_score = _score((result.get("market_screen") or {}).get("score"))

    chain_status = _rotation_status(chain_rotation)
    venue_status = _rotation_status(venue_rotation)
    chain_bonus = _ROTATION_BONUS.get(chain_status, 0)
    venue_bonus = _ROTATION_BONUS.get(venue_status, 0)

    # Cap combined ecosystem influence so token-level evidence remains dominant.
    ecosystem_adjustment = max(-10, min(10, chain_bonus + venue_bonus))
    research_priority_score = max(0, min(100, round(base_score + ecosystem_adjustment, 2)))

    result["ecosystem_context"] = {
        "chain_status": chain_status,
        "venue_status": venue_status,
        "adjustment": ecosystem_adjustment,
        "note": "Ecosystem rotation adjusts research order only; it cannot clear a safety gate.",
    }
    result["research_priority_score"] = research_priority_score

    if signal_status in _HARD_BLOCKED:
        result["research_priority_eligible"] = False
        result["research_priority_reason"] = "hard_block_preserved"
    else:
        result["research_priority_eligible"] = True
        if ecosystem_adjustment > 0:
            result["research_priority_reason"] = "ecosystem_tailwind"
        elif ecosystem_adjustment < 0:
            result["research_priority_reason"] = "ecosystem_headwind"
        else:
            result["research_priority_reason"] = "neutral_ecosystem"

    return result


def sort_by_research_priority(candidates: list[Mapping[str, Any]]) -> list[dict]:
    """Eligible research candidates first; hard blocks remain visible but sink."""
    rows = [dict(row) for row in candidates]
    return sorted(
        rows,
        key=lambda row: (
            not bool(row.get("research_priority_eligible")),
            -_score(row.get("research_priority_score")),
        ),
    )
