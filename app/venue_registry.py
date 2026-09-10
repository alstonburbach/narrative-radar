"""Canonical chain and launchpad registry for Narrative Radar.

Keep ecosystem identity separate from token scoring. A chain is a network; a
venue is a launchpad/exchange on that network. Provenance should be verified
from contract/factory evidence when available rather than guessed from names.
"""

from __future__ import annotations
from typing import Any

CHAIN_REGISTRY: dict[str, dict[str, Any]] = {
    "solana": {"label": "Solana", "kind": "svm", "aliases": {"solana", "sol"}, "enabled": True},
    "robinhood": {"label": "Robinhood Chain", "kind": "evm", "chain_id": 4663, "aliases": {"robinhood", "robinhood_chain", "hood"}, "enabled": True},
    "base": {"label": "Base", "kind": "evm", "chain_id": 8453, "aliases": {"base"}, "enabled": True},
    "ethereum": {"label": "Ethereum", "kind": "evm", "chain_id": 1, "aliases": {"ethereum", "eth"}, "enabled": True},
    "bsc": {"label": "BNB Chain", "kind": "evm", "chain_id": 56, "aliases": {"bsc", "bnb", "bnb_chain"}, "enabled": True},
}

VENUE_REGISTRY: dict[str, dict[str, Any]] = {
    "pump_fun": {"label": "Pump.fun", "chain": "solana", "detection": "mint_pattern_plus_launch_dex", "enabled": True},
    "pons": {
        "label": "PONS", "chain": "robinhood", "detection": "factory_contract", "enabled": True,
        "factory_addresses": {"0xa5aab3f0c6eeadf30ef1d3eb997108e976351feb", "0x0c37a24f5d23a486fa692d1500881d698b1f77a4"},
        "source": "https://docs.ponsfamily.com/",
    },
    "robinhood_chain": {"label": "Robinhood Chain generic", "chain": "robinhood", "detection": "chain_only", "enabled": True},
}

def normalize_chain(value: str | None) -> str | None:
    needle = str(value or "").strip().lower()
    if not needle: return None
    for key, config in CHAIN_REGISTRY.items():
        if needle == key or needle in config.get("aliases", set()): return key
    return needle

def venue_config(venue: str | None) -> dict[str, Any] | None:
    config = VENUE_REGISTRY.get(str(venue or "").strip().lower())
    return dict(config) if config else None

def identify_factory_venue(*, chain: str | None, factory_address: str | None) -> str | None:
    normalized_chain = normalize_chain(chain)
    address = str(factory_address or "").strip().lower()
    if not normalized_chain or not address: return None
    for venue, config in VENUE_REGISTRY.items():
        if normalize_chain(config.get("chain")) == normalized_chain and address in config.get("factory_addresses", set()): return venue
    return None

def enabled_chains() -> tuple[str, ...]: return tuple(key for key, value in CHAIN_REGISTRY.items() if value.get("enabled"))
def enabled_venues() -> tuple[str, ...]: return tuple(key for key, value in VENUE_REGISTRY.items() if value.get("enabled"))
