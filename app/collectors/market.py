import requests
from datetime import datetime, timezone


DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{contract_address}"


def _number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_address(left, right):
    return bool(left and right and str(left).strip().casefold() == str(right).strip().casefold())


def fetch_market_data(contract_address: str, chain: str = None) -> dict:
    if not contract_address or not contract_address.strip():
        raise ValueError("contract_address is required")

    response = requests.get(
        DEXSCREENER_TOKEN_URL.format(contract_address=contract_address.strip()),
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    pairs = payload.get("pairs") or []

    requested_chain = (chain or "").strip().lower()
    if requested_chain and requested_chain not in {"unknown", "auto", "any"}:
        matching_pairs = [
            pair for pair in pairs
            if str(pair.get("chainId", "")).lower() == requested_chain
        ]
        if not matching_pairs:
            return {
                "found": False,
                "contract_address": contract_address,
                "requested_chain": requested_chain,
                "reason": "chain_not_found",
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
        pairs = matching_pairs

    if not pairs:
        return {
            "found": False,
            "contract_address": contract_address,
            "requested_chain": requested_chain or None,
            "reason": "no_active_pair",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    requested_address = contract_address.strip()
    addressed_pairs = [
        pair
        for pair in pairs
        if (pair.get("baseToken") or {}).get("address")
        or (pair.get("quoteToken") or {}).get("address")
    ]
    base_pairs = [
        pair
        for pair in pairs
        if _same_address((pair.get("baseToken") or {}).get("address"), requested_address)
    ]
    if addressed_pairs and not base_pairs:
        return {
            "found": False,
            "contract_address": contract_address,
            "requested_chain": requested_chain or None,
            "reason": "token_not_base_token",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
    if base_pairs:
        pairs = base_pairs

    best_pair = max(
        pairs,
        key=lambda pair: _number((pair.get("liquidity") or {}).get("usd")) or 0,
    )
    base_token = best_pair.get("baseToken") or {}
    quote_token = best_pair.get("quoteToken") or {}
    liquidity = best_pair.get("liquidity") or {}
    volume = best_pair.get("volume") or {}
    price_change = best_pair.get("priceChange") or {}
    txns = (best_pair.get("txns") or {}).get("h24") or {}

    return {
        "found": True,
        "contract_address": contract_address,
        "token_name": base_token.get("name"),
        "token_symbol": base_token.get("symbol"),
        "chain": best_pair.get("chainId"),
        "dex": best_pair.get("dexId"),
        "pair_address": best_pair.get("pairAddress"),
        "quote_symbol": quote_token.get("symbol"),
        "price_usd": _number(best_pair.get("priceUsd")),
        "market_cap": _number(best_pair.get("marketCap")),
        "fdv": _number(best_pair.get("fdv")),
        "liquidity_usd": _number(liquidity.get("usd")),
        "volume_24h": _number(volume.get("h24")),
        "volume_6h": _number(volume.get("h6")),
        "volume_1h": _number(volume.get("h1")),
        "price_change_24h": _number(price_change.get("h24")),
        "price_change_6h": _number(price_change.get("h6")),
        "price_change_1h": _number(price_change.get("h1")),
        "buys_24h": _number(txns.get("buys")),
        "sells_24h": _number(txns.get("sells")),
        "pair_created_at": best_pair.get("pairCreatedAt"),
        "dex_url": best_pair.get("url"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
