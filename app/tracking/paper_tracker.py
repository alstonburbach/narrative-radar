from typing import Any, Mapping, Optional, Sequence


def _number(value: Any):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


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
            }
        )

    return {
        "status": "ready",
        "paper_only": True,
        "entry_market_cap": entry_market_cap,
        "amount_usd": amount,
        "projections": projections,
        "note": "Projections use market-cap multiples and ignore fees, slippage, taxes, and supply changes.",
    }
