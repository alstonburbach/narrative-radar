from collections import defaultdict, deque
from typing import Iterable, List

from app.wallets.ledger import WalletSwap, WalletTransfer


USD_LIKE_ASSETS = {"USD", "USDC", "USDT", "DAI", "FDUSD"}


def calculate_realized_pnl(swaps: Iterable[WalletSwap]) -> dict:
    """Match sells to FIFO buy lots and calculate realized quote-asset PnL.

    The caller must provide swaps with quote values and fees in the declared
    quote asset. USD-like quotes are also aggregated into the USD fields.
    Inbound token transfers that are not represented as buys are intentionally
    reported as unmatched sells instead of being treated as free profit.
    """
    lots = defaultdict(deque)
    realized_by_asset = defaultdict(float)
    matched_proceeds_by_asset = defaultdict(float)
    matched_cost_basis_by_asset = defaultdict(float)
    unmatched_sell_by_asset = defaultdict(float)
    closed_trades = 0
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0

    for swap in sorted(swaps, key=lambda item: item.timestamp):
        if swap.side == "buy":
            unit_cost = (swap.quote_usd + swap.fee_usd) / swap.token_amount
            lots[(swap.token_address, swap.quote_asset.upper())].append(
                [swap.token_amount, unit_cost]
            )
            continue

        remaining = swap.token_amount
        unit_proceeds = max(0.0, swap.quote_usd - swap.fee_usd) / swap.token_amount
        sell_pnl = 0.0
        sell_matched = 0.0
        asset = swap.quote_asset.upper()
        while remaining > 1e-12 and lots[(swap.token_address, asset)]:
            lot_amount, unit_cost = lots[(swap.token_address, asset)][0]
            matched_amount = min(remaining, lot_amount)
            cost = matched_amount * unit_cost
            proceeds = matched_amount * unit_proceeds
            matched_cost_basis_by_asset[asset] += cost
            matched_proceeds_by_asset[asset] += proceeds
            sell_pnl += proceeds - cost
            sell_matched += matched_amount
            remaining -= matched_amount
            lot_amount -= matched_amount
            if lot_amount <= 1e-12:
                lots[(swap.token_address, asset)].popleft()
            else:
                lots[(swap.token_address, asset)][0][0] = lot_amount

        if remaining > 1e-12:
            unmatched_sell_by_asset[asset] += remaining * unit_proceeds
        if sell_matched > 1e-12:
            closed_trades += 1
            if sell_pnl > 0:
                wins += 1
                gross_profit += sell_pnl
            elif sell_pnl < 0:
                losses += 1
                gross_loss += abs(sell_pnl)
            realized_by_asset[asset] += sell_pnl

    quote_assets = sorted(
        set(realized_by_asset)
        | set(matched_proceeds_by_asset)
        | set(matched_cost_basis_by_asset)
        | set(unmatched_sell_by_asset)
    )
    primary_quote_asset = quote_assets[0] if len(quote_assets) == 1 else None
    primary_realized_pnl = (
        round(realized_by_asset[primary_quote_asset], 8)
        if primary_quote_asset
        else None
    )
    usd_assets = [asset for asset in quote_assets if asset in USD_LIKE_ASSETS]
    realized_pnl_usd = (
        round(sum(realized_by_asset[asset] for asset in usd_assets), 2)
        if usd_assets
        else None
    )
    matched_proceeds_usd = (
        round(sum(matched_proceeds_by_asset[asset] for asset in usd_assets), 2)
        if usd_assets
        else None
    )
    matched_cost_basis_usd = (
        round(sum(matched_cost_basis_by_asset[asset] for asset in usd_assets), 2)
        if usd_assets
        else None
    )
    unmatched_sell_value_usd = (
        round(sum(unmatched_sell_by_asset[asset] for asset in usd_assets), 2)
        if usd_assets
        else None
    )
    profit_factor = None
    if primary_quote_asset and primary_quote_asset == "USD" and gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)

    return {
        "realized_pnl_usd": realized_pnl_usd,
        "realized_pnl_by_quote_asset": {
            asset: round(value, 8) for asset, value in realized_by_asset.items()
        },
        "primary_realized_pnl": primary_realized_pnl,
        "primary_quote_asset": primary_quote_asset,
        "matched_proceeds_usd": matched_proceeds_usd,
        "matched_cost_basis_usd": matched_cost_basis_usd,
        "unmatched_sell_value_usd": unmatched_sell_value_usd,
        "matched_proceeds_by_quote_asset": {
            asset: round(value, 8)
            for asset, value in matched_proceeds_by_asset.items()
        },
        "matched_cost_basis_by_quote_asset": {
            asset: round(value, 8)
            for asset, value in matched_cost_basis_by_asset.items()
        },
        "unmatched_sell_value_by_quote_asset": {
            asset: round(value, 8)
            for asset, value in unmatched_sell_by_asset.items()
        },
        "quote_assets": quote_assets,
        "closed_trades": closed_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round((wins / closed_trades) * 100, 2) if closed_trades else None,
        "profit_factor": profit_factor,
    }


def calculate_external_flow(transfers: Iterable[WalletTransfer]) -> dict:
    external_in = 0.0
    external_out = 0.0
    for transfer in transfers:
        if not transfer.external:
            continue
        if transfer.direction == "in":
            external_in += transfer.amount_usd
        else:
            external_out += transfer.amount_usd
    return {
        "external_inflow_usd": round(external_in, 2),
        "external_outflow_usd": round(external_out, 2),
        "net_external_flow_usd": round(external_in - external_out, 2),
    }


def evaluate_wallet(
    swaps: Iterable[WalletSwap],
    transfers: Iterable[WalletTransfer] = (),
    min_closed_trades: int = 20,
) -> dict:
    swap_items: List[WalletSwap] = list(swaps)
    transfer_items = list(transfers)
    pnl = calculate_realized_pnl(swap_items)
    flow = calculate_external_flow(transfer_items)
    primary_pnl = pnl["primary_realized_pnl"]
    profit_value = primary_pnl if primary_pnl is not None else pnl["realized_pnl_usd"]

    flags = []
    if pnl["closed_trades"] < min_closed_trades:
        flags.append("insufficient_closed_trade_history")
    if profit_value is None or profit_value <= 0:
        flags.append("no_positive_realized_pnl")
    if any(value > 0 for value in pnl["unmatched_sell_value_by_quote_asset"].values()):
        flags.append("incomplete_cost_basis_or_inbound_tokens")
    if len(pnl["quote_assets"]) > 1:
        flags.append("mixed_quote_assets_require_conversion")
    comparable_profit = abs(profit_value or 0)
    if flow["external_inflow_usd"] > 0 and pnl["primary_quote_asset"] not in USD_LIKE_ASSETS:
        flags.append("external_flows_require_quote_conversion")
    elif flow["external_inflow_usd"] > max(100.0, comparable_profit * 2):
        flags.append("external_inflows_are_large_relative_to_realized_pnl")

    quality = 0
    if pnl["closed_trades"] >= 50:
        quality += 25
    elif pnl["closed_trades"] >= min_closed_trades:
        quality += 15
    else:
        quality += 5
    if profit_value is not None and profit_value > 0:
        quality += 25
    if pnl["win_rate_pct"] is not None and pnl["win_rate_pct"] >= 55:
        quality += 20
    elif pnl["win_rate_pct"] is not None:
        quality += 10
    if not any(value > 0 for value in pnl["unmatched_sell_value_by_quote_asset"].values()):
        quality += 20
    else:
        quality += 5
    flows_comparable = (
        pnl["primary_quote_asset"] in USD_LIKE_ASSETS
        or flow["external_inflow_usd"] == 0
    )
    if flows_comparable and flow["external_inflow_usd"] <= max(100.0, comparable_profit * 2):
        quality += 10

    qualifies = not flags and quality >= 60
    return {
        "quality_score": min(100, quality),
        "research_candidate": qualifies,
        "copy_trade_ready": False,
        "flags": flags,
        "pnl": pnl,
        "external_flow": flow,
        "note": "A candidate still requires latency, slippage, liquidity, and multi-wallet checks before any copy-trading decision.",
    }


def evaluate_normalized_activity(activity, min_closed_trades: int = 20) -> dict:
    """Evaluate normalized wallet activity and downgrade incomplete ingestion."""
    report = evaluate_wallet(
        swaps=activity.swaps,
        transfers=activity.transfers,
        min_closed_trades=min_closed_trades,
    )
    ingestion_flags = []
    if activity.unpriced_swaps:
        ingestion_flags.append("unpriced_or_unrecognized_swaps")
    if activity.unpriced_transfers:
        ingestion_flags.append("unpriced_or_unrecognized_transfers")
    if ingestion_flags:
        report["flags"].extend(ingestion_flags)
        report["research_candidate"] = False
    report["ingestion"] = activity.to_dict()
    return report
