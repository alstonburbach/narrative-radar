"""Rank narrative-level research options without implying token safety or a buy."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.agents.narrative_quality import assess_narrative_quality


OPTION_VERSION = 1
_STATUS_ORDER = {
    "research_next": 0,
    "watch_for_confirmation": 1,
    "insufficient_evidence": 2,
}
_STRONG_SOURCE_TYPES = {"primary", "primary_candidate", "onchain_data"}


def _canonical_url(value: Any) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.query,
            "",
        )
    )


def _labels(values: Any) -> set[str]:
    return {
        str(value).strip().casefold()
        for value in values or []
        if str(value).strip()
    }


def build_narrative_options(
    report: Mapping[str, Any],
    limit: int = 5,
) -> list[dict]:
    """Turn cross-source themes into conservative next-research options.

    A narrative option can never become buy-eligible here because no exact
    token contract, liquidity, holder/bundler distribution, or contract
    security report exists at the narrative stage.
    """
    evidence_by_url = {
        _canonical_url(item.get("source_url")): item
        for item in report.get("evidence") or []
        if isinstance(item, Mapping) and _canonical_url(item.get("source_url"))
    }
    searched_lenses = list(report.get("searched_lenses") or [])
    lens_reports = report.get("lenses") or {}
    counterevidence_searched = (
        (lens_reports.get("counterevidence") or {}).get("status") == "complete"
        or "counterevidence" in searched_lenses
    )
    history = report.get("discovery_history") or {}
    recurring = _labels(history.get("recurring_signals"))
    persisted = _labels(history.get("persisted_since_previous"))

    options = []
    for candidate in report.get("candidate_signals") or []:
        if not isinstance(candidate, Mapping):
            continue
        label = str(candidate.get("label") or "").strip()
        if not label:
            continue
        urls = {
            _canonical_url(value)
            for value in candidate.get("evidence_urls") or []
            if _canonical_url(value)
        }
        supporting_evidence = [
            evidence_by_url[url] for url in sorted(urls) if url in evidence_by_url
        ]
        quality = assess_narrative_quality(
            supporting_evidence,
            searched_lenses=searched_lenses,
        )
        domains = list(candidate.get("independent_domains") or [])
        positive_lenses = list(
            candidate.get("positive_lenses") or candidate.get("lenses") or []
        )
        source_types = {
            str(item.get("source_type") or "unknown")
            for item in supporting_evidence
        }
        freshness = quality.get("freshness") or {}
        recent = int(freshness.get("recent_count") or 0) > 0
        strong_source = bool(source_types & _STRONG_SOURCE_TYPES)
        counterevidence_leads = int(quality.get("counterevidence_leads") or 0)
        normalized_label = label.casefold()
        durable = normalized_label in recurring or normalized_label in persisted

        evidence_blockers = []
        confirmation_gaps = []
        if len(domains) < 2:
            evidence_blockers.append("fewer_than_two_independent_domains")
        if len(positive_lenses) < 2:
            confirmation_gaps.append("fewer_than_two_positive_research_lenses")
        if not recent:
            evidence_blockers.append("no_recent_dated_evidence")
        if not counterevidence_searched:
            evidence_blockers.append("counterevidence_search_incomplete")

        signal_score = int(float(candidate.get("signal_score") or 0))
        quality_score = int(float(quality.get("quality_score") or 0))
        if evidence_blockers:
            status = "insufficient_evidence"
        elif (
            signal_score >= 70
            and quality_score >= 40
            and len(domains) >= 3
            and len(positive_lenses) >= 2
            and strong_source
            and counterevidence_leads == 0
        ):
            status = "research_next"
        else:
            status = "watch_for_confirmation"

        cautions = []
        if not strong_source:
            cautions.append("No likely primary-source or on-chain lead is attached yet.")
        if counterevidence_leads:
            cautions.append(
                f"{counterevidence_leads} counterevidence lead(s) require manual review."
            )
        if not durable:
            cautions.append("The theme has not yet persisted across repeated scans.")
        if confirmation_gaps:
            cautions.append(
                "The theme needs confirmation from another positive research lens."
            )

        options.append(
            {
                "version": OPTION_VERSION,
                "label": label,
                "status": status,
                "signal_score": signal_score,
                "evidence_quality_score": quality_score,
                "evidence_classification": quality.get("classification"),
                "independent_domains": domains,
                "positive_lenses": positive_lenses,
                "recent_evidence_count": int(freshness.get("recent_count") or 0),
                "counterevidence_lead_count": counterevidence_leads,
                "strong_source_present": strong_source,
                "durable_across_scans": durable,
                "evidence_blockers": evidence_blockers,
                "confirmation_gaps": confirmation_gaps,
                "cautions": cautions,
                "evidence_urls": sorted(urls)[:5],
                "possible_buy_review_status": "blocked_pending_token_checks",
                "required_token_checks": [
                    "exact_public_contract_identity",
                    "live_liquidity_and_sellability",
                    "contract_security_and_admin_permissions",
                    "holder_and_lp_concentration",
                    "bundler_or_linked_wallet_concentration",
                    "fresh_counterevidence_and_decision_gate",
                ],
                "execution_enabled": False,
                "note": (
                    "This ranks a narrative for more research. It does not identify "
                    "a safe token or recommend a buy."
                ),
            }
        )

    options.sort(
        key=lambda item: (
            _STATUS_ORDER[item["status"]],
            -item["signal_score"],
            -item["evidence_quality_score"],
            item["label"],
        )
    )
    bounded = options[: max(1, min(int(limit), 10))]
    for index, option in enumerate(bounded, start=1):
        option["rank"] = index
    return bounded
