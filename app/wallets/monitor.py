from typing import Callable, Optional

from app.collectors.wallet_provider import WalletProvider
from app.wallets.analyzer import evaluate_normalized_activity
from app.wallets.normalizer import normalize_helius_transactions


def analyze_wallet(
    wallet_address: str,
    provider: WalletProvider,
    max_transactions: int = 500,
    quote_price_resolver: Optional[Callable] = None,
    min_closed_trades: int = 20,
) -> dict:
    transactions = provider.fetch_history(wallet_address, max_transactions=max_transactions)
    activity = normalize_helius_transactions(
        wallet_address=wallet_address,
        transactions=transactions,
        quote_price_resolver=quote_price_resolver,
    )
    report = evaluate_normalized_activity(activity, min_closed_trades=min_closed_trades)
    report["wallet_address"] = wallet_address
    report["transaction_count_fetched"] = len(transactions)
    report["execution_enabled"] = False
    return report
