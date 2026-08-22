import requests
from datetime import datetime, timezone


DEXSCREENER_TOKEN_URL = (
    "https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
)


def fetch_market_data(contract_address: str) -> dict:
    """
    Fetch live DEX market data for a token contract.

    Returns normalized data for the strongest-liquidity pair found.
    """

    url = DEXSCREENER_TOKEN_URL.format(
        contract_address=contract_address
    )

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    payload = response.json()
    pairs = payload.get("pairs") or []

    if not pairs:
        return {
            "found": False,
            "contract_address": contract_address,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

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