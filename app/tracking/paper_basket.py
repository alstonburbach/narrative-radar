"""Paper-only evaluation for fixed-stake asymmetric baskets.

The evaluator describes observed or marked outcomes. It does not estimate the
probability of a target, predict returns, or place orders.
"""

from collections import Counter
from math import isfinite
from typing import Any, Iterable, Mapping, Optional


_OUTCOMES = {"closed", "lost", "open"}


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _optional_cost(position: Mapping[str, Any], key: str):
    raw_value = position.get(key)
    if raw_value is None:
        return None, False, None
    value = _number(raw_value)
    if value is None or value < 0:
        return None, False, f"{key} must be a non-negative number when supplied."
    return value, True, None


def _round(value: Optional[float]) -> Optional[float]:
    return round(value, 2) if value is not None else None


def evaluate_paper_basket(
    positions: Iterable[Mapping[str, Any]],
    stake_usd: float = 50.0,
    target_multiple: Optional[float] = None,
) -> dict:
    """Evaluate a fixed-stake basket from explicit paper outcomes.

    Each position must include label, entry_market_cap, and an outcome of
    closed, lost, or open. Closed positions require exit_market_cap; open
    positions require mark_market_cap. Optional fees_usd and slippage_usd are
    reported as known costs only. Missing costs are never represented as exact
    net costs.
    """
    stake = _number(stake_usd)
    if stake is None or stake <= 0:
        raise ValueError("stake_usd must be greater than zero")
    target = _number(target_multiple)
    if target is not None and target <= 0:
        raise ValueError("target_multiple must be greater than zero")

    raw_positions = list(positions)
    if not raw_positions:
        raise ValueError("at least one position is required")

    records = []
    errors = []
    family_counts = Counter()
    missing_cost_positions = []
    fee_present_count = 0
    slippage_present_count = 0

    for index, position in enumerate(raw_positions, start=1):
        label = f"position_{index}"
        record = {
            "label": label,
            "status": "invalid",
            "errors": [],
        }
        if not isinstance(position, Mapping):
            record["errors"].append("Position must be an object.")
            records.append(record)
            errors.extend(f"{label}: {error}" for error in record["errors"])
            continue

        label = str(position.get("label") or position.get("token") or label).strip()
        record["label"] = label
        family = str(position.get("narrative_family") or "unassigned").strip()
        family = family or "unassigned"
        record["narrative_family"] = family
        family_counts[family] += 1

        entry_market_cap = _number(position.get("entry_market_cap"))
        outcome = str(position.get("outcome") or "").strip().lower()
        record["outcome"] = outcome or None
        record["entry_market_cap"] = entry_market_cap

        if entry_market_cap is None or entry_market_cap <= 0:
            record["errors"].append("entry_market_cap must be greater than zero.")
        if outcome not in _OUTCOMES:
            record["errors"].append("outcome must be closed, lost, or open.")

        observed_market_cap = None
        if outcome == "closed":
            observed_market_cap = _number(position.get("exit_market_cap"))
            if observed_market_cap is None or observed_market_cap <= 0:
                record["errors"].append(
                    "closed positions require exit_market_cap greater than zero."
                )
        elif outcome == "open":
            observed_market_cap = _number(position.get("mark_market_cap"))
            if observed_market_cap is None or observed_market_cap <= 0:
                record["errors"].append(
                    "open positions require mark_market_cap greater than zero."
                )
        elif outcome == "lost":
            observed_market_cap = 0.0

        fee_usd, fee_present, fee_error = _optional_cost(position, "fees_usd")
        slippage_usd, slippage_present, slippage_error = _optional_cost(
            position, "slippage_usd"
        )
        if fee_present:
            fee_present_count += 1
        if slippage_present:
            slippage_present_count += 1
        if fee_error:
            record["errors"].append(fee_error)
        if slippage_error:
            record["errors"].append(slippage_error)
        if not fee_present or not slippage_present:
            missing_cost_positions.append(label)

        record["fees_usd"] = fee_usd
        record["slippage_usd"] = slippage_usd
        record["known_costs_usd"] = (
            (fee_usd or 0.0) + (slippage_usd or 0.0)
            if not fee_error and not slippage_error
            else None
        )
        record["costs_complete"] = (
            fee_present
            and slippage_present
            and fee_error is None
            and slippage_error is None
        )
        record["observed_market_cap"] = observed_market_cap

        if record["errors"]:
            records.append(record)
            errors.extend(f"{label}: {error}" for error in record["errors"])
            continue

        multiple = observed_market_cap / entry_market_cap
        gross_value = stake * multiple
        gross_pnl = gross_value - stake
        target_reached = target is not None and multiple >= target
        record.update(
            {
                "status": "ready",
                "multiple": round(multiple, 4),
                "gross_value_usd": _round(gross_value),
                "gross_pnl_usd": _round(gross_pnl),
                "target_reached": target_reached,
            }
        )
        records.append(record)

    position_count = len(records)
    closed_count = sum(
        record.get("outcome") in {"closed", "lost"} for record in records
    )
    open_count = sum(record.get("outcome") == "open" for record in records)
    lost_count = sum(record.get("outcome") == "lost" for record in records)
    invalid_count = sum(record.get("status") != "ready" for record in records)
    all_valid = invalid_count == 0

    aggregate = {
        "committed_usd": _round(stake * position_count),
        "gross_portfolio_value_usd": None,
        "gross_pnl_usd": None,
        "known_costs_usd": None,
        "pnl_after_known_costs_usd": None,
        "realized_gross_pnl_usd": None,
        "realized_pnl_after_known_costs_usd": None,
        "marked_gross_pnl_usd": None,
        "marked_pnl_after_known_costs_usd": None,
        "gross_return_multiple": None,
        "return_multiple_after_known_costs": None,
    }
    if all_valid:
        committed = stake * position_count
        gross_value = sum(record["gross_value_usd"] for record in records)
        known_costs = sum(record["known_costs_usd"] or 0.0 for record in records)
        realized_records = [
            record for record in records if record["outcome"] in {"closed", "lost"}
        ]
        realized_value = sum(
            record["gross_value_usd"] for record in realized_records
        )
        realized_stake = stake * len(realized_records)
        realized_costs = sum(
            record["known_costs_usd"] or 0.0 for record in realized_records
        )
        aggregate.update(
            {
                "gross_portfolio_value_usd": _round(gross_value),
                "gross_pnl_usd": _round(gross_value - committed),
                "known_costs_usd": _round(known_costs),
                "pnl_after_known_costs_usd": _round(
                    gross_value - committed - known_costs
                ),
                "realized_gross_pnl_usd": _round(realized_value - realized_stake),
                "realized_pnl_after_known_costs_usd": _round(
                    realized_value - realized_stake - realized_costs
                ),
                "marked_gross_pnl_usd": _round(gross_value - committed),
                "marked_pnl_after_known_costs_usd": _round(
                    gross_value - committed - known_costs
                ),
                "gross_return_multiple": (
                    round(gross_value / committed, 4) if committed else None
                ),
                "return_multiple_after_known_costs": (
                    round((gross_value - known_costs) / committed, 4)
                    if committed
                    else None
                ),
            }
        )

    realized_target_hits = sum(
        record.get("target_reached") is True
        and record.get("outcome") == "closed"
        for record in records
    )
    marked_target_reached = sum(
        record.get("target_reached") is True for record in records
    )
    target_metrics = {
        "target_multiple": target,
        "realized_target_hit_count": realized_target_hits if target else None,
        "marked_target_reached_count": marked_target_reached if target else None,
        "realized_target_hit_rate_pct": (
            _round(realized_target_hits / position_count * 100)
            if target and all_valid
            else None
        ),
        "realized_target_hit_rate_among_closed_pct": (
            _round(realized_target_hits / closed_count * 100)
            if target and closed_count and all_valid
            else None
        ),
    }

    family_share_pct = None
    if family_counts:
        family_share_pct = round(max(family_counts.values()) / position_count * 100, 2)

    warnings = []
    if missing_cost_positions:
        warnings.append(
            "Fees or slippage are missing for "
            f"{len(missing_cost_positions)} position(s); after-known-cost PnL "
            "is not an exact net result."
        )
    if open_count:
        warnings.append(
            f"{open_count} open position(s) are marked, not realized; their value "
            "can change materially."
        )
    if family_share_pct is not None and max(family_counts.values()) > 1:
        warnings.append(
            "Multiple positions share a narrative family; basket outcomes may be "
            "correlated rather than independent."
        )
    if family_share_pct == 100:
        warnings.append(
            "Every position is in one narrative family; this is not diversified "
            "by narrative."
        )
    if errors:
        warnings.append(
            "Basket results are incomplete until every position has valid required "
            "outcome data."
        )

    return {
        "status": "ready" if all_valid else "incomplete",
        "paper_only": True,
        "research_only": True,
        "execution_enabled": False,
        "position_count": position_count,
        "stake_usd": stake,
        "break_even_winner_multiple_before_costs": float(position_count),
        "break_even_winner_multiple_after_known_costs": (
            round(
                position_count
                + sum(record.get("known_costs_usd") or 0.0 for record in records)
                / stake,
                4,
            )
            if all_valid
            else None
        ),
        "closed_count": closed_count,
        "open_count": open_count,
        "lost_count": lost_count,
        "invalid_count": invalid_count,
        "cost_coverage": {
            "fees_present_count": fee_present_count,
            "slippage_present_count": slippage_present_count,
            "explicit_costs_present_count": sum(
                record.get("costs_complete") is True for record in records
            ),
            "fees_coverage_pct": _round(fee_present_count / position_count * 100),
            "slippage_coverage_pct": _round(
                slippage_present_count / position_count * 100
            ),
            "complete": all(
                record.get("costs_complete") is True for record in records
            )
            and all_valid,
        },
        "narrative_family_counts": dict(sorted(family_counts.items())),
        "max_narrative_family_share_pct": family_share_pct,
        "target_metrics": target_metrics,
        "aggregate": aggregate,
        "missing_cost_positions": missing_cost_positions,
        "errors": errors,
        "warnings": warnings,
        "positions": records,
        "note": (
            "This is descriptive paper analysis. It does not infer the "
            "probability of a target, predict returns, account for unknown "
            "slippage, or create, sign, or submit an order."
        ),
    }
