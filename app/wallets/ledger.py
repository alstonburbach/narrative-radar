from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WalletSwap:
    timestamp: str
    tx_hash: str
    token_address: str
    side: str
    token_amount: float
    quote_usd: float
    fee_usd: float = 0.0
    quote_asset: str = "USD"

    def __post_init__(self):
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if self.token_amount <= 0:
            raise ValueError("token_amount must be greater than zero")
        if self.quote_usd < 0 or self.fee_usd < 0:
            raise ValueError("quote_usd and fee_usd cannot be negative")
        if not self.quote_asset or not self.quote_asset.strip():
            raise ValueError("quote_asset is required")


@dataclass(frozen=True)
class WalletTransfer:
    timestamp: str
    tx_hash: str
    direction: str
    asset: str
    amount_usd: float
    external: bool = True

    def __post_init__(self):
        if self.direction not in {"in", "out"}:
            raise ValueError("direction must be 'in' or 'out'")
        if self.amount_usd < 0:
            raise ValueError("amount_usd cannot be negative")
