from typing import Any, Iterable, Mapping, Optional


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
        "delta": round(last_value - first_value, 4),
        "available": True,
    }


def compare_adoption_history(history: Iterable[Mapping[str, Any]]) -> dict:
    """Compare on-chain activity snapshots without calling them user adoption."""
    items = list(history)
    if not items:
        return {
            "state": "no_history",
            "run_count": 0,
            "note": "Collect the same token again later to measure on-chain activity change.",
        }
    if len(items) == 1:
        item = items[0]
        return {
            "state": "insufficient_history",
            "run_count": 1,
            "first_run_at": item.get("observed_at"),
            "last_run_at": item.get("observed_at"),
            "note": "One snapshot cannot establish activity growth or persistence.",
        }

    first = items[0]
    last = items[-1]
    holder_count = _delta(first, last, "holder_count")
    transfer_transactions = _delta(
        first, last, "transfer_transaction_count_24h"
    )
    transfer_events = _delta(first, last, "transfer_event_count_24h")
    active_wallets = _delta(first, last, "unique_active_wallets_24h")

    available = [
        metric
        for metric in (
            holder_count,
            transfer_transactions,
            transfer_events,
            active_wallets,
        )
        if metric["available"]
    ]
    holder_grew = holder_count["available"] and holder_count["delta"] > 0
    activity_grew = any(
        metric["available"] and metric["delta"] > 0
        for metric in (transfer_transactions, transfer_events, active_wallets)
    )
    holder_declined = holder_count["available"] and holder_count["delta"] < 0
    activity_declined = all(
        not metric["available"] or metric["delta"] <= 0
        for metric in (transfer_transactions, transfer_events, active_wallets)
    )

    if holder_grew and activity_grew:
        state = "strengthening"
    elif holder_declined and activity_declined:
        state = "weakening"
    else:
        state = "mixed_or_stable"

    return {
        "state": state if available else "insufficient_data",
        "run_count": len(items),
        "first_run_at": first.get("observed_at"),
        "last_run_at": last.get("observed_at"),
        "holder_count": holder_count,
        "transfer_transaction_count_24h": transfer_transactions,
        "transfer_event_count_24h": transfer_events,
        "unique_active_wallets_24h": active_wallets,
        "note": (
            "These are changes in indexed token-account and transfer activity, not proof of "
            "human users, product usage, or future returns. Inspect scan completeness and address mix."
        ),
    }
