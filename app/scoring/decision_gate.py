"""Transparent readiness checks for research and manual review.

This module makes the boundary between research quality and execution explicit.
It never authorizes, creates, signs, or submits an order.
"""

from datetime import datetime, timezone
from typing import Any, Mapping, Optional


_RISK_LEVELS = {"low": 0, "medium": 1, "high": 2, "critical": 3}

def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _requirement(
    name: str,
    passed: bool,
    detail: str,
    *,
    blocking: bool = False,
    status: Optional[str] = None,
) -> dict:
    if status is None:
        status = "pass" if passed else ("blocked" if blocking else "review")
    return {
        "name": name,
        "status": status,
        "passed": bool(passed),
        "blocking": bool(blocking),
        "detail": detail,
    }


def evaluate_manual_review_gate(
    market: Optional[Mapping[str, Any]],
    score: Optional[Mapping[str, Any]],
    narrative_quality: Optional[Mapping[str, Any]],
    red_team: Optional[Mapping[str, Any]],
    order_preview: Optional[Mapping[str, Any]] = None,
    *,
    min_radar_score: float = 50.0,
    max_risk_level: str = "medium",
    require_recent_evidence: bool = True,
    as_of: Optional[datetime] = None,
    max_snapshot_age_seconds: int = 300,
    max_future_skew_seconds: int = 30,
) -> dict:
    """Evaluate transparent research requirements for a human review.

    A passing result means the report is ready for a person to review. It is
    not a trade signal, order authorization, or execution eligibility result.
    """
    if min_radar_score < 0:
        raise ValueError("min_radar_score cannot be negative")
    if max_snapshot_age_seconds <= 0:
        raise ValueError("max_snapshot_age_seconds must be greater than zero")
    if max_future_skew_seconds < 0:
        raise ValueError("max_future_skew_seconds cannot be negative")

    normalized_max_risk = str(max_risk_level or "").strip().lower()
    if normalized_max_risk not in _RISK_LEVELS:
        raise ValueError("max_risk_level must be low, medium, high, or critical")

    market = market or {}
    score = score or {}
    narrative_quality = narrative_quality or {}
    red_team = red_team or {}
    requirements = []

    market_found = bool(market.get("found"))
    requirements.append(
        _requirement(
            "market_pair",
            market_found,
            (
                "A selected market pair is available."
                if market_found
                else "A selected market pair is required."
            ),
            blocking=True,
        )
    )

    score_value = _number(score.get("radar_score"))
    score_passes = score_value is not None and score_value >= min_radar_score
    requirements.append(
        _requirement(
            "radar_score",
            score_passes,
            (
                f"Radar score is {score_value:.1f}; minimum is {min_radar_score:.1f}."
                if score_value is not None
                else "A numeric radar score is required."
            ),
        )
    )

    classification = str(narrative_quality.get("classification") or "").strip()
    quality_score = _number(narrative_quality.get("quality_score"))
    domain_count = _number(narrative_quality.get("independent_domain_count"))
    positive_lens_count = len(narrative_quality.get("positive_lenses_covered") or [])
    corroborated_passes = (
        classification == "corroborated_leads"
        and quality_score is not None
        and quality_score >= 60
        and domain_count is not None
        and domain_count >= 3
        and positive_lens_count >= 3
    )
    verified_passes = (
        classification == "verified_and_corroborated"
        and quality_score is not None
        and quality_score >= 50
        and domain_count is not None
        and domain_count >= 2
    )
    evidence_passes = corroborated_passes or verified_passes
    requirements.append(
        _requirement(
            "narrative_evidence",
            evidence_passes,
            (
                f"Evidence is {classification} with quality {quality_score:.1f}/100 "
                f"across {domain_count:.0f} independent domain(s)."
                if quality_score is not None and domain_count is not None
                else "A corroborated evidence classification and quality metrics are required."
            ),
        )
    )

    freshness = narrative_quality.get("freshness") or {}
    freshness_status = str(freshness.get("status") or "unknown")
    future_dated_count = _number(freshness.get("future_dated_count")) or 0
    if future_dated_count > 0:
        requirements.append(
            _requirement(
                "evidence_freshness",
                False,
                f"{future_dated_count:.0f} evidence item(s) are future-dated.",
                blocking=True,
            )
        )
    else:
        freshness_passes = (
            freshness_status == "recent_evidence_present"
            if require_recent_evidence
            else freshness_status not in {"no_evidence", "future_dated_only"}
        )
        requirements.append(
            _requirement(
                "evidence_freshness",
                freshness_passes,
                (
                    "Recent dated evidence is present."
                    if freshness_passes
                    else (
                        "Recent dated evidence is required."
                        if require_recent_evidence
                        else "Evidence freshness is unavailable or there is no evidence."
                    )
                ),
            )
        )

    collected_at_raw = market.get("collected_at")
    collected_at = _datetime(collected_at_raw)
    as_of_value = _datetime(as_of) or datetime.now(timezone.utc)
    if collected_at is None:
        snapshot_detail = (
            "A valid market collection timestamp is required for a current-snapshot check."
            if collected_at_raw
            else "No market collection timestamp is available for a current-snapshot check."
        )
        requirements.append(
            _requirement(
                "market_snapshot_freshness",
                False,
                snapshot_detail,
            )
        )
    else:
        snapshot_age_seconds = (as_of_value - collected_at).total_seconds()
        if snapshot_age_seconds < -max_future_skew_seconds:
            requirements.append(
                _requirement(
                    "market_snapshot_freshness",
                    False,
                    "Market snapshot timestamp is too far in the future.",
                    blocking=True,
                )
            )
        else:
            snapshot_passes = snapshot_age_seconds <= max_snapshot_age_seconds
            requirements.append(
                _requirement(
                    "market_snapshot_freshness",
                    snapshot_passes,
                    (
                        f"Market snapshot is {max(0.0, snapshot_age_seconds):.1f} seconds old; "
                        f"limit is {max_snapshot_age_seconds} seconds."
                        if snapshot_passes
                        else (
                            f"Market snapshot is {snapshot_age_seconds:.1f} seconds old; "
                            f"limit is {max_snapshot_age_seconds} seconds."
                        )
                    ),
                )
            )

    risk_level = str(red_team.get("risk_level") or "").strip().lower()
    if risk_level not in _RISK_LEVELS:
        requirements.append(
            _requirement(
                "risk_level",
                False,
                "A recognized red-team risk level is required.",
                blocking=True,
            )
        )
    else:
        risk_passes = _RISK_LEVELS[risk_level] <= _RISK_LEVELS[normalized_max_risk]
        requirements.append(
            _requirement(
                "risk_level",
                risk_passes,
                (
                    f"Risk level is {risk_level}; configured maximum is "
                    f"{normalized_max_risk}."
                ),
                blocking=not risk_passes,
            )
        )

    fetch_failures = _number(narrative_quality.get("fetch_failures")) or 0
    requirements.append(
        _requirement(
            "source_fetches",
            fetch_failures == 0,
            (
                "All fetched source checks completed."
                if fetch_failures == 0
                else f"{fetch_failures:.0f} source fetch check(s) failed and need review."
            ),
        )
    )

    counterevidence_count = _number(
        narrative_quality.get("counterevidence_leads")
    ) or 0
    requirements.append(
        _requirement(
            "counterevidence_review",
            counterevidence_count == 0,
            (
                "No unresolved counterevidence lead was returned."
                if counterevidence_count == 0
                else (
                    f"{counterevidence_count:.0f} counterevidence lead(s) require "
                    "manual review."
                )
            ),
        )
    )

    if order_preview is None:
        order_preview_ready = False
        requirements.append(
            _requirement(
                "order_preview",
                True,
                "No order preview was requested; only research requirements were evaluated.",
                status="not_requested",
            )
        )
        requirements.append(
            _requirement(
                "execution_safety",
                True,
                "Execution is disabled by design.",
            )
        )
    else:
        preview_status = str(order_preview.get("status") or "unknown")
        order_preview_ready = (
            preview_status == "ready_for_manual_review"
            and order_preview.get("manual_approval_required") is True
            and order_preview.get("execution_enabled") is False
        )
        requirements.append(
            _requirement(
                "order_preview",
                preview_status == "ready_for_manual_review",
                (
                    "Order preview passed its explicit market and size checks."
                    if preview_status == "ready_for_manual_review"
                    else f"Order preview status is {preview_status}; it must be ready_for_manual_review."
                ),
                blocking=True,
            )
        )
        requirements.append(
            _requirement(
                "execution_safety",
                order_preview.get("manual_approval_required") is True
                and order_preview.get("execution_enabled") is False,
                "Preview must require manual approval and keep execution disabled.",
                blocking=True,
            )
        )

    failed_requirements = [
        requirement["name"]
        for requirement in requirements
        if not requirement["passed"]
    ]
    blocking_failures = [
        requirement["name"]
        for requirement in requirements
        if not requirement["passed"] and requirement["blocking"]
    ]
    review_requirements = [
        requirement["name"]
        for requirement in requirements
        if not requirement["passed"] and not requirement["blocking"]
    ]

    if blocking_failures:
        status = "blocked"
    elif failed_requirements:
        status = "research_only"
    else:
        status = "manual_review_ready"

    notices = []
    if order_preview is None:
        notices.append(
            "No order preview was requested; this result does not evaluate a proposed notional."
        )
    if counterevidence_count:
        notices.append("Counterevidence must be resolved by the reviewer.")
    if fetch_failures:
        notices.append("Some source pages could not be checked.")
    if review_requirements:
        notices.append(
            "One or more non-blocking research requirements still need review."
        )

    return {
        "status": status,
        "manual_review_ready": status == "manual_review_ready",
        "order_preview_requested": order_preview is not None,
        "order_preview_ready": order_preview_ready,
        "requirements_met": not failed_requirements,
        "requirements": requirements,
        "failed_requirements": failed_requirements,
        "blocking_failures": blocking_failures,
        "review_requirements": review_requirements,
        "notices": notices,
        "risk_level": risk_level or None,
        "thresholds": {
            "min_radar_score": float(min_radar_score),
            "max_risk_level": normalized_max_risk,
            "require_recent_evidence": bool(require_recent_evidence),
            "max_snapshot_age_seconds": int(max_snapshot_age_seconds),
            "max_future_skew_seconds": int(max_future_skew_seconds),
        },
        "decision_only": True,
        "manual_approval_required": True,
        "execution_enabled": False,
        "note": (
            "This gate makes research requirements explicit for human review. "
            "It is not a trade signal, order authorization, or promise of returns; "
            "no transaction is created, signed, or submitted."
        ),
    }
