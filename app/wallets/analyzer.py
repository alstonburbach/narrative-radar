from collections import defaultdict, deque
from datetime import datetime, timezone
from statistics import median
from typing import Iterable, List

from app.wallets.ledger import WalletSwap, WalletTransfer


USD_LIKE_ASSETS = {"USD", "USDC", "USDT", "DAI", "FDUSD"}


def _timestamp_datetime(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _month_key(value):
    parsed = _timestamp_datetime(value)
    return parsed.strftime("%Y-%m") if parsed else None


def _build_strategy_profile(
    records: list[dict],
    realized_pnl: float,
    matched_cost_basis: float,
) -> dict:
    """Summarize whether realized performance is distributed over time.

    This is deliberately not a portfolio-return calculation: open positions,
    mark-to-market gains, and unpriced assets are outside the profile.
    """
    if not records:
        return {
            "trade_count": 0,
            "active_days": 0,
            "observed_span_days": None,
            "observed_months": 0,
            "profitable_months": 0,
            "profitable_month_share_pct": None,
            "largest_profitable_month_share_pct": None,
            "realized_roi_on_matched_cost_basis_pct": None,
            "median_holding_days": None,
            "average_holding_days": None,
            "trades_per_30d": None,
            "timestamp_coverage_pct": 0.0,
            "monthly_realized_pnl": {},
            "style": "unknown",
        }

    month_pnl = defaultdict(float)
    active_days = set()
    dated = []
    holding_days = []
    for record in records:
        parsed = _timestamp_datetime(record.get("timestamp"))
        if parsed:
            dated.append(parsed)
            active_days.add(parsed.date().isoformat())
            month_pnl[parsed.strftime("%Y-%m")] += record["pnl"]
        if record.get("holding_days") is not None:
            holding_days.append(record["holding_days"])

    observed_months = len(month_pnl)
    profitable_months = sum(value > 0 for value in month_pnl.values())
    positive_month_pnl = [value for value in month_pnl.values() if value > 0]
    gross_monthly_profit = sum(positive_month_pnl)
    largest_profitable_month_share_pct = (
        round(max(positive_month_pnl) / gross_monthly_profit * 100, 2)
        if gross_monthly_profit
        else None
    )
    observed_span_days = None
    if len(dated) >= 2:
        observed_span_days = round(
            (max(dated) - min(dated)).total_seconds() / 86_400,
            2,
        )
    elapsed_days = max(observed_span_days or 0.0, 1.0)
    median_holding_days = round(median(holding_days), 2) if holding_days else None
    if median_holding_days is None:
        style = "unknown"
    elif median_holding_days <= 1:
        style = "intraday_or_scalping"
    elif median_holding_days <= 7:
        style = "short_swing"
    else:
        style = "swing_or_longer"

    return {
        "trade_count": len(records),
        "active_days": len(active_days),
        "observed_span_days": observed_span_days,
        "observed_months": observed_months,
        "profitable_months": profitable_months,
        "profitable_month_share_pct": (
            round(profitable_months / observed_months * 100, 2)
            if observed_months
            else None
        ),
        "largest_profitable_month_share_pct": largest_profitable_month_share_pct,
        "realized_roi_on_matched_cost_basis_pct": (
            round(realized_pnl / matched_cost_basis * 100, 2)
            if matched_cost_basis > 0
            else None
        ),
        "median_holding_days": median_holding_days,
        "average_holding_days": (
            round(sum(holding_days) / len(holding_days), 2)
            if holding_days
            else None
        ),
        "trades_per_30d": round(len(records) / elapsed_days * 30, 2),
        "timestamp_coverage_pct": round(len(dated) / len(records) * 100, 2),
        "monthly_realized_pnl": {
            month: round(value, 8)
            for month, value in sorted(month_pnl.items())
        },
        "style": style,
    }


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
    trade_pnls_by_asset = defaultdict(list)
    trade_records_by_asset = defaultdict(list)

    for swap in sorted(swaps, key=lambda item: item.timestamp):
        if swap.side == "buy":
            unit_cost = (swap.quote_usd + swap.fee_usd) / swap.token_amount
            lots[(swap.token_address, swap.quote_asset.upper())].append(
                [swap.token_amount, unit_cost, swap.timestamp]
            )
            continue

        remaining = swap.token_amount
        unit_proceeds = max(0.0, swap.quote_usd - swap.fee_usd) / swap.token_amount
        sell_pnl = 0.0
        sell_matched = 0.0
        sell_cost_basis = 0.0
        sell_proceeds = 0.0
        holding_days_total = 0.0
        holding_amount = 0.0
        asset = swap.quote_asset.upper()
        while remaining > 1e-12 and lots[(swap.token_address, asset)]:
            lot_amount, unit_cost, lot_timestamp = lots[(swap.token_address, asset)][0]
            matched_amount = min(remaining, lot_amount)
            cost = matched_amount * unit_cost
            proceeds = matched_amount * unit_proceeds
            matched_cost_basis_by_asset[asset] += cost
            matched_proceeds_by_asset[asset] += proceeds
            sell_pnl += proceeds - cost
            sell_matched += matched_amount
            sell_cost_basis += cost
            sell_proceeds += proceeds
            buy_time = _timestamp_datetime(lot_timestamp)
            sell_time = _timestamp_datetime(swap.timestamp)
            if buy_time and sell_time:
                holding_days_total += matched_amount * max(
                    0.0, (sell_time - buy_time).total_seconds() / 86_400
                )
                holding_amount += matched_amount
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
            trade_pnls_by_asset[asset].append(sell_pnl)
            trade_records_by_asset[asset].append(
                {
                    "timestamp": swap.timestamp,
                    "token_address": swap.token_address,
                    "pnl": sell_pnl,
                    "cost_basis": sell_cost_basis,
                    "proceeds": sell_proceeds,
                    "holding_days": (
                        holding_days_total / holding_amount
                        if holding_amount > 1e-12
                        else None
                    ),
                }
            )

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

    def trade_stats(values):
        if not values:
            return {
                "trade_count": 0,
                "median_trade_pnl": None,
                "average_trade_pnl": None,
                "average_win_pnl": None,
                "average_loss_pnl": None,
                "largest_win_share_pct": None,
                "top_3_win_share_pct": None,
            }
        wins_only = sorted((value for value in values if value > 0), reverse=True)
        losses_only = [value for value in values if value < 0]
        gross_wins = sum(wins_only)
        return {
            "trade_count": len(values),
            "median_trade_pnl": round(median(values), 8),
            "average_trade_pnl": round(sum(values) / len(values), 8),
            "average_win_pnl": round(sum(wins_only) / len(wins_only), 8) if wins_only else None,
            "average_loss_pnl": round(sum(losses_only) / len(losses_only), 8) if losses_only else None,
            "largest_win_share_pct": round(wins_only[0] / gross_wins * 100, 2) if gross_wins else None,
            "top_3_win_share_pct": round(sum(wins_only[:3]) / gross_wins * 100, 2) if gross_wins else None,
        }

    trade_stats_by_asset = {
        asset: trade_stats(values)
        for asset, values in trade_pnls_by_asset.items()
    }
    primary_trade_stats = (
        trade_stats_by_asset.get(primary_quote_asset)
        if primary_quote_asset
        else None
    )
    strategy_profile_by_asset = {
        asset: _build_strategy_profile(
            trade_records_by_asset[asset],
            realized_by_asset[asset],
            matched_cost_basis_by_asset[asset],
        )
        for asset in trade_records_by_asset
    }
    primary_strategy_profile = (
        strategy_profile_by_asset.get(primary_quote_asset)
        if primary_quote_asset
        else None
    )

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
        "trade_pnl_stats_by_quote_asset": trade_stats_by_asset,
        "trade_pnl_stats": primary_trade_stats,
        "strategy_profile_by_quote_asset": strategy_profile_by_asset,
        "strategy_profile": primary_strategy_profile,
    }


def calculate_external_flow(transfers: Iterable[WalletTransfer]) -> dict:
    external_in = 0.0
    external_out = 0.0
    inflow_sources = defaultdict(float)
    outflow_destinations = defaultdict(float)
    unknown_inflow_counterparties = 0
    unknown_outflow_counterparties = 0
    external_inflow_transfer_count = 0
    external_outflow_transfer_count = 0
    for transfer in transfers:
        if not transfer.external:
            continue
        if transfer.direction == "in":
            external_in += transfer.amount_usd
            external_inflow_transfer_count += 1
            counterparty = str(transfer.counterparty or "").strip()
            if counterparty:
                inflow_sources[counterparty] += transfer.amount_usd
            else:
                unknown_inflow_counterparties += 1
        else:
            external_out += transfer.amount_usd
            external_outflow_transfer_count += 1
            counterparty = str(transfer.counterparty or "").strip()
            if counterparty:
                outflow_destinations[counterparty] += transfer.amount_usd
            else:
                unknown_outflow_counterparties += 1

    def concentration(values, total):
        return round(max(values.values()) / total * 100, 2) if values and total else None

    return {
        "external_inflow_usd": round(external_in, 2),
        "external_outflow_usd": round(external_out, 2),
        "net_external_flow_usd": round(external_in - external_out, 2),
        "external_inflow_transfer_count": external_inflow_transfer_count,
        "external_outflow_transfer_count": external_outflow_transfer_count,
        "external_inflow_counterparty_count": len(inflow_sources),
        "external_outflow_counterparty_count": len(outflow_destinations),
        "unknown_inflow_counterparty_count": unknown_inflow_counterparties,
        "unknown_outflow_counterparty_count": unknown_outflow_counterparties,
        "largest_inflow_source_share_pct": concentration(inflow_sources, external_in),
        "largest_outflow_destination_share_pct": concentration(
            outflow_destinations, external_out
        ),
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
    strategy_profile = pnl.get("strategy_profile") or {}
    if pnl.get("matched_proceeds_usd"):
        flow["external_inflow_to_matched_proceeds_pct"] = round(
            flow["external_inflow_usd"] / pnl["matched_proceeds_usd"] * 100,
            2,
        )
    else:
        flow["external_inflow_to_matched_proceeds_pct"] = None
    if pnl.get("realized_pnl_usd") and pnl["realized_pnl_usd"] > 0:
        flow["external_inflow_to_realized_pnl_multiple"] = round(
            flow["external_inflow_usd"] / pnl["realized_pnl_usd"],
            2,
        )
    else:
        flow["external_inflow_to_realized_pnl_multiple"] = None

    flags = []
    if pnl["closed_trades"] < min_closed_trades:
        flags.append("insufficient_closed_trade_history")
    if profit_value is None or profit_value <= 0:
        flags.append("no_positive_realized_pnl")
    if any(value > 0 for value in pnl["unmatched_sell_value_by_quote_asset"].values()):
        flags.append("incomplete_cost_basis_or_inbound_tokens")
    if len(pnl["quote_assets"]) > 1:
        flags.append("mixed_quote_assets_require_conversion")
    trade_stats = pnl.get("trade_pnl_stats") or {}
    meaningful_trade_sample = pnl["closed_trades"] >= max(5, min_closed_trades)
    if meaningful_trade_sample and (
        (
            trade_stats.get("largest_win_share_pct") is not None
            and trade_stats["largest_win_share_pct"] > 75
        )
        or (
            trade_stats.get("top_3_win_share_pct") is not None
            and trade_stats["top_3_win_share_pct"] > 90
        )
    ):
        flags.append("profit_concentrated_in_few_trades")
    if (
        meaningful_trade_sample
        and strategy_profile.get("observed_span_days") is not None
        and strategy_profile["observed_span_days"] < 7
    ):
        flags.append("short_observation_window")
    if (
        meaningful_trade_sample
        and strategy_profile.get("observed_months", 0) >= 3
        and strategy_profile.get("largest_profitable_month_share_pct") is not None
        and strategy_profile["largest_profitable_month_share_pct"] > 75
    ):
        flags.append("profit_concentrated_in_few_periods")
    comparable_profit = abs(profit_value or 0)
    if flow["external_inflow_usd"] > 0 and pnl["primary_quote_asset"] not in USD_LIKE_ASSETS:
        flags.append("external_flows_require_quote_conversion")
    elif flow["external_inflow_usd"] > max(100.0, comparable_profit * 2):
        flags.append("external_inflows_are_large_relative_to_realized_pnl")
    if (
        pnl["primary_quote_asset"] in USD_LIKE_ASSETS
        and flow.get("external_inflow_counterparty_count") == 1
        and (flow.get("largest_inflow_source_share_pct") or 0) >= 90
        and flow["external_inflow_usd"] > max(
            1_000.0,
            abs(pnl.get("realized_pnl_usd") or 0) * 2,
        )
    ):
        flags.append("external_inflows_concentrated_in_one_source")

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
