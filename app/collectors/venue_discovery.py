"""Exact-contract launch leads from bounded public DEX Screener feeds.

The collector intentionally treats token profiles as promotional leads. A token
can only advance when its exact contract has a live pair and passes transparent
market-activity checks. Contract security and linked-wallet checks are applied
by the venue-watch pipeline, not inferred here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import requests


LATEST_TOKEN_PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_BATCH_URL = "https://api.dexscreener.com/tokens/v1/{chain}/{addresses}"

_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_STATUS_ORDER = {
    "research_next": 0,
    "watch_for_confirmation": 1,
    "blocked_market_risk": 2,
}

_EARLY_PAIR_MIN_MINUTES = 2
_EARLY_PAIR_MAX_MINUTES = 12
_MIN_DEX_VOLUME_1H_USD = 10_000
_MIN_DEX_TRANSACTIONS_1H = 50
_MIN_PUMP_MARKET_CAP_USD = 10_000
_MIN_PUMP_TRANSACTIONS_1H = 100
_MIN_BUY_SELL_RATIO = 1.10
_MAX_FIVE_MINUTE_DRAWDOWN_PCT = -10
_MAX_SINCE_LAUNCH_DRAWDOWN_PCT = -15
_MAX_SINCE_LAUNCH_RUN_UP_PCT = 100


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _same_address(left: Any, right: Any) -> bool:
    return bool(
        left
        and right
        and str(left).strip().casefold() == str(right).strip().casefold()
    )


def _safe_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url or any(character.isspace() or character in "<>" for character in url):
        return None
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _profile_venue(profile: Mapping[str, Any]) -> tuple[str, str] | None:
    chain = str(profile.get("chainId") or "").strip().lower()
    address = str(profile.get("tokenAddress") or "").strip()
    if chain == "robinhood" and _EVM_ADDRESS.fullmatch(address):
        return "robinhood_chain", "robinhood"
    if (
        chain == "solana"
        and _SOLANA_ADDRESS.fullmatch(address)
        and address.casefold().endswith("pump")
    ):
        return "pump_fun", "solana"
    return None


def _pair_created_at(value: Any) -> datetime | None:
    milliseconds = _number(value)
    if milliseconds is None or milliseconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _market_screen(candidate: dict, observed_at: datetime) -> dict:
    pair = candidate.get("pair") or {}
    blockers: list[str] = []
    cautions: list[str] = []

    if not pair:
        return {
            "status": "blocked_market_risk",
            "score": 0,
            "blockers": ["no_active_pair"],
            "cautions": [],
            "note": "The promotional profile has no active exact-contract market pair.",
        }

    liquidity = _number(candidate.get("liquidity_usd"))
    volume_1h = _number(candidate.get("volume_1h"))
    market_cap = _number(candidate.get("market_cap"))
    buys_1h = _number(candidate.get("buys_1h")) or 0
    sells_1h = _number(candidate.get("sells_1h")) or 0
    transactions_1h = buys_1h + sells_1h
    bonding_curve = (
        candidate.get("venue") == "pump_fun"
        and str(candidate.get("dex") or "").strip().lower() == "pumpfun"
    )
    candidate["market_structure"] = (
        "pump_fun_bonding_curve" if bonding_curve else "dex_pool"
    )
    price_change_5m = _number(candidate.get("price_change_5m"))
    price_change_1h = _number(candidate.get("price_change_1h"))
    created_at = _pair_created_at(candidate.get("pair_created_at"))
    pair_age_minutes = None
    if created_at is not None:
        pair_age_minutes = max(0.0, (observed_at - created_at).total_seconds() / 60)
        candidate["pair_created_at_iso"] = created_at.isoformat()
        candidate["pair_age_minutes"] = round(pair_age_minutes, 2)

    if candidate.get("venue_confidence") not in {"chain_confirmed", "launch_dex_confirmed"}:
        blockers.append("launch_venue_not_confirmed")
    if (liquidity is None or liquidity <= 0) and bonding_curve:
        cautions.append(
            "Pre-graduation Pump.fun bonding curve; traditional DEX liquidity is not available."
        )
        if sells_1h < 5:
            blockers.append("bonding_curve_sell_activity_unconfirmed")
    elif liquidity is None or liquidity <= 0:
        blockers.append("missing_liquidity")
    elif liquidity < 5_000:
        blockers.append("very_thin_liquidity")
    elif liquidity < 10_000:
        cautions.append("Liquidity is below $10,000.")
    if volume_1h is None:
        cautions.append("One-hour volume is unavailable.")
    elif volume_1h < _MIN_DEX_VOLUME_1H_USD:
        cautions.append("One-hour volume is below $10,000.")
    required_transactions = (
        _MIN_PUMP_TRANSACTIONS_1H if bonding_curve else _MIN_DEX_TRANSACTIONS_1H
    )
    if transactions_1h < required_transactions:
        cautions.append(
            f"Fewer than {required_transactions} early trades are visible."
        )
    if sells_1h > 0 and buys_1h < sells_1h * _MIN_BUY_SELL_RATIO:
        cautions.append("Early buy flow is not leading sell flow.")
    if price_change_5m is None or price_change_1h is None:
        cautions.append("Early momentum data is incomplete.")
    if (
        price_change_5m is not None
        and price_change_5m <= _MAX_FIVE_MINUTE_DRAWDOWN_PCT
    ):
        blockers.append("early_five_minute_breakdown")
    if (
        price_change_1h is not None
        and price_change_1h <= _MAX_SINCE_LAUNCH_DRAWDOWN_PCT
    ):
        blockers.append("early_since_launch_breakdown")
    elif (
        price_change_1h is not None
        and price_change_1h >= _MAX_SINCE_LAUNCH_RUN_UP_PCT
    ):
        blockers.append("early_run_up_already_extended")
    if market_cap and liquidity and market_cap / liquidity > 100:
        blockers.append("extreme_market_cap_to_liquidity")
    if pair_age_minutes is None:
        cautions.append("Pair age could not be verified.")
    elif pair_age_minutes < _EARLY_PAIR_MIN_MINUTES:
        cautions.append("The pair is under two minutes old and needs more observations.")
    elif pair_age_minutes > _EARLY_PAIR_MAX_MINUTES:
        blockers.append("outside_early_launch_window")

    score = 0
    score += 20
    score += (
        12
        if bonding_curve and (liquidity is None or liquidity <= 0)
        else (20 if liquidity is not None and liquidity >= 10_000 else 5)
    )
    score += 20 if volume_1h is not None and volume_1h >= 5_000 else 5
    score += 15 if transactions_1h >= 25 else 5
    score += 10 if buys_1h >= sells_1h else 3
    if pair_age_minutes is not None:
        score += (
            15
            if _EARLY_PAIR_MIN_MINUTES
            <= pair_age_minutes
            <= _EARLY_PAIR_MAX_MINUTES
            else 5
        )
    score = max(
        0,
        min(score - 20 * len(blockers) - 5 * len(cautions), 100),
    )

    if blockers:
        status = "blocked_market_risk"
    elif (
        (
            (
                not bonding_curve
                and liquidity is not None
                and liquidity >= 10_000
                and transactions_1h >= _MIN_DEX_TRANSACTIONS_1H
            )
            or (
                bonding_curve
                and market_cap is not None
                and market_cap >= _MIN_PUMP_MARKET_CAP_USD
                and sells_1h >= 10
                and transactions_1h >= _MIN_PUMP_TRANSACTIONS_1H
            )
        )
        and volume_1h is not None
        and volume_1h >= _MIN_DEX_VOLUME_1H_USD
        and sells_1h > 0
        and buys_1h >= sells_1h * _MIN_BUY_SELL_RATIO
        and price_change_5m is not None
        and price_change_5m > _MAX_FIVE_MINUTE_DRAWDOWN_PCT
        and price_change_1h is not None
        and _MAX_SINCE_LAUNCH_DRAWDOWN_PCT
        < price_change_1h
        < _MAX_SINCE_LAUNCH_RUN_UP_PCT
        and pair_age_minutes is not None
        and _EARLY_PAIR_MIN_MINUTES
        <= pair_age_minutes
        <= _EARLY_PAIR_MAX_MINUTES
    ):
        status = "research_next"
    else:
        status = "watch_for_confirmation"

    return {
        "status": status,
        "score": score,
        "blockers": list(dict.fromkeys(blockers)),
        "cautions": list(dict.fromkeys(cautions)),
        "note": (
            "This is a market-activity prefilter, not a contract-safety pass or buy signal."
        ),
    }


class DexScreenerVenueProvider:
    """Collect bounded Pump.fun and Robinhood Chain exact-contract leads."""

    provider_name = "dexscreener_latest_profiles"

    def __init__(self, session=None, timeout: int = 15):
        self.session = session or requests.Session()
        self.timeout = max(1, int(timeout))

    def _get_json(self, url: str) -> Any:
        response = self.session.get(
            url,
            headers={"User-Agent": "NarrativeRadar/1.0 (+research-only)"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _pairs_by_contract(
        self,
        profiles: Iterable[Mapping[str, Any]],
    ) -> dict[tuple[str, str], list[dict]]:
        addresses_by_chain: dict[str, list[str]] = defaultdict(list)
        for profile in profiles:
            chain = str(profile.get("chainId") or "").strip().lower()
            address = str(profile.get("tokenAddress") or "").strip()
            if address and address not in addresses_by_chain[chain]:
                addresses_by_chain[chain].append(address)

        pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for chain, addresses in addresses_by_chain.items():
            if not addresses:
                continue
            url = TOKEN_BATCH_URL.format(chain=chain, addresses=",".join(addresses[:30]))
            payload = self._get_json(url)
            if not isinstance(payload, list):
                raise RuntimeError("DEX Screener token-pair response was not a list")
            for pair in payload:
                if not isinstance(pair, Mapping):
                    continue
                base_address = str((pair.get("baseToken") or {}).get("address") or "")
                pair_chain = str(pair.get("chainId") or "").strip().lower()
                if base_address and pair_chain:
                    pairs[(pair_chain, base_address.casefold())].append(dict(pair))
        return pairs

    def collect(
        self,
        *,
        venues: Iterable[str] = ("pump_fun", "robinhood_chain"),
        profile_limit_per_venue: int = 12,
        candidate_limit: int = 12,
        observed_at: datetime | None = None,
    ) -> dict:
        wanted = {str(value).strip().lower() for value in venues}
        unsupported = wanted - {"pump_fun", "robinhood_chain"}
        if unsupported:
            raise ValueError(f"Unsupported venue(s): {', '.join(sorted(unsupported))}")
        profile_limit_per_venue = max(1, min(int(profile_limit_per_venue), 30))
        candidate_limit = max(1, min(int(candidate_limit), 30))
        observed = observed_at or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        observed = observed.astimezone(timezone.utc)

        payload = self._get_json(LATEST_TOKEN_PROFILES_URL)
        if not isinstance(payload, list):
            raise RuntimeError("DEX Screener latest-profile response was not a list")

        selected: list[dict] = []
        venue_counts: dict[str, int] = defaultdict(int)
        seen: set[tuple[str, str]] = set()
        for raw_profile in payload:
            if not isinstance(raw_profile, Mapping):
                continue
            venue_match = _profile_venue(raw_profile)
            if not venue_match:
                continue
            venue, chain = venue_match
            if venue not in wanted or venue_counts[venue] >= profile_limit_per_venue:
                continue
            address = str(raw_profile.get("tokenAddress") or "").strip()
            key = (chain, address.casefold())
            if key in seen:
                continue
            seen.add(key)
            venue_counts[venue] += 1
            selected.append({**dict(raw_profile), "venue": venue, "chain": chain})

        pairs_by_contract = self._pairs_by_contract(selected)
        candidates = []
        for profile in selected:
            chain = profile["chain"]
            address = str(profile.get("tokenAddress") or "").strip()
            pairs = pairs_by_contract.get((chain, address.casefold()), [])
            base_pairs = [
                pair
                for pair in pairs
                if _same_address((pair.get("baseToken") or {}).get("address"), address)
            ]
            best_pair = max(
                base_pairs,
                key=lambda pair: _number((pair.get("liquidity") or {}).get("usd")) or 0,
                default=None,
            )
            dex = str((best_pair or {}).get("dexId") or "").strip().lower()
            if profile["venue"] == "robinhood_chain":
                venue_confidence = "chain_confirmed"
            elif dex in {"pumpfun", "pumpswap"}:
                venue_confidence = "launch_dex_confirmed"
            else:
                venue_confidence = "mint_pattern_only"

            links = []
            for item in profile.get("links") or []:
                if not isinstance(item, Mapping):
                    continue
                url = _safe_url(item.get("url"))
                if url:
                    links.append(
                        {
                            "label": str(item.get("label") or item.get("type") or "source")[:40],
                            "url": url,
                        }
                    )

            liquidity = (best_pair or {}).get("liquidity") or {}
            volume = (best_pair or {}).get("volume") or {}
            txns = (best_pair or {}).get("txns") or {}
            price_change = (best_pair or {}).get("priceChange") or {}
            h1_txns = txns.get("h1") or {}
            base_token = (best_pair or {}).get("baseToken") or {}
            candidate = {
                "venue": profile["venue"],
                "chain": chain,
                "contract_address": address,
                "venue_confidence": venue_confidence,
                "token_name": base_token.get("name"),
                "token_symbol": base_token.get("symbol"),
                "profile_description": str(profile.get("description") or "")[:500],
                "profile_url": _safe_url(profile.get("url")),
                "profile_links": links[:5],
                "pair": dict(best_pair) if best_pair else None,
                "pair_address": (best_pair or {}).get("pairAddress"),
                "dex": (best_pair or {}).get("dexId"),
                "dex_url": _safe_url((best_pair or {}).get("url")),
                "pair_created_at": (best_pair or {}).get("pairCreatedAt"),
                "price_usd": _number((best_pair or {}).get("priceUsd")),
                "market_cap": _number((best_pair or {}).get("marketCap")),
                "fdv": _number((best_pair or {}).get("fdv")),
                "liquidity_usd": _number(liquidity.get("usd")),
                "volume_1h": _number(volume.get("h1")),
                "volume_6h": _number(volume.get("h6")),
                "volume_24h": _number(volume.get("h24")),
                "buys_1h": _number(h1_txns.get("buys")),
                "sells_1h": _number(h1_txns.get("sells")),
                "price_change_5m": _number(price_change.get("m5")),
                "price_change_1h": _number(price_change.get("h1")),
                "price_change_6h": _number(price_change.get("h6")),
                "observed_at": observed.isoformat(),
                "execution_enabled": False,
            }
            candidate["market_screen"] = _market_screen(candidate, observed)
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                _STATUS_ORDER[item["market_screen"]["status"]],
                -int(item["market_screen"]["score"]),
                -(_number(item.get("volume_1h")) or 0),
                -(_number(item.get("liquidity_usd")) or 0),
                item["contract_address"].casefold(),
            )
        )
        candidates = candidates[:candidate_limit]
        for index, candidate in enumerate(candidates, start=1):
            candidate["rank"] = index

        return {
            "version": 1,
            "status": "complete",
            "provider": self.provider_name,
            "observed_at": observed.isoformat(),
            "requested_venues": sorted(wanted),
            "profiles_received": len(payload),
            "eligible_profiles": len(selected),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "execution_enabled": False,
            "note": (
                "Latest token profiles are promotional discovery leads. Exact-contract "
                "market, security, and linked-wallet checks remain mandatory."
            ),
        }
