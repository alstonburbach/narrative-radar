"""Live chain and launchpad activity collector for market-rotation research.

Uses DefiLlama's public DEX overview endpoint as a broad chain-activity source.
The collector intentionally fails closed: missing fields remain missing and are
never converted to zero activity. Launchpad rows are only emitted when a known
protocol is explicitly present in provider data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

import requests


CHAIN_PROVIDER_NAMES = {
    "solana": "Solana",
    "robinhood": "Robinhood Chain",
    "base": "Base",
    "ethereum": "Ethereum",
    "bsc": "BSC",
}

# Protocol names are provider-facing aliases, not token-name guesses.
LAUNCHPAD_PROTOCOL_ALIASES = {
    "pump_fun": {"pump", "pump.fun", "pumpswap"},
    "pons": {"pons"},
}

API_TEMPLATE = (
    "https://api.llama.fi/overview/dexs/{chain}"
    "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
    "&dataType=dailyVolume"
)


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _first_number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _daily_baseline(total: float | None, days: int) -> float | None:
    if total is None or total < 0 or days <= 0:
        return None
    return total / days


def _protocol_name(row: Mapping[str, Any]) -> str:
    return str(row.get("displayName") or row.get("name") or row.get("module") or "").strip()


def _protocol_volume(row: Mapping[str, Any]) -> tuple[float | None, float | None]:
    current = _first_number(row, "total24h", "dailyVolume", "volume24h")
    seven_day = _first_number(row, "total7d", "weeklyVolume", "volume7d")
    return current, _daily_baseline(seven_day, 7)


class DefiLlamaEcosystemActivityProvider:
    """Collect normalized DEX activity for supported chains and known launchpads."""

    provider_name = "defillama_dex_overview"

    def __init__(self, session=None, timeout: int = 15):
        self.session = session or requests.Session()
        self.timeout = max(1, int(timeout))

    def _get(self, chain_name: str) -> Mapping[str, Any]:
        response = self.session.get(
            API_TEMPLATE.format(chain=chain_name),
            headers={"User-Agent": "NarrativeRadar/1.0 (+research-only)"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise RuntimeError("DefiLlama DEX overview response was not an object")
        return payload

    def collect_chain(self, chain: str) -> list[dict]:
        chain_key = str(chain or "").strip().lower()
        provider_chain = CHAIN_PROVIDER_NAMES.get(chain_key)
        if not provider_chain:
            raise ValueError(f"Unsupported chain: {chain}")

        payload = self._get(provider_chain)
        observed_at = datetime.now(timezone.utc).isoformat()
        chain_24h = _first_number(payload, "total24h", "dailyVolume", "volume24h")
        chain_7d = _first_number(payload, "total7d", "weeklyVolume", "volume7d")
        protocols = [row for row in (payload.get("protocols") or []) if isinstance(row, Mapping)]

        active_protocols = 0
        baseline_active_protocols = 0
        for row in protocols:
            current, baseline = _protocol_volume(row)
            if current is not None and current >= 100_000:
                active_protocols += 1
            if baseline is not None and baseline >= 100_000:
                baseline_active_protocols += 1

        observations = [{
            "chain": chain_key,
            "venue": "",
            "provider": self.provider_name,
            "observed_at": observed_at,
            "status": "complete",
            "volume_usd": chain_24h,
            "baseline_volume_usd": _daily_baseline(chain_7d, 7),
            "active_traders": active_protocols,
            "baseline_active_traders": baseline_active_protocols,
            "metric_semantics": {
                "volume_usd": "current 24h DEX volume",
                "baseline_volume_usd": "7d average daily DEX volume",
                "active_traders": "proxy: protocols with >=$100k current 24h DEX volume",
                "baseline_active_traders": "proxy: protocols with >=$100k 7d-average daily DEX volume",
            },
            "execution_enabled": False,
        }]

        for row in protocols:
            name = _protocol_name(row).casefold()
            venue = next(
                (
                    venue_name
                    for venue_name, aliases in LAUNCHPAD_PROTOCOL_ALIASES.items()
                    if name in {alias.casefold() for alias in aliases}
                ),
                None,
            )
            if not venue:
                continue
            current, baseline = _protocol_volume(row)
            observations.append({
                "chain": chain_key,
                "venue": venue,
                "provider": self.provider_name,
                "provider_protocol": _protocol_name(row),
                "observed_at": observed_at,
                "status": "complete",
                "volume_usd": current,
                "baseline_volume_usd": baseline,
                "execution_enabled": False,
                "note": "Launchpad observation is emitted only from an explicit provider protocol match.",
            })
        return observations

    def collect(self, chains: tuple[str, ...] = tuple(CHAIN_PROVIDER_NAMES)) -> dict:
        observations: list[dict] = []
        failures: list[dict] = []
        for chain in chains:
            try:
                observations.extend(self.collect_chain(chain))
            except Exception as exc:  # noqa: BLE001 - partial provider outages are surfaced
                failures.append({
                    "chain": chain,
                    "provider": self.provider_name,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "note": "Provider failure was not interpreted as zero activity.",
                })
        return {
            "status": "complete" if observations and not failures else ("partial" if observations else "failed"),
            "observations": observations,
            "failures": failures,
            "execution_enabled": False,
        }
