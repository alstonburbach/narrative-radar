from app.collectors.market import fetch_market_data


def scout_token(contract_address: str, chain: str = "unknown") -> dict:
    """Fetch the normalized live market snapshot used by the pipeline."""
    return fetch_market_data(
        contract_address,
        chain=None if chain.lower() in {"unknown", "auto", "any"} else chain,
    )
