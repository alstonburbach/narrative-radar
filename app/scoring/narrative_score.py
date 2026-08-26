from typing import Any, Dict, Iterable, Optional

from app.database.models import Evidence


def _number(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_narrative(
    market: Dict[str, Any],
    evidence: Iterable[Evidence],
    red_team: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a transparent research score, never an automatic buy/sell decision."""

    evidence = list(evidence)
    red_team = red_team or {"warnings": []}

    if evidence:
        average_confidence = sum(item.confidence for item in evidence) / len(evidence)
        evidence_quality = _clamp(average_confidence * 50)
        source_diversity = _clamp(len({item.source_type for item in evidence}) * 15)
        primary_bonus = 20 if any(item.source_type.lower() == "primary" for item in evidence) else 0
        evidence_component = _clamp(evidence_quality + source_diversity + primary_bonus)
    else:
        evidence_component = 0.0

    liquidity = _number(market.get("liquidity_usd"))
    volume_24h = _number(market.get("volume_24h"))
    change_24h = _number(market.get("price_change_24h"))

    liquidity_component = _clamp((liquidity or 0) / 100_000 * 100)
    volume_component = _clamp((volume_24h or 0) / 500_000 * 100)
    momentum_component = _clamp(50 + (change_24h or 0) * 1.5)
    market_component = (
        liquidity_component * 0.45
        + volume_component * 0.35
        + momentum_component * 0.20
        if market.get("found")
        else 0.0
    )

    warning_penalty = sum(
        15 if warning.get("severity") == "high" else 7
        for warning in red_team.get("warnings", [])
    )
    raw_score = evidence_component * 0.55 + market_component * 0.45 - warning_penalty
    score = round(_clamp(raw_score), 2)

    if score >= 75:
        label = "strong_research_case"
    elif score >= 55:
        label = "watchlist"
    elif score >= 35:
        label = "weak_case"
    else:
        label = "insufficient_evidence"

    return {
        "score": score,
        "label": label,
        "components": {
            "evidence": round(evidence_component, 2),
            "market": round(market_component, 2),
            "warning_penalty": warning_penalty,
        },
        "disclaimer": "Research score only; not financial advice and not an execution signal.",
    }
