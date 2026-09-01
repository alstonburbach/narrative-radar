from datetime import datetime, timezone

from app.collectors.venue_discovery import DexScreenerVenueProvider


ROBINHOOD = "0x1111111111111111111111111111111111111111"
PUMP = "9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, profiles, pairs):
        self.profiles = profiles
        self.pairs = pairs
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/token-profiles/latest/v1"):
            return Response(self.profiles)
        if "/tokens/v1/robinhood/" in url:
            return Response(self.pairs.get("robinhood", []))
        if "/tokens/v1/solana/" in url:
            return Response(self.pairs.get("solana", []))
        raise AssertionError(f"unexpected URL: {url}")


def _pair(
    chain,
    address,
    *,
    dex,
    created_at,
    drawdown=2,
    hour_change=10,
    buys=55,
    sells=10,
):
    return {
        "chainId": chain,
        "dexId": dex,
        "url": f"https://dexscreener.com/{chain}/pair",
        "pairAddress": f"{chain}-pair",
        "baseToken": {"address": address, "name": "Test", "symbol": "TEST"},
        "quoteToken": {"symbol": "WETH" if chain == "robinhood" else "SOL"},
        "priceUsd": "0.0001",
        "marketCap": 100_000,
        "fdv": 100_000,
        "liquidity": {"usd": 20_000},
        "volume": {"h1": 15_000, "h6": 20_000, "h24": 20_000},
        "txns": {"h1": {"buys": buys, "sells": sells}},
        "priceChange": {"m5": drawdown, "h1": hour_change, "h6": 10},
        "pairCreatedAt": created_at,
    }


def test_venue_collector_keeps_exact_robinhood_and_pumpfun_contracts():
    observed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    created = int(datetime(2026, 9, 1, 11, 54, tzinfo=timezone.utc).timestamp() * 1000)
    profiles = [
        {
            "chainId": "robinhood",
            "tokenAddress": ROBINHOOD,
            "url": f"https://dexscreener.com/robinhood/{ROBINHOOD}",
            "links": [{"type": "twitter", "url": "https://x.com/test"}],
        },
        {
            "chainId": "solana",
            "tokenAddress": PUMP,
            "url": f"https://dexscreener.com/solana/{PUMP}",
        },
        {
            "chainId": "solana",
            "tokenAddress": "DmkQo9iBz5wKexPj3JsUTmib5LY24SLdd8YZKMojcXoa",
        },
        {"chainId": "base", "tokenAddress": ROBINHOOD},
    ]
    pairs = {
        "robinhood": [
            _pair("robinhood", ROBINHOOD, dex="uniswap", created_at=created)
        ],
        "solana": [_pair("solana", PUMP, dex="pumpswap", created_at=created)],
    }

    report = DexScreenerVenueProvider(
        session=Session(profiles, pairs)
    ).collect(observed_at=observed)

    assert report["eligible_profiles"] == 2
    assert report["candidate_count"] == 2
    by_venue = {item["venue"]: item for item in report["candidates"]}
    assert by_venue["robinhood_chain"]["contract_address"] == ROBINHOOD
    assert by_venue["robinhood_chain"]["venue_confidence"] == "chain_confirmed"
    assert by_venue["pump_fun"]["contract_address"] == PUMP
    assert by_venue["pump_fun"]["venue_confidence"] == "launch_dex_confirmed"
    assert all(
        item["market_screen"]["status"] == "research_next"
        for item in report["candidates"]
    )
    assert by_venue["pump_fun"]["pair_age_minutes"] == 6


def test_venue_collector_blocks_profile_without_pair_and_fast_drawdown():
    observed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    created = int(datetime(2026, 9, 1, 11, 54, tzinfo=timezone.utc).timestamp() * 1000)
    second = "0x2222222222222222222222222222222222222222"
    profiles = [
        {"chainId": "robinhood", "tokenAddress": ROBINHOOD},
        {"chainId": "robinhood", "tokenAddress": second},
    ]
    pairs = {
        "robinhood": [
            _pair(
                "robinhood",
                ROBINHOOD,
                dex="uniswap",
                created_at=created,
                drawdown=-45,
            )
        ]
    }

    report = DexScreenerVenueProvider(
        session=Session(profiles, pairs)
    ).collect(observed_at=observed)
    by_address = {item["contract_address"]: item for item in report["candidates"]}

    assert "rapid_five_minute_drawdown" in by_address[ROBINHOOD]["market_screen"]["blockers"]
    assert by_address[second]["market_screen"]["blockers"] == ["no_active_pair"]
    assert all(
        item["market_screen"]["status"] == "blocked_market_risk"
        for item in report["candidates"]
    )


def test_active_pumpfun_bonding_curve_can_advance_without_fake_liquidity():
    observed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    created = int(datetime(2026, 9, 1, 11, 54, tzinfo=timezone.utc).timestamp() * 1000)
    pair = _pair("solana", PUMP, dex="pumpfun", created_at=created)
    pair["liquidity"] = {}
    pair["txns"]["h1"] = {"buys": 100, "sells": 40}
    profiles = [{"chainId": "solana", "tokenAddress": PUMP}]

    report = DexScreenerVenueProvider(
        session=Session(profiles, {"solana": [pair]})
    ).collect(observed_at=observed)
    candidate = report["candidates"][0]

    assert candidate["market_structure"] == "pump_fun_bonding_curve"
    assert candidate["liquidity_usd"] is None
    assert candidate["market_screen"]["status"] == "research_next"
    assert "missing_liquidity" not in candidate["market_screen"]["blockers"]
    assert any(
        "bonding curve" in caution
        for caution in candidate["market_screen"]["cautions"]
    )


def test_venue_collector_blocks_old_launches_and_demotes_sell_led_pairs():
    observed = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    old_created = int(
        datetime(2026, 9, 1, 11, 47, tzinfo=timezone.utc).timestamp() * 1000
    )
    fresh_created = int(
        datetime(2026, 9, 1, 11, 54, tzinfo=timezone.utc).timestamp() * 1000
    )
    second = "0x2222222222222222222222222222222222222222"
    profiles = [
        {"chainId": "robinhood", "tokenAddress": ROBINHOOD},
        {"chainId": "robinhood", "tokenAddress": second},
    ]
    pairs = {
        "robinhood": [
            _pair(
                "robinhood",
                ROBINHOOD,
                dex="uniswap",
                created_at=old_created,
            ),
            _pair(
                "robinhood",
                second,
                dex="uniswap",
                created_at=fresh_created,
                buys=40,
                sells=60,
            ),
        ]
    }

    report = DexScreenerVenueProvider(
        session=Session(profiles, pairs)
    ).collect(observed_at=observed)
    by_address = {item["contract_address"]: item for item in report["candidates"]}

    assert (
        "outside_early_launch_window"
        in by_address[ROBINHOOD]["market_screen"]["blockers"]
    )
    assert (
        by_address[ROBINHOOD]["market_screen"]["status"]
        == "blocked_market_risk"
    )
    assert (
        by_address[second]["market_screen"]["status"]
        == "watch_for_confirmation"
    )
    assert any(
        "buy flow" in caution
        for caution in by_address[second]["market_screen"]["cautions"]
    )
