import json
from typing import Any, Iterable, Mapping, Optional


CONTAMINATION_FLAGS = {
    "incomplete_cost_basis_or_inbound_tokens",
    "external_inflows_are_large_relative_to_realized_pnl",
    "external_inflows_concentrated_in_one_source",
    "external_flows_require_quote_conversion",
    "mixed_quote_assets_require_conversion",
    "unpriced_or_unrecognized_swaps",
    "unpriced_or_unrecognized_transfers",
    "profit_concentrated_in_few_trades",
    "profit_concentrated_in_few_periods",
    "short_observation_window",
    "large_realized_drawdown",
}


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(
    first: Mapping[str, Any],
    last: Mapping[str, Any],
    key: str,
) -> dict:
    first_value = _number(first.get(key))
    last_value = _number(last.get(key))
    if first_value is None or last_value is None:
        return {
            "first": first_value,
            "latest": last_value,
            "delta": None,
            "available": False,
        }
    return {
        "first": first_value,
        "latest": last_value,
        "delta": round(last_value - first_value, 8),
        "available": True,
    }


def _flags(item: Mapping[str, Any]) -> set[str]:
    values = item.get("flags") or []
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except (TypeError, json.JSONDecodeError):
            values = [values]
    return {str(value) for value in values}


def _positive_realized_candidate(item: Mapping[str, Any]) -> bool:
    pnl = _number(item.get("primary_realized_pnl"))
    return bool(item.get("research_candidate")) and pnl is not None and pnl > 0


def _accounting_fingerprint(item: Mapping[str, Any]) -> tuple:
    """Return fields that change when the observed trading history changes."""
    profile = item.get("strategy_profile") or {}
    return (
        item.get("primary_realized_pnl"),
        item.get("closed_trades"),
        item.get("wins"),
        item.get("losses"),
        item.get("external_inflow_usd"),
        item.get("external_outflow_usd"),
        profile.get("observed_span_days"),
        profile.get("profitable_months"),
        profile.get("realized_roi_on_matched_cost_basis_pct"),
        profile.get("max_realized_drawdown_on_matched_cost_basis_pct"),
    )


def compare_wallet_history(history: Iterable[Mapping[str, Any]]) -> dict:
    """Measure repeated realized-PnL evidence without authorizing copy trades."""
    items = list(history)
    if not items:
        return {
            "state": "no_history",
            "strategy_classification": "not_yet_repeatable",
            "run_count": 0,
            "note": "Run the same wallet again later; one report cannot establish a repeatable strategy.",
        }
    if len(items) == 1:
        item = items[0]
        return {
            "state": "insufficient_history",
            "strategy_classification": "not_yet_repeatable",
            "run_count": 1,
            "first_run_at": item.get("analyzed_at"),
            "last_run_at": item.get("analyzed_at"),
            "positive_realized_candidate_runs": int(_positive_realized_candidate(item)),
            "note": "A single realized-PnL snapshot is not enough to call a strategy repeatable.",
        }

    first = items[0]
    last = items[-1]
    candidate_runs = sum(_positive_realized_candidate(item) for item in items)
    contaminated_runs = sum(bool(_flags(item) & CONTAMINATION_FLAGS) for item in items)
    recent_items = items[-3:]
    recent_candidate_runs = sum(
        _positive_realized_candidate(item) for item in recent_items
    )
    distinct_accounting_snapshots = len(
        {_accounting_fingerprint(item) for item in items}
    )
    history_progressed = distinct_accounting_snapshots > 1
    same_quote_asset = (
        first.get("primary_quote_asset")
        and first.get("primary_quote_asset") == last.get("primary_quote_asset")
    )
    pnl = (
        _delta(first, last, "primary_realized_pnl")
        if same_quote_asset
        else {"available": False, "first": None, "latest": None, "delta": None}
    )
    quality = _delta(first, last, "quality_score")
    closed_trades = _delta(first, last, "closed_trades")
    external_inflow = _delta(first, last, "external_inflow_usd")

    if (
        len(items) >= 3
        and recent_candidate_runs == 3
        and contaminated_runs == 0
        and history_progressed
    ):
        classification = "repeatable_realized_candidate"
    elif (
        len(items) >= 3
        and recent_candidate_runs == 3
        and contaminated_runs == 0
        and not history_progressed
    ):
        classification = "same_snapshot_repeated"
    elif len(items) >= 3 and recent_candidate_runs < 3:
        classification = "recent_performance_mixed"
    elif contaminated_runs:
        classification = "contaminated_or_incomplete"
    elif candidate_runs >= 2:
        classification = "promising_but_short_history"
    else:
        classification = "not_yet_repeatable"

    if classification == "repeatable_realized_candidate":
        state = "strengthening"
    elif quality["available"] and quality["delta"] <= -15:
        state = "weakening"
    elif any(not _positive_realized_candidate(item) for item in items[-2:]):
        state = "mixed_or_unstable"
    else:
        state = "mixed_or_stable"

    return {
        "state": state,
        "strategy_classification": classification,
        "run_count": len(items),
        "first_run_at": first.get("analyzed_at"),
        "last_run_at": last.get("analyzed_at"),
        "positive_realized_candidate_runs": candidate_runs,
        "recent_positive_realized_candidate_runs": recent_candidate_runs,
        "contaminated_or_incomplete_runs": contaminated_runs,
        "distinct_accounting_snapshots": distinct_accounting_snapshots,
        "history_progressed": history_progressed,
        "same_primary_quote_asset": bool(same_quote_asset),
        "primary_realized_pnl": pnl,
        "quality_score": quality,
        "closed_trades": closed_trades,
        "external_inflow_usd": external_inflow,
        "latest_strategy_profile": last.get("strategy_profile") or {},
        "note": (
            "This is historical accounting evidence only. It requires matched cost basis, "
            "low deposit contamination, and repeated runs; it never makes a wallet copy-trade ready."
        ),
    }
