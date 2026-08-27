from typing import Any, Iterable, Mapping


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _delta(first: Mapping[str, Any], last: Mapping[str, Any], key: str) -> dict:
    first_value = _number(first.get(key))
    last_value = _number(last.get(key))
    return {
        "first": first_value,
        "latest": last_value,
        "delta": round(last_value - first_value, 4),
    }


def compare_narrative_history(history: Iterable[Mapping[str, Any]]) -> dict:
    """Describe evidence changes without treating price movement as validation."""
    items = list(history)
    if not items:
        return {
            "state": "no_history",
            "run_count": 0,
            "note": "Run the same analysis again later to measure whether evidence persists or changes.",
        }
    if len(items) == 1:
        item = items[0]
        return {
            "state": "insufficient_history",
            "run_count": 1,
            "first_run_at": item.get("started_at"),
            "last_run_at": item.get("started_at"),
            "latest_classification": item.get("classification"),
            "note": "One run cannot establish that a narrative is durable.",
        }

    first = items[0]
    last = items[-1]
    quality = _delta(first, last, "quality_score")
    domains = _delta(first, last, "independent_domain_count")
    lenses = _delta(first, last, "positive_lens_count")
    adoption = _delta(first, last, "adoption_evidence_count")
    adoption_matches = _delta(first, last, "adoption_content_matches")
    counterevidence = _delta(first, last, "counterevidence_leads")

    if (
        quality["delta"] >= 10
        and domains["delta"] >= 0
        and adoption["delta"] >= 0
        and counterevidence["delta"] <= 0
    ):
        state = "strengthening"
    elif quality["delta"] <= -10 or (
        counterevidence["delta"] > 0
        and adoption["delta"] <= 0
    ):
        state = "weakening"
    else:
        state = "mixed_or_stable"

    return {
        "state": state,
        "run_count": len(items),
        "first_run_at": first.get("started_at"),
        "last_run_at": last.get("started_at"),
        "latest_classification": last.get("classification"),
        "quality_score": quality,
        "independent_domain_count": domains,
        "positive_lens_count": lenses,
        "adoption_usage": {
            "evidence_count": adoption,
            "content_matches": adoption_matches,
        },
        "counterevidence_leads": counterevidence,
        "note": (
            "This is an evidence-persistence trend, not a return forecast. "
            "Review the underlying sources and claims before drawing conclusions."
        ),
    }
