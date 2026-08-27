from collections import Counter
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse


POSITIVE_LENSES = {
    "official_builders",
    "adoption_usage",
    "funding_backers",
    "onchain_tokenomics",
}


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _domain(url: str) -> str:
    return (urlparse(str(url)).hostname or "").lower().removeprefix("www.")


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_narrative_quality(
    evidence: Iterable[Any],
    searched_lenses: Iterable[str] = (),
) -> dict:
    """Score research quality, not token desirability or expected returns.

    Search results are still leads. A source is only verified when a separate
    primary-source workflow explicitly marks it as such.
    """
    items = list(evidence)
    searched = set(searched_lenses)
    domains = sorted({domain for domain in (_domain(_value(item, "source_url", "")) for item in items) if domain})
    lens_counts = Counter(
        _value(item, "research_lens")
        for item in items
        if _value(item, "research_lens")
    )
    source_types = Counter(
        _value(item, "source_type") or "unknown"
        for item in items
    )
    verified_primary = sum(
        1
        for item in items
        if _value(item, "source_type") == "primary"
        and _value(item, "verification_status") == "verified"
        and (_number(_value(item, "confidence")) or 0) >= 0.75
    )
    primary_candidates = source_types.get("primary_candidate", 0)
    onchain_sources = source_types.get("onchain_data", 0)
    secondary_sources = source_types.get("secondary_lead", 0)
    social_sources = source_types.get("social_lead", 0)
    positive_lenses = sorted(set(lens_counts) & POSITIVE_LENSES)
    counterevidence_leads = lens_counts.get("counterevidence", 0)

    if len(positive_lenses) >= 4:
        breadth_score = 20
    else:
        breadth_score = len(positive_lenses) * 5

    independence_score = {
        0: 0,
        1: 5,
        2: 12,
        3: 18,
    }.get(len(domains), 22)

    if verified_primary:
        source_score = 25
    elif primary_candidates or onchain_sources:
        source_score = 15
    elif secondary_sources:
        source_score = 10
    elif items:
        source_score = 4
    else:
        source_score = 0

    confidence_values = [
        max(0.0, min(1.0, _number(_value(item, "confidence")) or 0.0))
        for item in items
    ]
    identity_score = round((sum(confidence_values) / len(confidence_values)) * 15) if items else 0

    process_score = 5 if "counterevidence" in searched else 0
    quality_score = min(
        100,
        breadth_score + independence_score + source_score + identity_score + process_score,
    )

    if verified_primary and len(domains) >= 2:
        classification = "verified_and_corroborated"
    elif quality_score >= 60 and len(domains) >= 3 and len(positive_lenses) >= 3:
        classification = "corroborated_leads"
    elif quality_score >= 40:
        classification = "promising_leads"
    else:
        classification = "insufficient_evidence"

    warnings = []
    if not items:
        warnings.append("No research leads were collected.")
    if len(domains) < 2:
        warnings.append("Independent corroboration is not established yet.")
    if not (primary_candidates or onchain_sources or verified_primary):
        warnings.append("No likely primary-source or on-chain lead was found.")
    if social_sources and social_sources >= max(1, len(items) / 2):
        warnings.append("Evidence is dominated by social or aggregator leads.")
    if counterevidence_leads:
        warnings.append("Counterevidence search returned leads that require manual review.")
    if "counterevidence" not in searched:
        warnings.append("Counterevidence has not been searched yet.")

    return {
        "quality_score": quality_score,
        "classification": classification,
        "independent_domains": domains,
        "independent_domain_count": len(domains),
        "lenses_covered": sorted(lens_counts),
        "positive_lenses_covered": positive_lenses,
        "source_breakdown": dict(source_types),
        "verified_primary_sources": verified_primary,
        "counterevidence_leads": counterevidence_leads,
        "searched_lenses": sorted(searched),
        "warnings": warnings,
        "classification_only": True,
        "note": (
            "This measures evidence quality and corroboration. It does not prove a narrative, "
            "predict returns, or authorize a trade."
        ),
    }
