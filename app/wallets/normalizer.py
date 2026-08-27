from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional

from app.wallets.ledger import WalletSwap, WalletTransfer


SOL_MINT = "So11111111111111111111111111111111111111112"
SOL_ASSET = "SOL"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USD_LIKE_MINTS = {USDC_MINT: "USD"}
USD_LIKE_SYMBOLS = {"USD", "USDC", "USDT", "DAI"}


@dataclass
class NormalizedWalletActivity:
    swaps: List[WalletSwap]
    transfers: List[WalletTransfer]
    transaction_count: int
    skipped_transactions: int = 0
    unpriced_swaps: int = 0
    unpriced_swap_fees: int = 0
    unpriced_transfers: int = 0
    warnings: List[str] = None
    source: str = "helius"

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "transaction_count": self.transaction_count,
            "normalized_swaps": len(self.swaps),
            "normalized_transfers": len(self.transfers),
            "skipped_transactions": self.skipped_transactions,
            "unpriced_swaps": self.unpriced_swaps,
            "unpriced_swap_fees": self.unpriced_swap_fees,
            "unpriced_transfers": self.unpriced_transfers,
            "warnings": list(self.warnings),
        }


def _number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _timestamp(transaction: dict) -> str:
    value = transaction.get("timestamp")
    if value is None:
        value = transaction.get("blockTime")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if value:
        return str(value)
    return "1970-01-01T00:00:00+00:00"


def _signature(transaction: dict) -> str:
    return str(transaction.get("signature") or transaction.get("txHash") or "unknown")


def _mint(entry: dict) -> Optional[str]:
    return (
        entry.get("mint")
        or entry.get("tokenMint")
        or entry.get("token_address")
        or entry.get("asset")
    )


def _asset_for_mint(mint: Optional[str], symbol: Optional[str] = None) -> Optional[str]:
    if not mint or str(mint).upper() in {"SOL", "WSOL", SOL_MINT.upper()}:
        return SOL_ASSET
    if mint in USD_LIKE_MINTS:
        return USD_LIKE_MINTS[mint]
    symbol = str(symbol or mint).upper()
    if symbol in USD_LIKE_SYMBOLS:
        return "USD"
    return None


def _quantity(entry: dict, native: bool = False) -> Optional[float]:
    if native:
        amount = _number(entry.get("amount"))
        return amount / 1_000_000_000 if amount is not None else None

    raw = entry.get("rawTokenAmount")
    if isinstance(raw, dict):
        amount = raw.get("tokenAmount")
        decimals = raw.get("decimals", entry.get("decimals", 0))
    else:
        amount = raw if raw is not None else entry.get("amount")
        decimals = entry.get("decimals", 0)
    amount = _number(amount)
    decimals = _number(decimals)
    if amount is None or decimals is None:
        return None
    return amount / (10 ** int(decimals))


def _accounts(entry: dict) -> set:
    values = []
    for key in (
        "account",
        "userAccount",
        "fromUserAccount",
        "toUserAccount",
        "from",
        "to",
    ):
        value = entry.get(key)
        if value:
            values.append(str(value))
    return set(values)


def _belongs_to_wallet(entry: dict, wallet_address: str) -> bool:
    accounts = _accounts(entry)
    return not accounts or wallet_address in accounts


def _legs(swap: dict, wallet_address: str) -> tuple:
    spent = []
    received = []

    native_input = swap.get("nativeInput")
    if isinstance(native_input, dict) and _belongs_to_wallet(native_input, wallet_address):
        quantity = _quantity(native_input, native=True)
        if quantity:
            spent.append((SOL_ASSET, SOL_MINT, quantity))
    native_output = swap.get("nativeOutput")
    if isinstance(native_output, dict) and _belongs_to_wallet(native_output, wallet_address):
        quantity = _quantity(native_output, native=True)
        if quantity:
            received.append((SOL_ASSET, SOL_MINT, quantity))

    for entry in swap.get("tokenInputs") or []:
        if _belongs_to_wallet(entry, wallet_address):
            quantity = _quantity(entry)
            mint = _mint(entry)
            if quantity and mint:
                spent.append((_asset_for_mint(mint, entry.get("symbol") or entry.get("tokenSymbol")) or mint, mint, quantity))
    for entry in swap.get("tokenOutputs") or []:
        if _belongs_to_wallet(entry, wallet_address):
            quantity = _quantity(entry)
            mint = _mint(entry)
            if quantity and mint:
                received.append((_asset_for_mint(mint, entry.get("symbol") or entry.get("tokenSymbol")) or mint, mint, quantity))
    return spent, received


def _normalize_swap(
    transaction: dict,
    wallet_address: str,
    quote_price_resolver: Optional[Callable[[str, str], Optional[float]]] = None,
) -> tuple[Optional[WalletSwap], bool]:
    event = (transaction.get("events") or {}).get("swap")
    if not isinstance(event, dict):
        return None, False
    spent, received = _legs(event, wallet_address)
    if not spent or not received:
        return None, False

    quote_in = next((leg for leg in spent if leg[0] in {SOL_ASSET, "USD"}), None)
    target_out = next((leg for leg in received if leg[0] not in {SOL_ASSET, "USD"}), None)
    side = "buy"
    target = target_out
    quote = quote_in
    if target is None or quote is None:
        target_in = next((leg for leg in spent if leg[0] not in {SOL_ASSET, "USD"}), None)
        quote_out = next((leg for leg in received if leg[0] in {SOL_ASSET, "USD"}), None)
        if target_in is None or quote_out is None:
            return None, False
        side = "sell"
        target = target_in
        quote = quote_out

    asset, _, quote_quantity = quote
    timestamp = _timestamp(transaction)
    quote_value = quote_quantity
    quote_asset = asset
    fee_lamports = _number(transaction.get("fee"))
    fee_complete = fee_lamports is not None
    network_fee_sol = (fee_lamports or 0.0) / 1_000_000_000
    fee = 0.0

    if asset == SOL_ASSET:
        fee = network_fee_sol
        if quote_price_resolver is not None:
            price = quote_price_resolver(SOL_ASSET, timestamp)
            if price is not None:
                quote_value = quote_quantity * price
                fee *= price
                quote_asset = "USD"
    elif asset == "USD" and network_fee_sol > 0:
        fee_price = (
            quote_price_resolver(SOL_ASSET, timestamp)
            if quote_price_resolver is not None
            else None
        )
        if fee_price is None:
            fee_complete = False
        else:
            fee = network_fee_sol * fee_price

    if asset not in {SOL_ASSET, "USD"}:
        return None, False

    return (
        WalletSwap(
            timestamp=timestamp,
            tx_hash=_signature(transaction),
            token_address=target[1],
            side=side,
            token_amount=target[2],
            quote_usd=quote_value,
            fee_usd=fee,
            quote_asset=quote_asset,
        ),
        fee_complete,
    )


def _normalize_transfers(
    transaction: dict,
    wallet_address: str,
    quote_price_resolver: Optional[Callable[[str, str], Optional[float]]],
) -> tuple:
    transfers = []
    unpriced = 0
    timestamp = _timestamp(transaction)
    signature = _signature(transaction)

    for entry in transaction.get("nativeTransfers") or []:
        quantity = _quantity(entry, native=True)
        if not quantity:
            continue
        from_account = entry.get("fromUserAccount")
        to_account = entry.get("toUserAccount")
        direction = "in" if to_account == wallet_address else "out" if from_account == wallet_address else None
        if direction is None:
            continue
        price = quote_price_resolver(SOL_ASSET, timestamp) if quote_price_resolver else None
        if price is None:
            unpriced += 1
            continue
        counterparty = from_account if direction == "in" else to_account
        transfers.append(
            WalletTransfer(
                timestamp,
                signature,
                direction,
                SOL_ASSET,
                quantity * price,
                counterparty=counterparty,
            )
        )

    for entry in transaction.get("tokenTransfers") or []:
        mint = _mint(entry)
        quantity = _quantity(entry)
        if not mint or not quantity:
            continue
        from_account = entry.get("fromUserAccount")
        to_account = entry.get("toUserAccount")
        direction = "in" if to_account == wallet_address else "out" if from_account == wallet_address else None
        if direction is None:
            continue
        asset = _asset_for_mint(mint, entry.get("symbol") or entry.get("tokenSymbol"))
        price = 1.0 if asset == "USD" else (
            quote_price_resolver(mint, timestamp) if quote_price_resolver else None
        )
        if price is None:
            unpriced += 1
            continue
        counterparty = from_account if direction == "in" else to_account
        transfers.append(
            WalletTransfer(
                timestamp,
                signature,
                direction,
                asset or mint,
                quantity * price,
                counterparty=counterparty,
            )
        )
    return transfers, unpriced


def normalize_helius_transactions(
    wallet_address: str,
    transactions: Iterable[dict],
    quote_price_resolver: Optional[Callable[[str, str], Optional[float]]] = None,
) -> NormalizedWalletActivity:
    swaps = []
    transfers = []
    skipped_transactions = 0
    unpriced_swaps = 0
    unpriced_swap_fees = 0
    unpriced_transfers = 0
    warnings = []
    items = list(transactions)

    for transaction in items:
        transaction_type = str(transaction.get("type") or "").upper()
        if transaction_type == "SWAP":
            swap, fee_complete = _normalize_swap(
                transaction, wallet_address, quote_price_resolver
            )
            if swap is None:
                unpriced_swaps += 1
            else:
                swaps.append(swap)
                if not fee_complete:
                    unpriced_swap_fees += 1
        elif transaction_type == "TRANSFER":
            normalized, unpriced = _normalize_transfers(
                transaction, wallet_address, quote_price_resolver
            )
            transfers.extend(normalized)
            unpriced_transfers += unpriced
        else:
            skipped_transactions += 1

    if unpriced_swaps:
        warnings.append("Some swaps lacked a complete SOL/token leg and were excluded.")
    if unpriced_swap_fees:
        warnings.append(
            "Some swap network fees were missing or lacked a compatible historical quote price."
        )
    if unpriced_transfers:
        warnings.append("Some transfers lacked a historical USD price and were excluded from cash-flow totals.")
    return NormalizedWalletActivity(
        swaps=swaps,
        transfers=transfers,
        transaction_count=len(items),
        skipped_transactions=skipped_transactions,
        unpriced_swaps=unpriced_swaps,
        unpriced_swap_fees=unpriced_swap_fees,
        unpriced_transfers=unpriced_transfers,
        warnings=warnings,
    )
