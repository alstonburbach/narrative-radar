from app.wallets.analyzer import calculate_external_flow, calculate_realized_pnl, evaluate_wallet
from app.wallets.ledger import WalletSwap, WalletTransfer


def test_realized_pnl_uses_fifo_cost_basis():
    swaps = [
        WalletSwap("2026-01-01", "buy-1", "TOKEN", "buy", 10, 100),
        WalletSwap("2026-01-02", "sell-1", "TOKEN", "sell", 5, 75),
        WalletSwap("2026-01-03", "sell-2", "TOKEN", "sell", 5, 40),
    ]
    result = calculate_realized_pnl(swaps)
    assert result["realized_pnl_usd"] == 15
    assert result["closed_trades"] == 2
    assert result["unmatched_sell_value_usd"] == 0
    assert result["profit_factor"] == 2.5


def test_external_inflows_are_not_pnl():
    transfers = [
        WalletTransfer("2026-01-01", "in", "in", "USDC", 1_000),
        WalletTransfer("2026-01-02", "out", "out", "USDC", 200),
        WalletTransfer("2026-01-03", "self", "in", "USDC", 500, external=False),
    ]
    result = calculate_external_flow(transfers)
    assert result["external_inflow_usd"] == 1_000
    assert result["external_outflow_usd"] == 200
    assert result["net_external_flow_usd"] == 800


def test_wallet_with_short_history_is_not_copy_candidate():
    swaps = [
        WalletSwap("2026-01-01", "buy", "TOKEN", "buy", 10, 100),
        WalletSwap("2026-01-02", "sell", "TOKEN", "sell", 10, 150),
    ]
    result = evaluate_wallet(swaps)
    assert result["research_candidate"] is False
    assert "insufficient_closed_trade_history" in result["flags"]
    assert result["copy_trade_ready"] is False


def test_wallet_with_one_dominant_win_is_not_a_steady_research_candidate():
    swaps = []
    for index in range(19):
        swaps.extend(
            [
                WalletSwap(f"2026-01-{index + 1:02d}", f"buy-{index}", "TOKEN", "buy", 1, 10),
                WalletSwap(f"2026-02-{index + 1:02d}", f"sell-{index}", "TOKEN", "sell", 1, 11),
            ]
        )
    swaps.extend(
        [
            WalletSwap("2026-03-01", "buy-big", "TOKEN", "buy", 1, 10),
            WalletSwap("2026-03-02", "sell-big", "TOKEN", "sell", 1, 110),
        ]
    )

    result = evaluate_wallet(swaps)

    assert result["pnl"]["closed_trades"] == 20
    assert result["pnl"]["trade_pnl_stats"]["largest_win_share_pct"] > 75
    assert "profit_concentrated_in_few_trades" in result["flags"]
    assert result["research_candidate"] is False


def test_wallet_profile_rewards_profit_distributed_across_time():
    swaps = []
    for index in range(20):
        month = index // 7 + 1
        day = index % 7 + 1
        swaps.extend(
            [
                WalletSwap(
                    f"2026-{month:02d}-{day:02d}T00:00:00+00:00",
                    f"buy-{index}",
                    "TOKEN",
                    "buy",
                    1,
                    10,
                ),
                WalletSwap(
                    f"2026-{month:02d}-{day:02d}T12:00:00+00:00",
                    f"sell-{index}",
                    "TOKEN",
                    "sell",
                    1,
                    11,
                ),
            ]
        )

    result = evaluate_wallet(swaps)
    profile = result["pnl"]["strategy_profile"]

    assert result["research_candidate"] is True
    assert profile["observed_months"] == 3
    assert profile["profitable_months"] == 3
    assert profile["realized_roi_on_matched_cost_basis_pct"] == 10.0
    assert profile["max_realized_drawdown"] == 0.0
    assert profile["max_consecutive_losses"] == 0
    assert profile["style"] == "intraday_or_scalping"
    assert "profit_concentrated_in_few_periods" not in result["flags"]


def test_wallet_with_many_trades_in_one_short_window_is_not_steady():
    swaps = []
    for index in range(20):
        swaps.extend(
            [
                WalletSwap(
                    f"2026-01-01T00:{index:02d}:00+00:00",
                    f"buy-{index}",
                    "TOKEN",
                    "buy",
                    1,
                    10,
                ),
                WalletSwap(
                    f"2026-01-01T01:{index:02d}:00+00:00",
                    f"sell-{index}",
                    "TOKEN",
                    "sell",
                    1,
                    11,
                ),
            ]
        )

    result = evaluate_wallet(swaps)

    assert "short_observation_window" in result["flags"]
    assert result["research_candidate"] is False


def test_wallet_with_large_realized_drawdown_is_not_steady():
    swaps = []
    for index in range(20):
        day = index + 1
        sell_value = 2 if index < 13 else 25
        swaps.extend(
            [
                WalletSwap(
                    f"2026-01-{day:02d}T00:00:00+00:00",
                    f"buy-{index}",
                    "TOKEN",
                    "buy",
                    1,
                    10,
                ),
                WalletSwap(
                    f"2026-01-{day:02d}T12:00:00+00:00",
                    f"sell-{index}",
                    "TOKEN",
                    "sell",
                    1,
                    sell_value,
                ),
            ]
        )

    result = evaluate_wallet(swaps)
    profile = result["pnl"]["strategy_profile"]

    assert profile["max_realized_drawdown_on_matched_cost_basis_pct"] == 52.0
    assert "large_realized_drawdown" in result["flags"]
    assert result["research_candidate"] is False


def test_external_flow_tracks_known_counterparty_concentration():
    result = calculate_external_flow(
        [
            WalletTransfer("2026-01-01", "a", "in", "USD", 800, True, "source-a"),
            WalletTransfer("2026-01-02", "b", "in", "USD", 200, True, "source-b"),
            WalletTransfer("2026-01-03", "c", "out", "USD", 50, True, "destination"),
        ]
    )

    assert result["external_inflow_counterparty_count"] == 2
    assert result["largest_inflow_source_share_pct"] == 80.0
    assert result["external_outflow_counterparty_count"] == 1


def test_large_single_source_funding_is_flagged_separately_from_pnl():
    swaps = []
    for index in range(20):
        day = index + 1
        swaps.extend(
            [
                WalletSwap(
                    f"2026-01-{day:02d}T00:00:00+00:00",
                    f"buy-{index}",
                    "TOKEN",
                    "buy",
                    1,
                    10,
                ),
                WalletSwap(
                    f"2026-01-{day:02d}T12:00:00+00:00",
                    f"sell-{index}",
                    "TOKEN",
                    "sell",
                    1,
                    11,
                ),
            ]
        )

    result = evaluate_wallet(
        swaps,
        [
            WalletTransfer(
                "2026-01-01",
                "deposit",
                "in",
                "USD",
                5_000,
                True,
                "source-a",
            )
        ],
    )

    assert result["external_flow"]["largest_inflow_source_share_pct"] == 100.0
    assert "external_inflows_concentrated_in_one_source" in result["flags"]
    assert result["research_candidate"] is False
