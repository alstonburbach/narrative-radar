from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


DEXSCREENER_TOKEN_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
)


CHAIN_ALIASES = {
    "bnb": "bsc",
    "binance": "bsc",
    "binance-smart-chain": "bsc",
    "eth": "ethereum",
    "sol": "solana",
    "arb": "arbitrum",
    "matic": "polygon",
    "op": "optimism",
    "avax": "avalanche",
}


def normalize_chain(chain: Optional[str]) -> Optional[str]:
    """Return a stable chain label for user input and DexScreener output."""

    if chain is None:
        return None

    value = str(chain).strip().lower().replace("_", "-").replace(" ", "-")
    if not value or value in {"any", "all", "*"}:
        return None

    return CHAIN_ALIASES.get(value, value)


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_market_result(
    contract_address: str,
    requested_chain: Optional[str],
    reason: Optional[str] = None,
    available_chains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "found": False,
        "contract_address": contract_address,
        "requested_chain": requested_chain,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    if reason:
        result["reason"] = reason
    if available_chains:
        result["available_chains"] = available_chains

    return result


def fetch_market_data(
    contract_address: str,
    requested_chain: Optional[str] = None,
) -> dict:
    """
    Fetch live DEX market data for a token contract.

    Returns normalized data for the strongest-liquidity pair found.
    """

    contract_address = contract_address.strip()
    if not contract_address:
        raise ValueError("contract_address cannot be empty")

    normalized_chain = normalize_chain(requested_chain)
    url = DEXSCREENER_TOKEN_URL.format(contract_address=contract_address)

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    payload = response.json()
    pairs = payload.get("pairs") or []

    if not pairs:
        return _empty_market_result(
            contract_address,
            normalized_chain,
            reason="no_pairs_found",
        )

    available_chains = sorted(
        {
            str(pair.get("chainId"))
            for pair in pairs
            if pair.get("chainId")
        }
    )

    if normalized_chain:
        pairs = [
            pair
            for pair in pairs
            if normalize_chain(pair.get("chainId")) == normalized_chain
        ]

        if not pairs:
            return _empty_market_result(
                contract_address,
                normalized_chain,
                reason="no_pair_on_requested_chain",
                available_chains=available_chains,
            )

    # Prefer the pair with the most USD liquidity.
    best_pair = max(
        pairs,
        key=lambda pair: (
            pair.get("liquidity", {}).get("usd") or 0
        ),
    )

    base_token = best_pair.get("baseToken", {})
    quote_token = best_pair.get("quoteToken", {})
    liquidity = best_pair.get("liquidity", {})
    volume = best_pair.get("volume", {})
    price_change = best_pair.get("priceChange", {})

    return {
        "found": True,
        "contract_address": contract_address,
        "requested_chain": normalized_chain,
        "token_name": base_token.get("name"),
        "token_symbol": base_token.get("symbol"),
        "chain": best_pair.get("chainId"),
        "dex": best_pair.get("dexId"),
        "pair_address": best_pair.get("pairAddress"),
        "quote_symbol": quote_token.get("symbol"),
        "price_usd": best_pair.get("priceUsd"),
        "market_cap": best_pair.get("marketCap"),
        "fdv": best_pair.get("fdv"),
        "liquidity_usd": liquidity.get("usd"),
        "volume_24h": volume.get("h24"),
        "volume_6h": volume.get("h6"),
        "volume_1h": volume.get("h1"),
        "price_change_24h": price_change.get("h24"),
        "price_change_6h": price_change.get("h6"),
        "price_change_1h": price_change.get("h1"),
        "dex_url": best_pair.get("url"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
