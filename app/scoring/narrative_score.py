from typing import Any, Iterable, Mapping, Optional

from app.agents.red_team import run_red_team, summarize_red_team


def _number(value: Any):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0, high: float = 100) -> int:
    return int(max(low, min(high, round(value))))


def _liquidity_score(liquidity: Optional[float]) -> int:
    if liquidity is None or liquidity <= 0:
        return 0
    if liquidity >= 1_000_000:
        return 25
    if liquidity >= 250_000:
        return 20
    if liquidity >= 50_000:
        return 15
    if liquidity >= 10_000:
        return 8
    return 3


def _activity_score(volume: Optional[float], liquidity: Optional[float]) -> int:
    if not volume or not liquidity or volume <= 0 or liquidity <= 0:
        return 0
    ratio = volume / liquidity
    if 0.5 <= ratio <= 10:
        return 20
    if 0.1 <= ratio < 0.5:
        return 12
    if 10 < ratio <= 30:
        return 10
    return 4


def _momentum_score(change: Optional[float]) -> int:
    if change is None:
        return 0
    if 10 <= change <= 50:
        return 15
    if 0 < change < 10:
        return 10
    if -10 <= change <= 0:
        return 7
    if -25 < change < -10:
        return 4
    return 2


def _evidence_score(evidence: Iterable[Any]) -> int:
    total = 0.0
    for item in evidence:
        confidence = _number(getattr(item, "confidence", None))
        if confidence is None and isinstance(item, Mapping):
            confidence = _number(item.get("confidence"))
        source_type = getattr(item, "source_type", None)
        if source_type is None and isinstance(item, Mapping):
            source_type = item.get("source_type")
        if confidence is not None:
            weight = 1.25 if source_type == "primary" else 1.0
            total += max(0, min(1, confidence)) * weight * 10
    return min(25, int(round(total)))


def _narrative_quality_component(quality: Mapping[str, Any]) -> int:
    value = _number(quality.get("quality_score"))
    if value is None:
        return 0
    return int(round(max(0, min(100, value)) * 0.25))


def _apply_narrative_gate(score: int, quality: Optional[Mapping[str, Any]]) -> int:
    """Prevent strong market data from masking weak narrative evidence."""
    if quality is None:
        return score
    classification = quality.get("classification")
    caps = {
        "insufficient_evidence": 29,
        "promising_leads": 49,
        "corroborated_leads": 69,
    }
    return min(score, caps.get(classification, 100))


def score_radar(
    market: Mapping[str, Any],
    evidence: Iterable[Any] = (),
    red_flags: Optional[Iterable[Mapping[str, Any]]] = None,
    narrative_quality: Optional[Mapping[str, Any]] = None,
) -> dict:
    evidence_items = list(evidence)
    flags = list(red_flags) if red_flags is not None else run_red_team(market, evidence_items)

    liquidity = _number(market.get("liquidity_usd")) if market else None
    volume = _number(market.get("volume_24h")) if market else None
    price_change = _number(market.get("price_change_24h")) if market else None

    structure = 0
    if market and market.get("found"):
        structure += 5
    if market and market.get("market_cap"):
        structure += 4
    if market and market.get("pair_address"):
        structure += 3
    if market and market.get("price_usd"):
        structure += 3

    evidence_component = (
        _narrative_quality_component(narrative_quality)
        if narrative_quality is not None
        else _evidence_score(evidence_items)
    )
    components = {
        "liquidity": _liquidity_score(liquidity),
        "market_activity": _activity_score(volume, liquidity),
        "momentum": _momentum_score(price_change),
        "evidence": evidence_component,
        "market_structure": structure,
    }

    penalty = sum(
        {"high": 15, "medium": 7, "low": 2}.get(flag.get("severity"), 0)
        for flag in flags
    )
    penalty = min(45, penalty)
    raw_score = _clamp(sum(components.values()) - penalty)
    score = _apply_narrative_gate(raw_score, narrative_quality)

    if score >= 70 and (
        narrative_quality is None
        or narrative_quality.get("classification") == "verified_and_corroborated"
    ):
        rating = "strong_watch"
    elif score >= 50:
        rating = "watch"
    elif score >= 30:
        rating = "research_only"
    else:
        rating = "high_risk"

    return {
        "radar_score": score,
        "raw_market_score": raw_score,
        "narrative_gate_applied": narrative_quality is not None,
        "rating": rating,
        "components": components,
        "risk_penalty": penalty,
        "red_team": summarize_red_team(flags),
        "narrative_quality": narrative_quality or {},
        "classification_only": True,
        "note": "This score ranks research quality and market conditions; it does not predict returns or authorize a trade.",
    }


def calculate_narrative_score(
    market: Mapping[str, Any],
    evidence: Iterable[Any] = (),
    red_flags: Optional[Iterable[Mapping[str, Any]]] = None,
    narrative_quality: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Compatibility alias for callers using the original planned name."""
    return score_radar(market, evidence, red_flags, narrative_quality)
