from collections import defaultdict, deque
from typing import Iterable, List

from app.wallets.ledger import WalletSwap, WalletTransfer


def calculate_realized_pnl(swaps: Iterable[WalletSwap]) -> dict:
    """Match sells to FIFO buy lots and calculate realized USD PnL.

    The caller must provide swaps with quote values and fees normalized to USD.
    Inbound token transfers that are not represented as buys are intentionally
    reported as unmatched sells instead of being treated as free profit.
    """
    lots = defaultdict(deque)
    realized_pnl = 0.0
    matched_proceeds = 0.0
    matched_cost_basis = 0.0
    unmatched_sell_value = 0.0
    closed_trades = 0
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0

    for swap in sorted(swaps, key=lambda item: item.timestamp):
        if swap.side == "buy":
            unit_cost = (swap.quote_usd + swap.fee_usd) / swap.token_amount
            lots[swap.token_address].append([swap.token_amount, unit_cost])
            continue

        remaining = swap.token_amount
        unit_proceeds = max(0.0, swap.quote_usd - swap.fee_usd) / swap.token_amount
        sell_pnl = 0.0
        sell_matched = 0.0
        while remaining > 1e-12 and lots[swap.token_address]:
            lot_amount, unit_cost = lots[swap.token_address][0]
            matched_amount = min(remaining, lot_amount)
            cost = matched_amount * unit_cost
            proceeds = matched_amount * unit_proceeds
            matched_cost_basis += cost
            matched_proceeds += proceeds
            sell_pnl += proceeds - cost
            sell_matched += matched_amount
            remaining -= matched_amount
            lot_amount -= matched_amount
            if lot_amount <= 1e-12:
                lots[swap.token_address].popleft()
            else:
                lots[swap.token_address][0][0] = lot_amount

        if remaining > 1e-12:
            unmatched_sell_value += remaining * unit_proceeds
        if sell_matched > 1e-12:
            closed_trades += 1
            if sell_pnl > 0:
                wins += 1
                gross_profit += sell_pnl
            elif sell_pnl < 0:
                losses += 1
                gross_loss += abs(sell_pnl)
            realized_pnl += sell_pnl

    profit_factor = None
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)

    return {
        "realized_pnl_usd": round(realized_pnl, 2),
        "matched_proceeds_usd": round(matched_proceeds, 2),
        "matched_cost_basis_usd": round(matched_cost_basis, 2),
        "unmatched_sell_value_usd": round(unmatched_sell_value, 2),
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

    flags = []
    if pnl["closed_trades"] < min_closed_trades:
        flags.append("insufficient_closed_trade_history")
    if pnl["realized_pnl_usd"] <= 0:
        flags.append("no_positive_realized_pnl")
    if pnl["unmatched_sell_value_usd"] > 0:
        flags.append("incomplete_cost_basis_or_inbound_tokens")
    if flow["external_inflow_usd"] > max(100.0, pnl["realized_pnl_usd"] * 2):
        flags.append("external_inflows_are_large_relative_to_realized_pnl")

    quality = 0
    if pnl["closed_trades"] >= 50:
        quality += 25
    elif pnl["closed_trades"] >= min_closed_trades:
        quality += 15
    else:
        quality += 5
    if pnl["realized_pnl_usd"] > 0:
        quality += 25
    if pnl["win_rate_pct"] is not None and pnl["win_rate_pct"] >= 55:
        quality += 20
    elif pnl["win_rate_pct"] is not None:
        quality += 10
    if pnl["unmatched_sell_value_usd"] == 0:
        quality += 20
    else:
        quality += 5
    if flow["external_inflow_usd"] <= max(100.0, pnl["realized_pnl_usd"] * 2):
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
