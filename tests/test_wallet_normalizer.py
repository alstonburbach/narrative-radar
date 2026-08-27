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
