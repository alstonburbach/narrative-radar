from typing import Any, Iterable, Mapping


def _number(value: Any):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _flag(code: str, severity: str, message: str, **details: Any) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "details": details,
    }


def run_red_team(
    market: Mapping[str, Any],
    evidence: Iterable[Any] = (),
    token_security: Mapping[str, Any] | None = None,
) -> list[dict]:
    """Return explainable risk flags for a token snapshot.

    These are screening heuristics, not fraud findings or trade signals.
    """
    flags = []
    evidence_items = list(evidence)

    if not market or not market.get("found"):
        return [_flag("no_market_pair", "high", "No active market pair was found.")]

    liquidity = _number(market.get("liquidity_usd"))
    market_cap = _number(market.get("market_cap"))
    volume = _number(market.get("volume_24h"))
    price_change = _number(market.get("price_change_24h"))
    fdv = _number(market.get("fdv"))
    buys = _number(market.get("buys_24h"))
    sells = _number(market.get("sells_24h"))

    if liquidity is None or liquidity <= 0:
        flags.append(_flag("missing_liquidity", "high", "Liquidity is missing or zero."))
    elif liquidity < 5_000:
        flags.append(_flag("very_thin_liquidity", "high", "Liquidity is extremely thin; exits may have severe slippage.", liquidity_usd=liquidity))
    elif liquidity < 25_000:
        flags.append(_flag("thin_liquidity", "medium", "Liquidity is thin relative to normal trade execution risk.", liquidity_usd=liquidity))

    if market_cap and liquidity and market_cap / liquidity > 100:
        flags.append(_flag("thin_liquidity_vs_market_cap", "high", "Market cap is very large relative to available liquidity.", market_cap_to_liquidity=round(market_cap / liquidity, 2)))
    elif market_cap and liquidity and market_cap / liquidity > 40:
        flags.append(_flag("liquidity_gap", "medium", "Market cap is high relative to available liquidity.", market_cap_to_liquidity=round(market_cap / liquidity, 2)))

    if volume and liquidity:
        volume_ratio = volume / liquidity
        if volume_ratio > 100:
            flags.append(_flag("extreme_volume_to_liquidity", "high", "Reported volume is extreme relative to liquidity and needs verification.", volume_to_liquidity=round(volume_ratio, 2)))
        elif volume_ratio > 50:
            flags.append(_flag("elevated_volume_to_liquidity", "medium", "Volume is unusually high relative to liquidity.", volume_to_liquidity=round(volume_ratio, 2)))

    if price_change is not None:
        if price_change <= -50:
            flags.append(_flag("large_drawdown", "high", "The 24-hour price change shows a large drawdown.", price_change_24h=price_change))
        elif price_change >= 150:
            flags.append(_flag("extreme_run_up", "high", "The 24-hour move is extreme and may be highly unstable.", price_change_24h=price_change))
        elif price_change >= 75:
            flags.append(_flag("extended_move", "medium", "The 24-hour move is extended and vulnerable to reversals.", price_change_24h=price_change))

    if fdv and market_cap and market_cap > 0 and fdv / market_cap > 5:
        flags.append(_flag("fdv_gap", "medium", "FDV is much higher than current market cap; dilution or supply assumptions need review.", fdv_to_market_cap=round(fdv / market_cap, 2)))

    if buys is not None and sells is not None and buys + sells >= 20 and sells > buys * 3:
        flags.append(_flag("sell_pressure", "high", "Sell transactions materially outnumber buys in the reported 24-hour window.", buys_24h=buys, sells_24h=sells))

    if not evidence_items:
        flags.append(_flag("no_independent_evidence", "medium", "No research evidence was collected for the narrative claim."))

    security = token_security or {}
    if token_security is not None and security.get("status") != "complete":
        flags.append(
            _flag(
                "token_security_unavailable",
                "critical",
                "Contract-security and distribution screening is unavailable or incomplete.",
                status=security.get("status") or "missing",
            )
        )
    elif token_security is not None:
        for item in security.get("flags") or []:
            if not isinstance(item, Mapping):
                continue
            flags.append(
                _flag(
                    str(item.get("code") or "token_security_warning"),
                    str(item.get("severity") or "medium"),
                    str(item.get("message") or "Token-security review is required."),
                    provider=security.get("provider"),
                    **dict(item.get("details") or {}),
                )
            )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(flags, key=lambda item: (order.get(item["severity"], 3), item["code"]))


def summarize_red_team(flags: Iterable[Mapping[str, Any]]) -> dict:
    items = list(flags)
    if any(item.get("severity") == "critical" for item in items):
        level = "critical"
    elif any(item.get("severity") == "high" for item in items):
        level = "high"
    elif any(item.get("severity") == "medium" for item in items):
        level = "medium"
    else:
        level = "low"
    return {
        "risk_level": level,
        "flag_count": len(items),
        "critical_count": sum(item.get("severity") == "critical" for item in items),
        "high_count": sum(item.get("severity") == "high" for item in items),
        "medium_count": sum(item.get("severity") == "medium" for item in items),
    }
