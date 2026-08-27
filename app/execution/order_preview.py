from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.tracking.paper_tracker import _liquidity_context


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_order_preview(
    market: Mapping[str, Any],
    side: str,
    amount_usd: float,
    max_position_to_liquidity_pct: float = 5.0,
    as_of: Optional[datetime] = None,
    max_snapshot_age_seconds: int = 300,
    max_future_skew_seconds: int = 30,
) -> dict:
    """Build a reviewable proposal without creating or submitting an order.

    The preview intentionally omits slippage, fees, balances, and execution
    guarantees when the supplied market snapshot cannot support them.
    """
    normalized_side = str(side or "").strip().lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    amount = _number(amount_usd)
    if amount is None or amount <= 0:
        raise ValueError("amount_usd must be greater than zero")
    if max_position_to_liquidity_pct <= 0:
        raise ValueError("max_position_to_liquidity_pct must be greater than zero")
    if max_snapshot_age_seconds <= 0:
        raise ValueError("max_snapshot_age_seconds must be greater than zero")
    if max_future_skew_seconds < 0:
        raise ValueError("max_future_skew_seconds cannot be negative")

    market = market or {}
    price = _number(market.get("price_usd"))
    liquidity = _number(market.get("liquidity_usd"))
    checks = []
    as_of_value = _datetime(as_of) or datetime.now(timezone.utc)
    collected_at = _datetime(market.get("collected_at"))
    snapshot_age_seconds = (
        (as_of_value - collected_at).total_seconds()
        if collected_at is not None
        else None
    )
    snapshot_is_fresh = (
        snapshot_age_seconds is not None
        and snapshot_age_seconds <= max_snapshot_age_seconds
        and snapshot_age_seconds >= -max_future_skew_seconds
    )

    market_found = bool(market.get("found"))
    checks.append(
        {
            "name": "market_pair",
            "status": "pass" if market_found else "blocked",
            "detail": (
                "A selected market pair is available."
                if market_found
                else "No selected market pair is available."
            ),
        }
    )
    checks.append(
        {
            "name": "market_snapshot_freshness",
            "status": "pass" if snapshot_is_fresh else "blocked",
            "detail": (
                f"Market snapshot is {max(0.0, snapshot_age_seconds):.1f} seconds old; "
                f"limit is {max_snapshot_age_seconds} seconds."
                if snapshot_age_seconds is not None
                and snapshot_age_seconds >= -max_future_skew_seconds
                else (
                    "Market snapshot timestamp is too far in the future."
                    if snapshot_age_seconds is not None
                    else "A valid market collection timestamp is required."
                )
            ),
        }
    )
    checks.append(
        {
            "name": "reference_price",
            "status": "pass" if price is not None and price > 0 else "blocked",
            "detail": (
                "A positive reference price is available."
                if price is not None and price > 0
                else "A positive reference price is required."
            ),
        }
    )
    checks.append(
        {
            "name": "liquidity",
            "status": "pass" if liquidity is not None and liquidity > 0 else "blocked",
            "detail": (
                "Current pair liquidity is available."
                if liquidity is not None and liquidity > 0
                else "Current pair liquidity is required for the size screen."
            ),
        }
    )

    liquidity_context = _liquidity_context(amount, liquidity)
    ratio = liquidity_context["position_to_liquidity_pct"]
    size_passes = ratio is not None and ratio <= float(max_position_to_liquidity_pct)
    checks.append(
        {
            "name": "liquidity_size",
            "status": "pass" if size_passes else "blocked",
            "detail": (
                f"Notional is {ratio:.2f}% of current liquidity; "
                f"limit is {float(max_position_to_liquidity_pct):.2f}%."
                if ratio is not None
                else "The liquidity-size ratio cannot be calculated."
            ),
        }
    )

    estimated_token_amount = amount / price if price and price > 0 else None
    blocked_checks = [check["name"] for check in checks if check["status"] == "blocked"]
    return {
        "status": "blocked" if blocked_checks else "ready_for_manual_review",
        "research_only": True,
        "paper_only": True,
        "side": normalized_side,
        "token_name": market.get("token_name"),
        "token_symbol": market.get("token_symbol"),
        "chain": market.get("chain"),
        "contract_address": market.get("contract_address"),
        "pair_address": market.get("pair_address"),
        "dex": market.get("dex"),
        "notional_usd": amount,
        "reference_price_usd": price,
        "market_collected_at": (
            collected_at.isoformat() if collected_at is not None else None
        ),
        "preview_as_of": as_of_value.isoformat(),
        "snapshot_age_seconds": (
            round(snapshot_age_seconds, 3)
            if snapshot_age_seconds is not None
            else None
        ),
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
        "estimated_token_amount": estimated_token_amount,
        "liquidity_usd": liquidity,
        "liquidity_context": liquidity_context,
        "max_position_to_liquidity_pct": float(max_position_to_liquidity_pct),
        "checks": checks,
        "blocked_checks": blocked_checks,
        "estimated_fee_usd": None,
        "estimated_slippage_pct": None,
        "manual_approval_required": True,
        "execution_enabled": False,
        "execution_status": "not_implemented",
        "note": (
            "This is a reviewable paper proposal. It does not verify balances, "
            "gas, fees, slippage, price impact, or tax effects, and it never "
            "creates, signs, or submits a transaction."
        ),
    }
