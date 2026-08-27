from typing import Any, Mapping, Optional, Sequence


def _number(value: Any):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _liquidity_context(position_usd: float, liquidity_usd: Optional[float]) -> dict:
    if liquidity_usd is None or liquidity_usd <= 0:
        return {
            "position_to_liquidity_pct": None,
            "liquidity_risk": "unavailable",
        }
    ratio = position_usd / liquidity_usd * 100
    if ratio <= 1:
        risk = "low"
    elif ratio <= 5:
        risk = "moderate"
    elif ratio <= 10:
        risk = "high"
    elif ratio <= 25:
        risk = "very_high"
    else:
        risk = "extreme"
    return {
        "position_to_liquidity_pct": round(ratio, 2),
        "liquidity_risk": risk,
    }


def project_paper_position(
    market: Mapping[str, Any],
    amount_usd: float,
    target_market_caps: Optional[Sequence[float]] = None,
) -> dict:
    """Project hypothetical position values without placing an order."""
    amount = _number(amount_usd)
    entry_market_cap = _number(market.get("market_cap")) if market else None
    if amount is None or amount <= 0:
        raise ValueError("amount_usd must be greater than zero")
    if entry_market_cap is None or entry_market_cap <= 0:
        return {
            "status": "unavailable",
            "reason": "A positive market cap is required for a projection.",
        }

    liquidity_usd = _number(market.get("liquidity_usd")) if market else None
    entry_liquidity = _liquidity_context(amount, liquidity_usd)

    if target_market_caps is None:
        target_market_caps = [
            entry_market_cap * multiple for multiple in (2, 3, 5, 10)
        ]

    targets = sorted({float(target) for target in target_market_caps if float(target) > 0})
    projections = []
    for target in targets:
        multiple = target / entry_market_cap
        value = amount * multiple
        projections.append(
            {
                "target_market_cap": target,
                "multiple": round(multiple, 4),
                "estimated_value_usd": round(value, 2),
                "estimated_pnl_usd": round(value - amount, 2),
                "roi_pct": round((multiple - 1) * 100, 2),
                "target_to_current_liquidity": _liquidity_context(value, liquidity_usd),
            }
        )

    return {
        "status": "ready",
        "paper_only": True,
        "entry_market_cap": entry_market_cap,
        "amount_usd": amount,
        "entry_liquidity_usd": liquidity_usd,
        "entry_liquidity_context": entry_liquidity,
        "projections": projections,
        "note": "Projections use market-cap multiples. Liquidity fields are a current-liquidity size screen, not an exact slippage estimate; fees, taxes, and supply changes are excluded.",
    }