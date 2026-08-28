"""Paper-only evaluation for fixed-stake asymmetric baskets.

The evaluator describes observed or marked outcomes. It does not estimate the
probability of a target, predict returns, or place orders.
"""

from collections import Counter
from datetime import datetime, timezone
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


def _utc_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_paper_basket(
    positions: Iterable[Mapping[str, Any]],
    stake_usd: float = 50.0,
    target_multiple: Optional[float] = None,
    evaluated_at: Optional[Any] = None,
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
    evaluation_time = (
        _utc_timestamp(evaluated_at)
        if evaluated_at is not None
        else datetime.now(timezone.utc)
    )
    if evaluation_time is None:
        raise ValueError("evaluated_at must be a timezone-aware ISO 8601 timestamp")

    raw_positions = list(positions)
    if not raw_positions:
        raise ValueError("at least one position is required")

    records = []
    errors = []
    family_counts = Counter()
    missing_cost_positions = []
    fee_present_count = 0
    slippage_present_count = 0
    timing_status_counts = Counter()
    timing_issues = []

    for index, position in enumerate(raw_positions, start=1):
        label = f"position_{index}"
        record = {
            "label": label,
            "status": "invalid",
            "errors": [],
        }
        if not isinstance(position, Mapping):
            record["errors"].append("Position must be an object.")
            record["temporal_integrity"] = {
                "status": "invalid",
                "missing_fields": [],
                "errors": ["Position must be an object."],
            }
            timing_status_counts["invalid"] += 1
            timing_issues.append(f"{label}: Position must be an object.")
            records.append(record)
            errors.extend(f"{label}: {error}" for error in record["errors"])
            continue

        label = str(position.get("label") or position.get("token") or label).strip()
        record["label"] = label
        family = str(position.get("narrative_family") or "unassigned").strip()
        family = family or "unassigned"
        record["narrative_family"] = family
        family_counts[family] += 1

        timing_fields = (
            "signal_detected_at",
            "entry_recorded_at",
            "outcome_observed_at",
        )
        timing_values = {}
        timing_missing = []
        timing_errors = []
        for key in timing_fields:
            raw_timestamp = position.get(key)
            parsed_timestamp = _utc_timestamp(raw_timestamp)
            if raw_timestamp is None or not str(raw_timestamp).strip():
                timing_missing.append(key)
            elif parsed_timestamp is None:
                timing_errors.append(
                    f"{key} must be a timezone-aware ISO 8601 timestamp."
                )
            timing_values[key] = parsed_timestamp

        if not timing_missing and not timing_errors:
            signal_time = timing_values["signal_detected_at"]
            entry_time = timing_values["entry_recorded_at"]
            outcome_time = timing_values["outcome_observed_at"]
            if signal_time > entry_time:
                timing_errors.append(
                    "signal_detected_at must not be after entry_recorded_at."
                )
            if outcome_time < entry_time:
                timing_errors.append(
                    "outcome_observed_at must not be before entry_recorded_at."
                )
            if any(value > evaluation_time for value in timing_values.values()):
                timing_errors.append(
                    "Paper timestamps must not be after evaluated_at."
                )

        if timing_errors:
            timing_status = "invalid"
        elif timing_missing:
            timing_status = "missing"
        else:
            timing_status = "verified"
        timing_status_counts[timing_status] += 1
        timing_issues.extend(f"{label}: {error}" for error in timing_errors)
        record["temporal_integrity"] = {
            "status": timing_status,
            "signal_detected_at": (
                timing_values["signal_detected_at"].isoformat()
                if timing_values["signal_detected_at"] is not None
                else None
            ),
            "entry_recorded_at": (
                timing_values["entry_recorded_at"].isoformat()
                if timing_values["entry_recorded_at"] is not None
                else None
            ),
            "outcome_observed_at": (
                timing_values["outcome_observed_at"].isoformat()
                if timing_values["outcome_observed_at"] is not None
                else None
            ),
            "signal_to_entry_minutes": (
                round(
                    (
                        timing_values["entry_recorded_at"]
                        - timing_values["signal_detected_at"]
                    ).total_seconds()
                    / 60,
                    2,
                )
                if timing_status == "verified"
                else None
            ),
            "observed_holding_hours": (
                round(
                    (
                        timing_values["outcome_observed_at"]
                        - timing_values["entry_recorded_at"]
                    ).total_seconds()
                    / 3600,
                    2,
                )
                if timing_status == "verified"
                else None
            ),
            "missing_fields": timing_missing,
            "errors": timing_errors,
        }

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


    realized_records_for_distribution = [
        record
        for record in records
        if record.get("outcome") in {"closed", "lost"}
    ]
    winning_pnls = [
        record["gross_pnl_usd"]
        for record in realized_records_for_distribution
        if record.get("gross_pnl_usd", 0) > 0
    ]
    losing_count = sum(
        record.get("gross_pnl_usd", 0) < 0
        for record in realized_records_for_distribution
    )
    flat_count = sum(
        record.get("gross_pnl_usd", 0) == 0
        for record in realized_records_for_distribution
    )
    winning_pnl_total = sum(winning_pnls)
    largest_winner_pnl = max(winning_pnls, default=0.0)
    outcome_distribution = {
        "realized_winner_count": len(winning_pnls) if all_valid else None,
        "realized_loser_count": losing_count if all_valid else None,
        "realized_flat_count": flat_count if all_valid else None,
        "gross_winning_pnl_usd": (
            _round(winning_pnl_total) if all_valid else None
        ),
        "largest_winner_gross_pnl_usd": (
            _round(largest_winner_pnl) if all_valid and winning_pnls else None
        ),
        "largest_winner_share_of_gross_winning_pnl_pct": (
            _round(largest_winner_pnl / winning_pnl_total * 100)
            if all_valid and winning_pnl_total > 0
            else None
        ),
    }

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

    verified_timing_count = timing_status_counts["verified"]
    temporal_integrity = {
        "evaluated_at": evaluation_time.isoformat(),
        "verified_count": verified_timing_count,
        "missing_count": timing_status_counts["missing"],
        "invalid_count": timing_status_counts["invalid"],
        "coverage_pct": _round(verified_timing_count / position_count * 100),
        "timing_eligible_for_strategy_validation": (
            all_valid and verified_timing_count == position_count
        ),
        "issues": timing_issues,
        "note": (
            "Forward-test eligibility requires a recorded signal time, entry snapshot "
            "time, and later outcome observation for every position. Valid timing "
            "alone does not establish profitability or repeatability."
        ),
    }

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
    if temporal_integrity["missing_count"]:
        warnings.append(
            "One or more positions lack signal, entry, or outcome timestamps; PnL "
            "remains descriptive and is not eligible as a forward-tested result."
        )
    if temporal_integrity["invalid_count"]:
        warnings.append(
            "One or more position timelines are invalid or future-dated; they are "
            "excluded from forward-test validation."
        )
    largest_winner_share = outcome_distribution[
        "largest_winner_share_of_gross_winning_pnl_pct"
    ]
    if largest_winner_share is not None and largest_winner_share > 75:
        warnings.append(
            "The largest realized winner supplies more than 75% of gross winning "
            "PnL; treat the basket result as winner-concentrated, not yet repeatable."
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
        "temporal_integrity": temporal_integrity,
        "target_metrics": target_metrics,
        "outcome_distribution": outcome_distribution,
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
