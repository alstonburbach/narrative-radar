from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable, Mapping, Optional

from app.research_domains import source_domain_family
from app.research_independence import collapse_syndicated_evidence


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
    return source_domain_family(url)


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assess_narrative_quality(
    evidence: Iterable[Any],
    searched_lenses: Iterable[str] = (),
    as_of: Optional[datetime] = None,
    recent_days: int = 45,
    stale_days: int = 180,
) -> dict:
    """Score research quality, not token desirability or expected returns.

    Search results are still leads. A source is only verified when a separate
    primary-source workflow explicitly marks it as such.
    """
    items = list(evidence)
    scored_items, syndication = collapse_syndicated_evidence(items)
    searched = set(searched_lenses)
    raw_domains = sorted({domain for domain in (_domain(_value(item, "source_url", "")) for item in items) if domain})
    domains = sorted({domain for domain in (_domain(_value(item, "source_url", "")) for item in scored_items) if domain})
    lens_counts = Counter(
        _value(item, "research_lens")
        for item in scored_items
        if _value(item, "research_lens")
    )
    source_types = Counter(
        _value(item, "source_type") or "unknown"
        for item in scored_items
    )
    verified_primary = sum(
        1
        for item in scored_items
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
    content_matches = sum(
        1 for item in items if _value(item, "verification_status") == "content_match"
    )
    fetch_failures = sum(
        1 for item in items if _value(item, "verification_status") == "fetch_failed"
    )
    as_of_value = _datetime(as_of) or datetime.now(timezone.utc)
    published_dates = [
        published
        for item in scored_items
        if (published := _datetime(_value(item, "published_at"))) is not None
    ]
    future_cutoff = as_of_value + timedelta(days=1)
    historical_dates = [published for published in published_dates if published <= future_cutoff]
    future_dated_count = len(published_dates) - len(historical_dates)
    ages_days = [
        max(0, int((as_of_value - published).total_seconds() // 86_400))
        for published in historical_dates
    ]
    recent_count = sum(age <= max(1, int(recent_days)) for age in ages_days)
    stale_count = sum(age > max(1, int(stale_days)) for age in ages_days)
    if not scored_items:
        freshness_status = "no_evidence"
    elif not published_dates:
        freshness_status = "unknown"
    elif not historical_dates:
        freshness_status = "future_dated_only"
    elif recent_count:
        freshness_status = "recent_evidence_present"
    elif stale_count == len(historical_dates):
        freshness_status = "stale_only"
    else:
        freshness_status = "dated_but_not_recent"
    freshness = {
        "status": freshness_status,
        "as_of": as_of_value.isoformat(),
        "recent_window_days": max(1, int(recent_days)),
        "stale_after_days": max(1, int(stale_days)),
        "dated_count": len(published_dates),
        "undated_count": len(scored_items) - len(published_dates),
        "recent_count": recent_count,
        "stale_count": stale_count,
        "future_dated_count": future_dated_count,
        "newest_published_at": (
            max(historical_dates).isoformat() if historical_dates else None
        ),
        "oldest_published_at": (
            min(historical_dates).isoformat() if historical_dates else None
        ),
    }

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
    elif content_matches and (primary_candidates or onchain_sources):
        source_score = 18
    elif primary_candidates or onchain_sources:
        source_score = 15
    elif secondary_sources:
        source_score = 10
    elif scored_items:
        source_score = 4
    else:
        source_score = 0

    confidence_values = [
        max(0.0, min(1.0, _number(_value(item, "confidence")) or 0.0))
        for item in scored_items
    ]
    identity_score = round((sum(confidence_values) / len(confidence_values)) * 15) if scored_items else 0

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
    if not scored_items:
        warnings.append("No research leads were collected.")
    if len(domains) < 2:
        warnings.append("Independent corroboration is not established yet.")
    if not (primary_candidates or onchain_sources or verified_primary):
        warnings.append("No likely primary-source or on-chain lead was found.")
    if social_sources and social_sources >= max(1, len(scored_items) / 2):
        warnings.append("Evidence is dominated by social or aggregator leads.")
    if counterevidence_leads:
        warnings.append("Counterevidence search returned leads that require manual review.")
    if "counterevidence" not in searched:
        warnings.append("Counterevidence has not been searched yet.")
    if fetch_failures:
        warnings.append("Some high-value source leads could not be fetched for content checking.")
    if scored_items and not published_dates:
        warnings.append("No lead supplied a publication date; evidence freshness is unknown.")
    elif scored_items and historical_dates and not recent_count:
        warnings.append(
            f"No dated evidence was published within the last {max(1, int(recent_days))} days."
        )
    if historical_dates and stale_count >= max(1, len(historical_dates) / 2):
        warnings.append(
            f"At least half of dated evidence is older than {max(1, int(stale_days))} days."
        )
    if future_dated_count:
        warnings.append("Some evidence has a future publication date and requires review.")
    if syndication["collapsed_source_count"]:
        warnings.append(
            f'{syndication["collapsed_source_count"]} copied or syndicated source lead(s) '
            "were excluded from independent corroboration."
        )

    return {
        "quality_score": quality_score,
        "classification": classification,
        "independent_domains": domains,
        "independent_domain_count": len(domains),
        "raw_independent_domains": raw_domains,
        "raw_independent_domain_count": len(raw_domains),
        "syndication": syndication,
        "lenses_covered": sorted(lens_counts),
        "positive_lenses_covered": positive_lenses,
        "source_breakdown": dict(source_types),
        "verified_primary_sources": verified_primary,
        "content_matches": content_matches,
        "fetch_failures": fetch_failures,
        "counterevidence_leads": counterevidence_leads,
        "freshness": freshness,
        "searched_lenses": sorted(searched),
        "warnings": warnings,
        "classification_only": True,
        "note": (
            "This measures evidence quality and corroboration. It does not prove a narrative, "
            "predict returns, or authorize a trade."
        ),
    }