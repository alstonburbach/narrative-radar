from app.wallets.analyzer import evaluate_normalized_activity
from app.wallets.normalizer import SOL_MINT, normalize_helius_transactions


WALLET = "Wallet111"
TOKEN = "Token111"


def swap_transaction(signature, timestamp, side):
    if side == "buy":
        event = {
            "nativeInput": {"amount": 1_000_000_000, "account": WALLET},
            "tokenOutputs": [
                {
                    "mint": TOKEN,
                    "rawTokenAmount": {"tokenAmount": "1000", "decimals": 0},
                    "toUserAccount": WALLET,
                }
            ],
        }
    else:
        event = {
            "tokenInputs": [
                {
                    "mint": TOKEN,
                    "rawTokenAmount": {"tokenAmount": "1000", "decimals": 0},
                    "fromUserAccount": WALLET,
                }
            ],
            "nativeOutput": {"amount": 2_000_000_000, "account": WALLET},
        }
    return {
        "signature": signature,
        "timestamp": timestamp,
        "type": "SWAP",
        "fee": 5_000,
        "events": {"swap": event},
    }


def test_normalizer_preserves_real_sol_pnl_without_fake_usd_conversion():
    activity = normalize_helius_transactions(
        WALLET,
        [swap_transaction("buy", 1, "buy"), swap_transaction("sell", 2, "sell")],
    )
    assert len(activity.swaps) == 2
    assert activity.swaps[0].quote_asset == "SOL"
    assert activity.swaps[0].quote_usd == 1
    assert activity.swaps[1].quote_usd == 2
    report = evaluate_normalized_activity(activity, min_closed_trades=1)
    assert report["pnl"]["primary_quote_asset"] == "SOL"
    assert report["pnl"]["primary_realized_pnl"] > 0
    assert report["pnl"]["realized_pnl_usd"] is None
    assert report["research_candidate"] is True


def test_normalizer_preserves_external_transfer_counterparty():
    transaction = {
        "signature": "transfer",
        "timestamp": 1,
        "type": "TRANSFER",
        "nativeTransfers": [
            {
                "amount": 1_000_000_000,
                "fromUserAccount": "Source111",
                "toUserAccount": WALLET,
            }
        ],
    }

    activity = normalize_helius_transactions(
        WALLET,
        [transaction],
        quote_price_resolver=lambda asset, timestamp: 100.0,
    )

    assert activity.transfers[0].counterparty == "Source111"


def stablecoin_buy_transaction(signature, fee=5_000):
    transaction = {
        "signature": signature,
        "timestamp": 1,
        "type": "SWAP",
        "events": {
            "swap": {
                "tokenInputs": [
                    {
                        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "rawTokenAmount": {
                            "tokenAmount": "100000000",
                            "decimals": 6,
                        },
                        "fromUserAccount": WALLET,
                    }
                ],
                "tokenOutputs": [
                    {
                        "mint": TOKEN,
                        "rawTokenAmount": {"tokenAmount": "1000", "decimals": 0},
                        "toUserAccount": WALLET,
                    }
                ],
            }
        },
    }
    if fee is not None:
        transaction["fee"] = fee
    return transaction


def test_usd_quoted_swap_does_not_silently_drop_unpriced_sol_fee():
    activity = normalize_helius_transactions(
        WALLET,
        [stablecoin_buy_transaction("buy")],
    )

    assert activity.swaps[0].quote_asset == "USD"
    assert activity.swaps[0].fee_usd == 0
    assert activity.unpriced_swap_fees == 1
    report = evaluate_normalized_activity(activity, min_closed_trades=0)
    assert "unpriced_or_missing_swap_fees" in report["flags"]
    assert report["research_candidate"] is False


def test_usd_quoted_swap_converts_sol_fee_with_historical_resolver():
    activity = normalize_helius_transactions(
        WALLET,
        [stablecoin_buy_transaction("buy")],
        quote_price_resolver=lambda asset, timestamp: 100.0,
    )

    assert activity.swaps[0].fee_usd == 0.0005
    assert activity.unpriced_swap_fees == 0


def test_missing_network_fee_is_reported_as_incomplete():
    transaction = swap_transaction("buy", 1, "buy")
    transaction.pop("fee")

    activity = normalize_helius_transactions(WALLET, [transaction])

    assert activity.unpriced_swap_fees == 1


def test_skipped_transaction_types_fail_closed_for_strategy_candidates():
    activity = normalize_helius_transactions(
        WALLET,
        [
            swap_transaction("buy", 1, "buy"),
            {"signature": "unknown", "timestamp": 2, "type": "NFT_SALE"},
        ],
    )

    assert activity.skipped_transactions == 1
    assert activity.to_dict()["normalized_transaction_coverage_pct"] == 50.0
    assert any("not recognized" in warning for warning in activity.warnings)
    report = evaluate_normalized_activity(activity, min_closed_trades=0)
    assert "skipped_transaction_types" in report["flags"]
    assert report["research_candidate"] is False
