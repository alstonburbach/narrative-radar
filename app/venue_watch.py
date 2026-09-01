"""Launch-venue watch pipeline with fail-closed market and safety gates."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from app.collectors.token_security import GoPlusTokenSecurityProvider
from app.collectors.venue_discovery import DexScreenerVenueProvider
from app.database.db import (
    get_latest_venue_candidate_observation,
    initialize_database,
    save_venue_candidate_observation,
)


_ALERT_STATUSES = {"screened_research", "research_now"}
_SIGNAL_ORDER = {
    "screened_research": 0,
    "research_now": 1,
    "queued_security": 2,
    "market_watch": 3,
    "blocked_linked_wallets": 4,
    "blocked_security": 5,
    "blocked_market_risk": 6,
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _security_failure(provider: Any, exc: Exception) -> dict:
    return {
        "status": "failed",
        "provider": getattr(provider, "provider_name", "custom"),
        "risk_level": "unknown",
        "hard_blockers": ["token_security_unavailable"],
        "promotion_eligible": False,
        "error_type": type(exc).__name__,
        "execution_enabled": False,
        "note": "The contract-security lookup failed closed.",
    }


def _bundler_failure(provider: Any, exc: Exception) -> dict:
    return {
        "status": "failed",
        "provider": getattr(provider, "provider_name", "custom"),
        "hard_blockers": [],
        "error_type": type(exc).__name__,
        "execution_enabled": False,
        "note": "Linked-wallet collection failed safely; manual review is required.",
    }


def _holder_failure(provider: Any, exc: Exception) -> dict:
    return {
        "status": "failed",
        "source": getattr(provider, "provider_name", "helius"),
        "holder_scan_complete": False,
        "hard_blockers": ["holder_distribution_unavailable"],
        "error_type": type(exc).__name__,
        "note": "The holder-distribution lookup failed closed.",
    }


def _default_adoption_provider() -> tuple[Any | None, str | None]:
    try:
        from app.collectors.adoption_provider import HeliusAdoptionProvider

        return HeliusAdoptionProvider(), None
    except RuntimeError as exc:
        return None, str(exc)


def _can_complete_solana_holder_gap(token_security: Mapping[str, Any]) -> bool:
    blockers = set(token_security.get("hard_blockers") or [])
    severe_flags = [
        flag
        for flag in token_security.get("flags") or []
        if isinstance(flag, Mapping)
        and str(flag.get("severity") or "").lower() in {"high", "critical"}
    ]
    return (
        token_security.get("status") == "complete"
        and token_security.get("chain") == "solana"
        and token_security.get("authority_data_complete") is True
        and blockers == {"security_data_incomplete"}
        and not severe_flags
        and token_security.get("execution_enabled") is False
    )


def _evaluate_holder_snapshot(snapshot: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers = []
    if snapshot.get("status") not in {"complete", "partial"}:
        blockers.append("holder_distribution_unavailable")
    if snapshot.get("holder_scan_complete") is not True:
        blockers.append("holder_scan_incomplete")
    coverage = _number(snapshot.get("scanned_supply_coverage_pct"))
    if coverage is None or coverage < 99:
        blockers.append("holder_supply_coverage_incomplete")
    largest = _number(snapshot.get("largest_scanned_owner_share_pct"))
    top_ten = _number(snapshot.get("top_10_scanned_owner_share_pct"))
    if largest is None or top_ten is None:
        blockers.append("holder_concentration_unavailable")
    else:
        if largest >= 20:
            blockers.append("single_holder_concentration")
        if top_ten >= 60:
            blockers.append("top_holder_concentration")
    return not blockers, list(dict.fromkeys(blockers))


def _complete_security_with_helius(
    token_security: dict,
    holder_snapshot: Mapping[str, Any],
) -> None:
    token_security["hard_blockers"] = [
        value
        for value in token_security.get("hard_blockers") or []
        if value != "security_data_incomplete"
    ]
    token_security["flags"] = [
        flag
        for flag in token_security.get("flags") or []
        if not isinstance(flag, Mapping)
        or flag.get("code") != "holder_distribution_unknown"
    ]
    token_security["holder_distribution"] = {
        "row_count": holder_snapshot.get("holder_count"),
        "raw_top_rows_share_pct": holder_snapshot.get(
            "top_10_scanned_owner_share_pct"
        ),
        "largest_unlocked_unexcluded_share_pct": holder_snapshot.get(
            "largest_scanned_owner_share_pct"
        ),
        "top_unlocked_unexcluded_share_pct": holder_snapshot.get(
            "top_10_scanned_owner_share_pct"
        ),
        "source": "helius_complete_holder_scan",
        "supply_coverage_pct": holder_snapshot.get("scanned_supply_coverage_pct"),
        "excluded_market_owner_count": holder_snapshot.get(
            "concentration_excluded_owner_count", 0
        ),
    }
    token_security["data_complete"] = True
    token_security["promotion_eligible"] = True
    token_security["provider"] = "goplus+helius"
    token_security["note"] = (
        "GoPlus authority controls and a complete Helius holder scan were combined. "
        "Linked-wallet analysis remains a separate required check."
    )


def _change_state(candidate: dict, previous: dict | None) -> str:
    if previous is None:
        return "new"
    current_status = str(candidate.get("signal_status") or "blocked_market_risk")
    previous_status = str(previous.get("signal_status") or "blocked_market_risk")
    if current_status != previous_status:
        if _SIGNAL_ORDER.get(current_status, 99) < _SIGNAL_ORDER.get(previous_status, 99):
            return "promoted"
        return "downgraded"

    if current_status in _ALERT_STATUSES:
        current_liquidity = _number(candidate.get("liquidity_usd"))
        previous_liquidity = _number(previous.get("liquidity_usd"))
        current_volume = _number(candidate.get("volume_1h"))
        previous_volume = _number(previous.get("volume_1h"))
        if (
            current_liquidity is not None
            and previous_liquidity is not None
            and previous_liquidity > 0
            and current_volume is not None
            and previous_volume is not None
            and previous_volume > 0
            and current_liquidity >= previous_liquidity * 1.75
            and current_volume >= previous_volume * 1.75
        ):
            return "materially_strengthened"
    return "unchanged"


def _default_bundler_provider(chain: str) -> tuple[Any | None, str | None]:
    try:
        if str(chain or "").strip().lower() in {"robinhood", "robinhood_chain"}:
            from app.collectors.evm_bundler_provider import RobinhoodBundlerProvider

            return RobinhoodBundlerProvider(), None
        from app.collectors.bundler_provider import HeliusBundlerProvider

        return HeliusBundlerProvider(), None
    except RuntimeError as exc:
        return None, str(exc)


def run_venue_watch(
    *,
    provider: Any | None = None,
    security_provider: Any | None = None,
    adoption_provider: Any | None = None,
    bundler_provider: Any | None = None,
    venues: tuple[str, ...] = ("pump_fun", "robinhood_chain"),
    profile_limit_per_venue: int = 12,
    candidate_limit: int = 12,
    security_limit: int = 8,
    onchain_limit: int = 1,
    bundler_limit: int = 1,
    persist: bool = True,
) -> dict:
    """Collect launch leads and return only change-based research alerts.

    ``screened_research`` is still not a buy instruction. It only means every
    configured bounded research check completed without a hard blocker.
    """
    collector = provider or DexScreenerVenueProvider()
    security = security_provider or GoPlusTokenSecurityProvider()
    security_limit = max(0, min(int(security_limit), 30))
    onchain_limit = max(0, min(int(onchain_limit), 5))
    bundler_limit = max(0, min(int(bundler_limit), 5))

    report = collector.collect(
        venues=venues,
        profile_limit_per_venue=profile_limit_per_venue,
        candidate_limit=candidate_limit,
    )
    candidates = list(report.get("candidates") or [])
    if persist:
        initialize_database()

    previous_by_key: dict[tuple[str, str], dict | None] = {}
    for candidate in candidates:
        key = (
            str(candidate.get("venue") or ""),
            str(candidate.get("contract_address") or "").casefold(),
        )
        previous_by_key[key] = (
            get_latest_venue_candidate_observation(*key) if persist else None
        )

    security_scans = 0
    holder_scans = 0
    bundler_scans = 0
    bundler_scans_by_chain: dict[str, int] = {}
    active_adoption_provider = adoption_provider
    adoption_provider_error = None
    active_bundler_providers: dict[str, Any] = {}
    bundler_provider_errors: dict[str, str | None] = {}

    for candidate in candidates:
        preliminary = str((candidate.get("market_screen") or {}).get("status"))
        candidate["token_security"] = {
            "status": "not_requested",
            "hard_blockers": [],
            "promotion_eligible": False,
            "execution_enabled": False,
        }
        candidate["bundler_analysis"] = {
            "status": "not_requested",
            "hard_blockers": [],
            "execution_enabled": False,
        }
        candidate["onchain_holder_analysis"] = {
            "status": "not_requested",
            "holder_scan_complete": False,
        }

        if preliminary == "blocked_market_risk":
            candidate["signal_status"] = "blocked_market_risk"
            candidate["signal_note"] = "Market-risk blockers prevent promotion."
            continue
        if preliminary != "research_next":
            candidate["signal_status"] = "market_watch"
            candidate["signal_note"] = "Market activity needs more confirmation."
            continue
        if security_scans >= security_limit:
            candidate["signal_status"] = "queued_security"
            candidate["signal_note"] = "The bounded security-scan capacity was reached."
            continue

        security_scans += 1
        try:
            token_security = security.fetch(
                contract_address=candidate["contract_address"],
                chain=candidate["chain"],
            )
            if not isinstance(token_security, Mapping):
                raise RuntimeError("token security provider returned invalid data")
            token_security = dict(token_security)
        except Exception as exc:  # noqa: BLE001 - fail closed on public provider errors
            token_security = _security_failure(security, exc)
        candidate["token_security"] = token_security
        security_blockers = list(token_security.get("hard_blockers") or [])
        security_passed = (
            token_security.get("status") == "complete"
            and token_security.get("promotion_eligible") is True
            and not security_blockers
            and token_security.get("execution_enabled") is False
        )
        if (
            not security_passed
            and candidate.get("venue") == "pump_fun"
            and _can_complete_solana_holder_gap(token_security)
        ):
            key = (
                str(candidate.get("venue") or ""),
                str(candidate.get("contract_address") or "").casefold(),
            )
            previous = previous_by_key.get(key)
            previous_holder = ((previous or {}).get("raw") or {}).get(
                "onchain_holder_analysis"
            ) or {}
            previous_holder_passed, _ = _evaluate_holder_snapshot(previous_holder)
            if previous_holder_passed:
                holder_snapshot = dict(previous_holder)
                holder_snapshot["reused_from_previous_scan"] = True
            elif holder_scans >= onchain_limit:
                holder_snapshot = {
                    "status": "not_scanned_capacity",
                    "holder_scan_complete": False,
                    "note": "The bounded Helius holder-scan capacity was reached.",
                }
            else:
                if (
                    active_adoption_provider is None
                    and adoption_provider_error is None
                ):
                    active_adoption_provider, adoption_provider_error = (
                        _default_adoption_provider()
                    )
                if active_adoption_provider is None:
                    holder_snapshot = {
                        "status": "not_configured",
                        "source": "helius",
                        "holder_scan_complete": False,
                        "error": adoption_provider_error,
                        "note": "Set HELIUS_API_KEY for bounded holder checks.",
                    }
                else:
                    holder_scans += 1
                    excluded_owners = [
                        candidate.get("pair_address")
                    ] if candidate.get("pair_address") else []
                    try:
                        holder_snapshot = active_adoption_provider.fetch_snapshot(
                            token_address=candidate["contract_address"],
                            chain=candidate["chain"],
                            holder_limit=2_000,
                            transfer_limit=1,
                            activity_window_hours=1,
                            concentration_excluded_owners=excluded_owners,
                        )
                        if not isinstance(holder_snapshot, Mapping):
                            raise RuntimeError("holder provider returned invalid data")
                        holder_snapshot = dict(holder_snapshot)
                    except Exception as exc:  # noqa: BLE001 - fail closed and redact in provider
                        holder_snapshot = _holder_failure(
                            active_adoption_provider, exc
                        )
            candidate["onchain_holder_analysis"] = holder_snapshot
            holder_passed, holder_blockers = _evaluate_holder_snapshot(
                holder_snapshot
            )
            if holder_passed:
                _complete_security_with_helius(token_security, holder_snapshot)
                security_blockers = []
                security_passed = True
            else:
                concentration_blockers = {
                    "single_holder_concentration",
                    "top_holder_concentration",
                } & set(holder_blockers)
                if concentration_blockers:
                    token_security["hard_blockers"] = list(
                        dict.fromkeys(
                            list(token_security.get("hard_blockers") or [])
                            + sorted(concentration_blockers)
                        )
                    )
                    token_security["risk_level"] = "high"
                    candidate["signal_status"] = "blocked_security"
                    candidate["signal_note"] = (
                        "A complete Helius holder scan found concentrated ownership."
                    )
                else:
                    candidate["signal_status"] = "queued_security"
                    candidate["signal_note"] = (
                        "Holder coverage is incomplete; the candidate remains queued."
                    )
                continue
        if not security_passed and candidate.get("venue") != "robinhood_chain":
            candidate["signal_status"] = "blocked_security"
            candidate["signal_note"] = (
                "Contract-security or distribution checks did not pass."
            )
            candidate["gate_reason"] = candidate["signal_note"]
            continue

        key = (
            str(candidate.get("venue") or ""),
            str(candidate.get("contract_address") or "").casefold(),
        )
        previous = previous_by_key.get(key)
        previous_bundler = ((previous or {}).get("raw") or {}).get(
            "bundler_analysis"
        ) or {}
        chain_key = str(candidate.get("chain") or "unknown").strip().lower()
        same_pair = str(previous_bundler.get("pair_address") or "").casefold() == str(
            candidate.get("pair_address") or ""
        ).casefold()
        version_matches = (
            chain_key != "robinhood"
            or previous_bundler.get("analysis_version") == "robinhood-links-v1"
        )
        if (
            previous_bundler.get("status") == "complete"
            and not previous_bundler.get("hard_blockers")
            and (chain_key != "robinhood" or same_pair)
            and version_matches
        ):
            bundler_analysis = dict(previous_bundler)
            bundler_analysis["reused_from_previous_scan"] = True
        elif bundler_scans_by_chain.get(chain_key, 0) >= bundler_limit:
            bundler_analysis = {
                "status": "not_scanned_capacity",
                "hard_blockers": [],
                "execution_enabled": False,
                "note": (
                    f"The bounded {chain_key} linked-wallet scan capacity was reached."
                ),
            }
        else:
            active_bundler_provider = bundler_provider or active_bundler_providers.get(
                chain_key
            )
            if (
                active_bundler_provider is None
                and chain_key not in bundler_provider_errors
            ):
                active_bundler_provider, provider_error = _default_bundler_provider(
                    chain_key
                )
                bundler_provider_errors[chain_key] = provider_error
                if active_bundler_provider is not None:
                    active_bundler_providers[chain_key] = active_bundler_provider
            if active_bundler_provider is None:
                bundler_analysis = {
                    "status": "not_configured",
                    "provider": (
                        "robinhood_rpc_blockscout"
                        if chain_key == "robinhood"
                        else "helius"
                    ),
                    "hard_blockers": [],
                    "execution_enabled": False,
                    "error": bundler_provider_errors.get(chain_key),
                    "note": (
                        "Set HELIUS_API_KEY for bounded linked-wallet checks."
                        if chain_key != "robinhood"
                        else "Robinhood linked-wallet providers could not be configured."
                    ),
                }
            else:
                bundler_scans += 1
                bundler_scans_by_chain[chain_key] = (
                    bundler_scans_by_chain.get(chain_key, 0) + 1
                )
                try:
                    bundler_analysis = active_bundler_provider.fetch(
                        token_address=candidate["contract_address"],
                        chain=candidate["chain"],
                        pair_address=candidate.get("pair_address"),
                        pair_created_at=candidate.get("pair_created_at"),
                        pair_created_at_iso=candidate.get("pair_created_at_iso"),
                    )
                    if not isinstance(bundler_analysis, Mapping):
                        raise RuntimeError("bundler provider returned invalid data")
                    bundler_analysis = dict(bundler_analysis)
                except Exception as exc:  # noqa: BLE001 - fail closed without leaking keys
                    bundler_analysis = _bundler_failure(
                        active_bundler_provider, exc
                    )
        candidate["bundler_analysis"] = bundler_analysis
        bundler_blockers = list(bundler_analysis.get("hard_blockers") or [])
        gate_reasons = []
        if not security_passed:
            security_codes = list(token_security.get("hard_blockers") or [])
            candidate["signal_status"] = "blocked_security"
            gate_reasons.append(
                "Contract-security or holder evidence is incomplete or blocked"
                + (f": {', '.join(security_codes)}" if security_codes else ".")
            )
            if bundler_blockers:
                gate_reasons.append(
                    "The bounded wallet check also found concentrated links: "
                    + ", ".join(bundler_blockers)
                    + "."
                )
            elif bundler_analysis.get("status") == "complete":
                gate_reasons.append(
                    "The bounded Robinhood wallet check completed with no hard linked-wallet blocker observed."
                )
            else:
                gate_reasons.append(
                    "The bounded Robinhood wallet check is incomplete; wallet-link risk remains unknown."
                )
            candidate["signal_note"] = " ".join(gate_reasons)
        elif bundler_blockers:
            candidate["signal_status"] = "blocked_linked_wallets"
            candidate["signal_note"] = (
                "Observable linked-wallet concentration triggered a hard blocker."
            )
        elif bundler_analysis.get("status") == "complete":
            candidate["signal_status"] = "screened_research"
            candidate["signal_note"] = (
                "Configured market, token-security, and linked-wallet checks passed."
            )
        else:
            candidate["signal_status"] = "research_now"
            candidate["signal_note"] = (
                "Market and token-security checks passed; linked-wallet review is incomplete."
            )
        candidate["gate_reasons"] = gate_reasons or [candidate["signal_note"]]
        candidate["gate_reason"] = candidate["signal_note"]

    notification_candidates = []
    for candidate in candidates:
        key = (
            str(candidate.get("venue") or ""),
            str(candidate.get("contract_address") or "").casefold(),
        )
        previous = previous_by_key.get(key)
        candidate["change_state"] = _change_state(candidate, previous)
        previous_status = str((previous or {}).get("signal_status") or "")
        safety_downgrade = (
            previous_status in _ALERT_STATUSES
            and candidate.get("signal_status") not in _ALERT_STATUSES
            and candidate["change_state"] == "downgraded"
        )
        positive_update = (
            candidate.get("signal_status") in _ALERT_STATUSES
            and candidate["change_state"]
            in {"new", "promoted", "materially_strengthened"}
        )
        if safety_downgrade:
            candidate["notification_kind"] = "safety_downgrade"
            notification_candidates.append(candidate)
        elif positive_update:
            candidate["notification_kind"] = "research_candidate"
            notification_candidates.append(candidate)
        if persist:
            candidate["observation_id"] = save_venue_candidate_observation(candidate)

    report["candidates"] = candidates
    report["security_scans"] = security_scans
    report["holder_scans"] = holder_scans
    report["bundler_scans"] = bundler_scans
    report["bundler_scans_by_chain"] = bundler_scans_by_chain
    report["notification"] = {
        "notify": bool(notification_candidates),
        "reason": (
            "new_strengthened_or_safety_changed_candidate"
            if notification_candidates
            else "no_new_candidate_passed_the_available_gates"
        ),
        "candidate_count": len(notification_candidates),
        "research_candidate_count": sum(
            item.get("notification_kind") == "research_candidate"
            for item in notification_candidates
        ),
        "safety_downgrade_count": sum(
            item.get("notification_kind") == "safety_downgrade"
            for item in notification_candidates
        ),
        "candidates": notification_candidates[:3],
    }
    report["execution_enabled"] = False
    report["note"] = (
        "Alerts are exact-contract research candidates, not buy calls. Missing safety "
        "coverage stays visible and no transaction is created, signed, or submitted."
    )
    return report
