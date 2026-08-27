from collections import Counter
from math import ceil
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


def _labels(item: Mapping[str, Any]) -> set[str]:
    values = item.get("candidate_signal_labels") or []
    return {str(value) for value in values if str(value).strip()}


def compare_discovery_history(history: Iterable[Mapping[str, Any]]) -> dict:
    """Describe whether candidate narrative signals persist across scans."""
    items = list(history)
    if not items:
        return {
            "state": "no_history",
            "run_count": 0,
            "note": "The next scan will provide the first durability comparison.",
        }
    if len(items) == 1:
        item = items[0]
        return {
            "state": "insufficient_history",
            "run_count": 1,
            "first_scan_at": item.get("started_at"),
            "last_scan_at": item.get("started_at"),
            "persisted_signal_count": 0,
            "note": "One scan cannot show whether a candidate narrative persists.",
        }

    first = items[0]
    last = items[-1]
    first_labels = _labels(first)
    last_labels = _labels(last)
    signal_run_counts = Counter(
        label
        for item in items
        for label in _labels(item)
    )
    recurring_threshold = max(2, ceil(len(items) / 2))
    recurring_signals = sorted(
        label
        for label, count in signal_run_counts.items()
        if count >= recurring_threshold
    )
    persisted = sorted(first_labels & last_labels)
    new_labels = sorted(last_labels - first_labels)
    dropped_labels = sorted(first_labels - last_labels)
    quality = _delta(first, last, "quality_score")
    domains = _delta(first, last, "independent_domain_count")
    lead_count = _delta(first, last, "lead_count")

    if persisted and (
        (quality["available"] and quality["delta"] >= 10)
        or (domains["available"] and domains["delta"] > 0)
    ):
        state = "strengthening"
    elif not persisted and dropped_labels and (
        (quality["available"] and quality["delta"] <= -10)
        or (lead_count["available"] and lead_count["delta"] < 0)
    ):
        state = "weakening"
    else:
        state = "mixed_or_stable"

    return {
        "state": state,
        "run_count": len(items),
        "first_scan_at": first.get("started_at"),
        "last_scan_at": last.get("started_at"),
        "quality_score": quality,
        "independent_domain_count": domains,
        "lead_count": lead_count,
        "persisted_signal_count": len(persisted),
        "persisted_signals": persisted,
        "recurring_signal_counts": dict(sorted(signal_run_counts.items())),
        "recurring_signal_threshold": recurring_threshold,
        "recurring_signals": recurring_signals,
        "new_signals": new_labels,
        "dropped_signals": dropped_labels,
        "note": (
            "Signal persistence is a research filter, not proof of adoption, product usage, "
            "or future returns. Re-check the underlying sources and counterevidence."
        ),
    }
