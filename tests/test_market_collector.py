from app.collectors import market


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_fetch_market_data_selects_highest_liquidity(monkeypatch):
    monkeypatch.setattr(
        market.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "pairs": [
                    {
                        "chainId": "base",
                        "liquidity": {"usd": 1000},
                        "baseToken": {"name": "Low", "symbol": "LOW"},
                        "quoteToken": {"symbol": "WETH"},
                    },
                    {
                        "chainId": "base",
                        "liquidity": {"usd": 5000},
                        "baseToken": {"name": "High", "symbol": "HIGH"},
                        "quoteToken": {"symbol": "WETH"},
                    },
                ]
            }
        ),
    )

    result = market.fetch_market_data("0xtest", requested_chain="base")

    assert result["found"] is True
    assert result["token_symbol"] == "HIGH"
    assert result["requested_chain"] == "base"


def test_fetch_market_data_honors_chain_alias(monkeypatch):
    monkeypatch.setattr(
        market.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "pairs": [
                    {
                        "chainId": "bsc",
                        "liquidity": {"usd": 5000},
                        "baseToken": {"name": "BNB Token", "symbol": "BNB"},
                        "quoteToken": {"symbol": "USDT"},
                    }
                ]
            }
        ),
    )

    result = market.fetch_market_data("0xtest", requested_chain="bnb")

    assert result["found"] is True
    assert result["chain"] == "bsc"


def test_fetch_market_data_reports_chain_miss(monkeypatch):
    monkeypatch.setattr(
        market.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {
                "pairs": [
                    {
                        "chainId": "solana",
                        "liquidity": {"usd": 5000},
                    }
                ]
            }
        ),
    )

    result = market.fetch_market_data("0xtest", requested_chain="base")

    assert result["found"] is False
    assert result["reason"] == "no_pair_on_requested_chain"
    assert result["available_chains"] == ["solana"]
