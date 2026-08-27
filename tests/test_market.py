from app.collectors.market import fetch_market_data


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "pairs": [
                {
                    "chainId": "solana",
                    "dexId": "raydium",
                    "pairAddress": "sol-pair",
                    "baseToken": {"name": "Test", "symbol": "TEST"},
                    "quoteToken": {"symbol": "SOL"},
                    "liquidity": {"usd": 10_000},
                    "priceUsd": "0.01",
                    "marketCap": 100_000,
                },
                {
                    "chainId": "base",
                    "dexId": "uniswap",
                    "pairAddress": "base-pair",
                    "baseToken": {"name": "Test", "symbol": "TEST"},
                    "quoteToken": {"symbol": "WETH"},
                    "liquidity": {"usd": 20_000},
                    "priceUsd": "0.02",
                    "marketCap": 200_000,
                },
            ]
        }


def test_fetch_market_data_respects_requested_chain(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    result = fetch_market_data("0xtest", chain="solana")
    assert result["chain"] == "solana"
    assert result["pair_address"] == "sol-pair"
    assert result["market_cap"] == 100_000
