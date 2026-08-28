import os
from abc import ABC, abstractmethod
from typing import List, Optional

import requests
from dotenv import load_dotenv


load_dotenv()


class WalletProvider(ABC):
    @abstractmethod
    def fetch_history(self, wallet_address: str, max_transactions: int = 500) -> List[dict]:
        raise NotImplementedError


class HeliusWalletProvider(WalletProvider):
    """Read-only Solana transaction history through Helius Enhanced Transactions."""

    BASE_URL = "https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("HELIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Add it as a secret or .env value.")

    def fetch_page(
        self,
        wallet_address: str,
        limit: int = 100,
        before_signature: Optional[str] = None,
    ) -> List[dict]:
        if not wallet_address or not wallet_address.strip():
            raise ValueError("wallet_address is required")
        limit = max(1, min(int(limit), 100))
        params = {
            "api-key": self.api_key,
            "limit": limit,
            "commitment": "finalized",
            "token-accounts": "balanceChanged",
            "sort-order": "desc",
        }
        if before_signature:
            params["before-signature"] = before_signature

        try:
            response = requests.get(
                self.BASE_URL.format(wallet_address=wallet_address.strip()),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            response_status = getattr(getattr(exc, "response", None), "status_code", None)
            status_note = f" with HTTP {response_status}" if response_status else ""
            raise RuntimeError(
                f"Helius wallet-history request failed{status_note}."
            ) from None
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("transactions"), list):
            return payload["transactions"]
        raise RuntimeError("Helius returned an unexpected wallet-history response")

    def fetch_history(self, wallet_address: str, max_transactions: int = 500) -> List[dict]:
        max_transactions = max(1, min(int(max_transactions), 10_000))
        transactions: List[dict] = []
        seen_signatures = set()
        before_signature = None

        while len(transactions) < max_transactions:
            page_limit = min(100, max_transactions - len(transactions))
            page = self.fetch_page(
                wallet_address=wallet_address,
                limit=page_limit,
                before_signature=before_signature,
            )
            if not page:
                break
            added = 0
            for transaction in page:
                signature = transaction.get("signature") or transaction.get("txHash")
                if signature and signature in seen_signatures:
                    continue
                if signature:
                    seen_signatures.add(signature)
                transactions.append(transaction)
                added += 1
                if len(transactions) >= max_transactions:
                    break
            if not added:
                break
            last_signature = page[-1].get("signature") or page[-1].get("txHash")
            if not last_signature or last_signature == before_signature:
                break
            before_signature = last_signature

        return transactions[:max_transactions]
