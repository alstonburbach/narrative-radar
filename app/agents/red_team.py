from typing import Any, Dict, Iterable, List, Optional

from app.collectors.market import normalize_chain
from app.database.models import Evidence


def _number(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def build_red_team_report(
    market: Dict[str, Any],
    evidence: Iterable[Evidence],
    requested_chain: Optional[str] = None,
) -> Dict[str, Any]:
    """Look for reasons a narrative score should not be treated as a trade signal."""

    evidence = list(evidence)
    warnings: List[Dict[str, str]] = []

    def add(code: str, severity: str, message: str) -> None:
        warnings.append({"code": code, "severity": severity, "message": message})

    if not market.get("found"):
        add(
            "market_data_unavailable",
            "high",
            "No matching DEX pair was found, so price and liquidity cannot be evaluated.",
        )
    else:
        liquidity = _number(market.get("liquidity_usd"))
        volume_24h = _number(market.get("volume_24h"))
        change_24h = _number(market.get("price_change_24h"))
        market_cap = _number(market.get("market_cap"))
        fdv = _number(market.get("fdv"))

        if liquidity is None:
            add("liquidity_missing", "medium", "Liquidity was not reported by the market source.")
        elif liquidity < 10_000:
            add("very_thin_liquidity", "high", "Reported liquidity is below $10,000.")
        elif liquidity < 50_000:
            add("thin_liquidity", "medium", "Reported liquidity is below $50,000.")

        if liquidity and volume_24h is not None and volume_24h > liquidity * 10:
            add(
                "turnover_anomaly",
                "medium",
                "24-hour volume is more than 10x reported liquidity; verify wash-trading and volatility risk.",
            )

        if change_24h is not None and change_24h <= -25:
            add("sharp_24h_drawdown", "high", "The token is down at least 25% over 24 hours.")
        elif change_24h is not None and change_24h < 0:
            add("negative_24h_momentum", "medium", "The token has negative 24-hour price momentum.")

        if market_cap and fdv and fdv > market_cap * 2:
            add(
                "fdv_overhang",
                "medium",
                "FDV is more than twice current market cap; future supply may create dilution pressure.",
            )

        if requested_chain and market.get("chain"):
            if normalize_chain(requested_chain) != normalize_chain(market.get("chain")):
                add(
                    "chain_mismatch",
                    "high",
                    "The selected pair is on a different chain than the requested chain.",
                )

    if not evidence:
        add("no_narrative_evidence", "medium", "No public narrative evidence was collected.")
    elif not any(item.source_type.lower() == "primary" for item in evidence):
        add(
            "no_primary_source",
            "medium",
            "Collected sources do not include a verified primary source.",
        )

    high_count = sum(item["severity"] == "high" for item in warnings)
    medium_count = sum(item["severity"] == "medium" for item in warnings)
    risk_level = "high" if high_count else "medium" if medium_count else "low"

    return {
        "risk_level": risk_level,
        "warning_count": len(warnings),
        "warnings": warnings,
        "trade_execution_allowed": False,
    }
