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
                    "baseToken": {"address": "0xtest", "name": "Test", "symbol": "TEST"},
                    "quoteToken": {"symbol": "SOL"},
                    "liquidity": {"usd": 10_000},
                    "priceUsd": "0.01",
                    "marketCap": 100_000,
                },
                {
                    "chainId": "base",
                    "dexId": "uniswap",
                    "pairAddress": "base-pair",
                    "baseToken": {"address": "0xtest", "name": "Test", "symbol": "TEST"},
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


def test_fetch_market_data_ignores_pair_where_requested_token_is_only_quote(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "pairs": [
                    {
                        "chainId": "base",
                        "baseToken": {"address": "0xother", "name": "Other", "symbol": "OTHER"},
                        "quoteToken": {"address": "0xtest", "symbol": "TEST"},
                        "liquidity": {"usd": 1_000_000},
                        "priceUsd": "10",
                    },
                    {
                        "chainId": "base",
                        "baseToken": {"address": "0xtest", "name": "Test", "symbol": "TEST"},
                        "quoteToken": {"symbol": "USDC"},
                        "liquidity": {"usd": 10_000},
                        "priceUsd": "0.01",
                    },
                ]
            }

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    result = fetch_market_data("0xTeSt", chain="base")

    assert result["found"] is True
    assert result["pair_address"] is None
    assert result["token_symbol"] == "TEST"
    assert result["price_usd"] == 0.01


def test_fetch_market_data_fails_closed_when_all_addressed_pairs_mismatch(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "pairs": [
                    {
                        "chainId": "base",
                        "baseToken": {"address": "0xother", "name": "Other", "symbol": "OTHER"},
                        "quoteToken": {"address": "0xquote", "symbol": "Q"},
                        "liquidity": {"usd": 1_000_000},
                    }
                ]
            }

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())
    result = fetch_market_data("0xtest", chain="base")

    assert result["found"] is False
    assert result["reason"] == "token_not_base_token"
