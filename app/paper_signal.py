"""Forward-time paper signal snapshots and sampled market-cap marking."""

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


PAPER_SIGNAL_VERSION = 1
MILESTONE_MULTIPLES = (2.0, 3.0, 5.0)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _rounded(value: float | None, places: int = 4) -> float | None:
    return round(value, places) if value is not None else None


def _market_cap(market: Mapping[str, Any]) -> float | None:
    value = _number(market.get("market_cap"))
    return value if value is not None and value > 0 else None


def validate_paper_signal_state(state: Mapping[str, Any]) -> dict:
    """Validate a persisted state before any scheduled market request."""
    if int(state.get("version") or 0) != PAPER_SIGNAL_VERSION:
        raise ValueError("Unsupported paper signal state version.")
    contract = str(state.get("contract_address") or "").strip()
    if not contract or any(character.isspace() for character in contract):
        raise ValueError("Paper signal contract address is invalid.")
    entry_market_cap = _number(state.get("entry_market_cap"))
    stake_usd = _number(state.get("stake_usd"))
    target_multiple = _number(state.get("target_multiple"))
    if entry_market_cap is None or entry_market_cap <= 0:
        raise ValueError("Paper signal entry market cap is invalid.")
    if stake_usd is None or stake_usd <= 0:
        raise ValueError("Paper signal stake is invalid.")
    if target_multiple is None or target_multiple < 2:
        raise ValueError("Paper signal target multiple is invalid.")
    signal_time = _timestamp(state.get("signal_detected_at"))
    entry_time = _timestamp(state.get("entry_recorded_at"))
    if signal_time is None or entry_time is None or signal_time > entry_time:
        raise ValueError("Paper signal timing is invalid.")
    if state.get("execution_enabled") is not False:
        raise ValueError("Paper signal execution boundary is invalid.")
    return dict(state)


def create_paper_signal_state(
    request: Mapping[str, Any],
    analysis: Mapping[str, Any],
    issue_number: int,
    issue_created_at: str,
) -> dict:
    """Freeze a contemporaneous paper entry from an issue and analysis report."""
    market = analysis.get("market") or {}
    if not market.get("found"):
        raise ValueError("A live market pair is required to start a paper signal.")
    entry_market_cap = _market_cap(market)
    if entry_market_cap is None:
        raise ValueError("A positive market cap is required to start a paper signal.")
    signal_time = _timestamp(issue_created_at)
    entry_time = _timestamp(market.get("collected_at") or analysis.get("started_at"))
    if signal_time is None or entry_time is None:
        raise ValueError("Timezone-aware signal and entry timestamps are required.")
    if entry_time < signal_time:
        raise ValueError("Entry snapshot cannot predate the GitHub signal.")

    stake_usd = _number(request.get("stake_usd"))
    target_multiple = _number(request.get("target_multiple"))
    if stake_usd is None or stake_usd <= 0:
        raise ValueError("Paper stake must be positive.")
    if target_multiple is None or target_multiple < 2:
        raise ValueError("Target multiple must be at least 2.")

    gate = analysis.get("decision_gate") or {}
    quality = analysis.get("narrative_quality") or {}
    score = analysis.get("score") or {}
    risk = analysis.get("red_team") or {}
    state = {
        "version": PAPER_SIGNAL_VERSION,
        "paper_only": True,
        "execution_enabled": False,
        "status": "open",
        "mark_status": "ready",
        "source_issue_number": int(issue_number),
        "signal_source": request.get("signal_source") or "narrative_radar",
        "narrative_family": request.get("narrative_family") or "unassigned",
        "contract_address": str(request.get("contract_address") or "").strip(),
        "requested_chain": request.get("chain") or "unknown",
        "chain": market.get("chain") or request.get("chain") or "unknown",
        "token_name": market.get("token_name") or "Unknown",
        "token_symbol": market.get("token_symbol") or "Unknown",
        "stake_usd": round(stake_usd, 2),
        "target_multiple": round(target_multiple, 4),
        "target_market_cap": round(entry_market_cap * target_multiple, 2),
        "signal_detected_at": _iso(signal_time),
        "entry_recorded_at": _iso(entry_time),
        "entry_delay_seconds": round((entry_time - signal_time).total_seconds(), 2),
        "last_checked_at": _iso(entry_time),
        "last_marked_at": _iso(entry_time),
        "target_reached_at": None,
        "entry_market_cap": entry_market_cap,
        "current_market_cap": entry_market_cap,
        "highest_sampled_market_cap": entry_market_cap,
        "current_multiple": 1.0,
        "highest_sampled_multiple": 1.0,
        "gross_marked_value_usd": round(stake_usd, 2),
        "gross_marked_pnl_usd": 0.0,
        "sample_count": 1,
        "marks_count": 0,
        "milestones_reached": [],
        "entry_decision_gate": gate.get("status") or "not_evaluated",
        "entry_failed_requirements": list(gate.get("failed_requirements") or []),
        "entry_radar_score": score.get("radar_score"),
        "entry_narrative_quality_score": quality.get("quality_score"),
        "entry_narrative_classification": quality.get("classification"),
        "entry_risk_level": risk.get("risk_level"),
        "entry_snapshot": {
            "price_usd": market.get("price_usd"),
            "liquidity_usd": market.get("liquidity_usd"),
            "volume_24h": market.get("volume_24h"),
            "pair_address": market.get("pair_address"),
            "dex": market.get("dex"),
            "dex_url": market.get("dex_url"),
        },
        "latest_snapshot": {
            "price_usd": market.get("price_usd"),
            "liquidity_usd": market.get("liquidity_usd"),
            "volume_24h": market.get("volume_24h"),
            "pair_address": market.get("pair_address"),
            "dex": market.get("dex"),
            "dex_url": market.get("dex_url"),
        },
        "sampled_only_note": (
            "Highest values are based only on scheduled snapshots and can miss "
            "intraperiod highs or lows. Gross paper value excludes fees, taxes, "
            "slippage, supply changes, and execution constraints."
        ),
    }
    validate_paper_signal_state(state)
    return state


def _milestone_thresholds(target_multiple: float) -> list[float]:
    return sorted({*MILESTONE_MULTIPLES, float(target_multiple)})


def mark_paper_signal_state(
    raw_state: Mapping[str, Any],
    market: Mapping[str, Any],
    observed_at: str | None = None,
) -> tuple[dict, dict | None]:
    """Apply one later market snapshot and return an optional milestone alert."""
    state = validate_paper_signal_state(raw_state)
    state = deepcopy(state)
    observation_time = _timestamp(
        observed_at or market.get("collected_at") or datetime.now(timezone.utc).isoformat()
    )
    entry_time = _timestamp(state["entry_recorded_at"])
    if observation_time is None or entry_time is None or observation_time < entry_time:
        raise ValueError("Paper mark timestamp must not predate the entry snapshot.")
    state["last_checked_at"] = _iso(observation_time)

    if not market.get("found") or _market_cap(market) is None:
        state["mark_status"] = "market_unavailable"
        state["last_error"] = "No positive live market-cap snapshot was available."
        return state, None
    market_chain = str(market.get("chain") or "unknown").strip().lower()
    state_chain = str(state.get("chain") or "unknown").strip().lower()
    if state_chain not in {"unknown", "auto", "any"} and market_chain != state_chain:
        state["mark_status"] = "chain_mismatch"
        state["last_error"] = "The live pair chain did not match the entry chain."
        return state, None

    current_market_cap = _market_cap(market)
    entry_market_cap = float(state["entry_market_cap"])
    stake_usd = float(state["stake_usd"])
    target_multiple = float(state["target_multiple"])
    current_multiple = current_market_cap / entry_market_cap
    previous_high = _number(state.get("highest_sampled_multiple")) or 1.0
    highest_multiple = max(previous_high, current_multiple)
    highest_market_cap = max(
        _number(state.get("highest_sampled_market_cap")) or entry_market_cap,
        current_market_cap,
    )
    crossed = [
        threshold
        for threshold in _milestone_thresholds(target_multiple)
        if previous_high < threshold <= highest_multiple
    ]
    reached = sorted(
        {
            *(
                float(value)
                for value in state.get("milestones_reached") or []
                if _number(value) is not None
            ),
            *crossed,
        }
    )
    target_was_reached = bool(state.get("target_reached_at"))
    if highest_multiple >= target_multiple and not target_was_reached:
        state["target_reached_at"] = _iso(observation_time)
    if state.get("target_reached_at"):
        state["status"] = "target_reached"

    gross_value = stake_usd * current_multiple
    entry_pair = (state.get("entry_snapshot") or {}).get("pair_address")
    state.update(
        {
            "mark_status": "ready",
            "last_error": None,
            "last_marked_at": _iso(observation_time),
            "current_market_cap": current_market_cap,
            "highest_sampled_market_cap": highest_market_cap,
            "current_multiple": _rounded(current_multiple),
            "highest_sampled_multiple": _rounded(highest_multiple),
            "gross_marked_value_usd": round(gross_value, 2),
            "gross_marked_pnl_usd": round(gross_value - stake_usd, 2),
            "sample_count": int(state.get("sample_count") or 0) + 1,
            "marks_count": int(state.get("marks_count") or 0) + 1,
            "milestones_reached": reached,
            "age_hours": round(
                (observation_time - entry_time).total_seconds() / 3600,
                2,
            ),
            "latest_snapshot": {
                "price_usd": market.get("price_usd"),
                "liquidity_usd": market.get("liquidity_usd"),
                "volume_24h": market.get("volume_24h"),
                "pair_address": market.get("pair_address"),
                "dex": market.get("dex"),
                "dex_url": market.get("dex_url"),
                "pair_changed_since_entry": bool(
                    entry_pair
                    and market.get("pair_address")
                    and entry_pair != market.get("pair_address")
                ),
            },
        }
    )
    notification = None
    if not target_was_reached and state.get("target_reached_at"):
        notification = {
            "reason": "sampled_target_reached",
            "multiple": _rounded(highest_multiple),
            "message": (
                f"Sampled paper target reached: {state['token_symbol']} "
                f"touched {highest_multiple:.2f}x versus the recorded entry."
            ),
        }
    elif crossed:
        milestone = max(crossed)
        notification = {
            "reason": "sampled_milestone_reached",
            "multiple": milestone,
            "message": (
                f"Sampled paper milestone: {state['token_symbol']} reached "
                f"at least {milestone:g}x versus the recorded entry."
            ),
        }
    state["execution_enabled"] = False
    validate_paper_signal_state(state)
    return state, notification


def summarize_paper_signal_states(states: list[Mapping[str, Any]]) -> dict:
    """Aggregate current gross sampled marks without treating them as realized PnL."""
    valid = []
    for state in states:
        try:
            valid.append(validate_paper_signal_state(state))
        except ValueError:
            continue
    committed = sum(float(state["stake_usd"]) for state in valid)
    marked_value = sum(
        _number(state.get("gross_marked_value_usd")) or float(state["stake_usd"])
        for state in valid
    )
    target_hits = sum(bool(state.get("target_reached_at")) for state in valid)
    return {
        "paper_only": True,
        "execution_enabled": False,
        "signal_count": len(valid),
        "committed_usd": round(committed, 2),
        "gross_sampled_value_usd": round(marked_value, 2),
        "gross_sampled_pnl_usd": round(marked_value - committed, 2),
        "sampled_target_hit_count": target_hits,
        "sampled_target_hit_rate_pct": (
            round(target_hits / len(valid) * 100, 2) if valid else None
        ),
        "note": (
            "Marks are open, gross, sampled outcomes—not realized trading results. "
            "Costs and intraperiod highs or lows are not known."
        ),
    }
