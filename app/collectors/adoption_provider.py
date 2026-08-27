import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

import requests
from dotenv import load_dotenv


load_dotenv()


SOLANA_CHAINS = {"solana", "solana-mainnet", "mainnet-beta"}
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/"


def is_solana_chain(chain: str) -> bool:
    return str(chain or "").strip().lower() in SOLANA_CHAINS


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> Optional[int]:
    number = _number(value)
    return int(number) if number is not None else None


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass
class OnchainActivitySnapshot:
    """A bounded snapshot of token ownership and transfer activity.

    These fields are intentionally descriptive rather than a token score. Raw
    holder and transfer counts can include pools, routers, bots, exchanges,
    airdrop recipients, and other non-user addresses.
    """

    token_address: str
    chain: str
    observed_at: str
    status: str = "pending"
    source: str = "helius"
    holder_count: Optional[int] = None
    holder_count_is_lower_bound: bool = False
    token_account_count: Optional[int] = None
    holder_scan_total: Optional[int] = None
    holder_scan_returned: int = 0
    holder_scan_complete: Optional[bool] = None
    scanned_token_amount_raw: Optional[str] = None
    scanned_supply_coverage_pct: Optional[float] = None
    largest_scanned_owner_share_pct: Optional[float] = None
    top_10_scanned_owner_share_pct: Optional[float] = None
    holder_concentration_is_lower_bound: bool = False
    last_indexed_slot: Optional[int] = None
    token_supply: Optional[float] = None
    token_supply_raw: Optional[str] = None
    token_decimals: Optional[int] = None
    activity_window_hours: int = 24
    transfer_transaction_count_24h: Optional[int] = None
    transfer_event_count_24h: Optional[int] = None
    unique_active_wallets_24h: Optional[int] = None
    unique_inflow_wallets_24h: Optional[int] = None
    unique_outflow_wallets_24h: Optional[int] = None
    transfer_scan_returned: int = 0
    transfer_scan_limit: Optional[int] = None
    transfer_scan_truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = (
        "On-chain activity proxies are not proof of human users or product adoption; "
        "review pools, routers, bots, exchanges, airdrops, and scan coverage."
    )

    def to_dict(self) -> dict:
        return asdict(self)


class AdoptionProvider(ABC):
    @abstractmethod
    def fetch_snapshot(
        self,
        token_address: str,
        chain: str = "unknown",
        holder_limit: int = 2_000,
        transfer_limit: int = 100,
        activity_window_hours: int = 24,
    ) -> dict:
        raise NotImplementedError


class HeliusAdoptionProvider(AdoptionProvider):
    """Read-only Solana holder and bounded transfer-activity collector."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Any = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.api_key = api_key or os.getenv("HELIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Add it as a secret or .env value.")
        self.session = session or requests
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _rpc(self, method: str, params: list | dict) -> Any:
        response = self.session.post(
            f"{HELIUS_RPC_URL}?api-key={self.api_key}",
            json={
                "jsonrpc": "2.0",
                "id": "narrative-radar",
                "method": method,
                "params": params,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Helius returned an invalid {method} response")
        if payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                message = error.get("message") or str(error)
            else:
                message = str(error)
            raise RuntimeError(f"Helius {method} failed: {message}")
        if "result" not in payload:
            raise RuntimeError(f"Helius returned no result for {method}")
        return payload["result"]

    def _fetch_holder_accounts(
        self,
        token_address: str,
        max_accounts: int,
    ) -> dict:
        max_accounts = max(1, min(int(max_accounts), 10_000))
        page_limit = min(100, max_accounts)
        page = 1
        accounts = []
        owners = set()
        unknown_owner_rows = 0
        unknown_amount_rows = 0
        owner_balances: dict[str, Decimal] = {}
        scanned_token_amount = Decimal("0")
        total = None
        last_indexed_slot = None

        while len(accounts) < max_accounts:
            result = self._rpc(
                "getTokenAccounts",
                {
                    "mint": token_address,
                    "page": page,
                    "limit": page_limit,
                    "options": {"showZeroBalance": False},
                },
            )
            if not isinstance(result, dict):
                raise RuntimeError("Helius returned an invalid getTokenAccounts result")
            page_accounts = result.get("token_accounts")
            if not isinstance(page_accounts, list):
                raise RuntimeError("Helius returned no token_accounts list")
            if total is None:
                total = _integer(result.get("total"))
            if last_indexed_slot is None:
                last_indexed_slot = _integer(result.get("last_indexed_slot"))

            for account in page_accounts:
                if not isinstance(account, dict):
                    continue
                accounts.append(account)
                amount = _decimal(account.get("amount"))
                if amount is None:
                    unknown_amount_rows += 1
                if amount is not None and amount <= 0:
                    continue
                if amount is not None:
                    scanned_token_amount += amount
                owner = str(account.get("owner") or "").strip()
                if owner:
                    owners.add(owner)
                    if amount is not None:
                        owner_balances[owner] = owner_balances.get(owner, Decimal("0")) + amount
                else:
                    unknown_owner_rows += 1
                if len(accounts) >= max_accounts:
                    break

            if not page_accounts or len(page_accounts) < page_limit:
                break
            if total is not None and len(accounts) >= total:
                break
            page += 1

        complete = total is not None and len(accounts) >= total
        if total is None and len(accounts) < max_accounts:
            complete = True
        owner_amounts = sorted(owner_balances.values(), reverse=True)
        return {
            "holder_count": len(owners),
            "token_account_count": len(accounts),
            "total": total,
            "returned": len(accounts),
            "complete": bool(complete),
            "last_indexed_slot": last_indexed_slot,
            "unknown_owner_rows": unknown_owner_rows,
            "unknown_amount_rows": unknown_amount_rows,
            "scanned_token_amount_raw": str(scanned_token_amount),
            "largest_owner_amount_raw": str(owner_amounts[0]) if owner_amounts else None,
            "top_10_owner_amount_raw": str(sum(owner_amounts[:10])) if owner_amounts else None,
        }

    def _fetch_supply(self, token_address: str) -> dict:
        result = self._rpc("getTokenSupply", [token_address])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise RuntimeError("Helius returned no token supply value")
        return {
            "token_supply": _number(value.get("uiAmount")),
            "token_supply_raw": str(value.get("amount")) if value.get("amount") is not None else None,
            "token_decimals": _integer(value.get("decimals")),
        }

    @staticmethod
    def _balance_amount(entry: dict) -> Optional[float]:
        value = entry.get("uiTokenAmount")
        if not isinstance(value, dict):
            return _number(entry.get("amount"))
        return _number(value.get("amount"))

    @classmethod
    def _token_balance_changes(cls, row: dict, token_address: str) -> list[dict]:
        meta = row.get("meta") if isinstance(row, dict) else None
        if not isinstance(meta, dict):
            return []
        before = {}
        after = {}
        for entry in meta.get("preTokenBalances") or []:
            if not isinstance(entry, dict) or entry.get("mint") != token_address:
                continue
            key = (entry.get("accountIndex"), entry.get("owner") or "")
            before[key] = {
                "amount": cls._balance_amount(entry) or 0.0,
                "owner": entry.get("owner") or "",
            }
        for entry in meta.get("postTokenBalances") or []:
            if not isinstance(entry, dict) or entry.get("mint") != token_address:
                continue
            key = (entry.get("accountIndex"), entry.get("owner") or "")
            after[key] = {
                "amount": cls._balance_amount(entry) or 0.0,
                "owner": entry.get("owner") or "",
            }

        changes = []
        for key in set(before) | set(after):
            before_value = before.get(key, {})
            after_value = after.get(key, {})
            delta = after_value.get("amount", 0.0) - before_value.get("amount", 0.0)
            if abs(delta) <= 1e-12:
                continue
            changes.append(
                {
                    "owner": after_value.get("owner") or before_value.get("owner") or "",
                    "delta": delta,
                }
            )
        return changes

    def _fetch_transfer_activity(
        self,
        token_address: str,
        limit: int,
        window_hours: int,
    ) -> dict:
        limit = max(1, min(int(limit), 1000))
        window_hours = max(1, min(int(window_hours), 24 * 30))
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        since = now - timedelta(hours=window_hours)
        result = self._rpc(
            "getTransactionsForAddress",
            [
                token_address,
                {
                    "transactionDetails": "full",
                    "limit": limit,
                    "sortOrder": "desc",
                    "commitment": "finalized",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "filters": {
                        "status": "succeeded",
                        "blockTime": {"gte": int(since.timestamp())},
                        "tokenTransfer": {"mint": token_address},
                    },
                },
            ],
        )
        if not isinstance(result, dict):
            raise RuntimeError("Helius returned an invalid transaction result")
        rows = result.get("data") or []
        if not isinstance(rows, list):
            raise RuntimeError("Helius returned no transaction data list")

        active_wallets = set()
        inflow_wallets = set()
        outflow_wallets = set()
        transaction_count = 0
        event_count = 0
        unknown_owner_changes = 0
        for row in rows:
            changes = self._token_balance_changes(row, token_address)
            if not changes:
                continue
            transaction_count += 1
            event_count += len(changes)
            for change in changes:
                owner = str(change.get("owner") or "").strip()
                if not owner:
                    unknown_owner_changes += 1
                    continue
                active_wallets.add(owner)
                if change["delta"] > 0:
                    inflow_wallets.add(owner)
                elif change["delta"] < 0:
                    outflow_wallets.add(owner)

        return {
            "activity_window_hours": window_hours,
            "transfer_transaction_count_24h": transaction_count,
            "transfer_event_count_24h": event_count,
            "unique_active_wallets_24h": len(active_wallets),
            "unique_inflow_wallets_24h": len(inflow_wallets),
            "unique_outflow_wallets_24h": len(outflow_wallets),
            "transfer_scan_returned": len(rows),
            "transfer_scan_limit": limit,
            "transfer_scan_truncated": bool(result.get("paginationToken")),
            "unknown_owner_changes": unknown_owner_changes,
        }

    def fetch_snapshot(
        self,
        token_address: str,
        chain: str = "unknown",
        holder_limit: int = 2_000,
        transfer_limit: int = 100,
        activity_window_hours: int = 24,
    ) -> dict:
        if not token_address or not token_address.strip():
            raise ValueError("token_address is required")
        token_address = token_address.strip()
        chain = (chain or "unknown").strip().lower()
        observed_at = self.clock()
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        snapshot = OnchainActivitySnapshot(
            token_address=token_address,
            chain=chain,
            observed_at=observed_at.astimezone(timezone.utc).isoformat(),
            activity_window_hours=max(1, min(int(activity_window_hours), 24 * 30)),
        )
        if not is_solana_chain(chain):
            snapshot.status = "unsupported_chain"
            snapshot.note = "The current on-chain adapter supports Solana mainnet only."
            return snapshot.to_dict()

        successful_sections = 0
        holders = {}
        try:
            holders = self._fetch_holder_accounts(token_address, holder_limit)
            snapshot.holder_count = holders["holder_count"]
            snapshot.token_account_count = holders["token_account_count"]
            snapshot.holder_scan_total = holders["total"]
            snapshot.holder_scan_returned = holders["returned"]
            snapshot.holder_scan_complete = holders["complete"]
            snapshot.last_indexed_slot = holders["last_indexed_slot"]
            snapshot.holder_count_is_lower_bound = not holders["complete"]
            snapshot.holder_concentration_is_lower_bound = not holders["complete"]
            snapshot.scanned_token_amount_raw = holders["scanned_token_amount_raw"]
            if holders["unknown_amount_rows"]:
                snapshot.warnings.append(
                    "Some token accounts had no parseable amount; supply coverage and concentration are incomplete."
                )
            if holders["unknown_owner_rows"]:
                snapshot.warnings.append(
                    "Some nonzero token accounts had no owner field and were excluded from the holder count."
                )
            if not holders["complete"]:
                snapshot.warnings.append(
                    "Holder scan was bounded; holder_count is a lower bound until a complete scan is collected."
                )
            successful_sections += 1
        except Exception as exc:
            snapshot.errors.append(f"holder scan: {exc}")

        try:
            snapshot.__dict__.update(self._fetch_supply(token_address))
            supply = _decimal(snapshot.token_supply_raw)
            scanned = _decimal(snapshot.scanned_token_amount_raw)
            largest = _decimal(holders.get("largest_owner_amount_raw"))
            top_10 = _decimal(holders.get("top_10_owner_amount_raw"))
            if supply is not None and supply > 0:
                if scanned is not None:
                    snapshot.scanned_supply_coverage_pct = round(float(scanned / supply * 100), 4)
                if largest is not None:
                    snapshot.largest_scanned_owner_share_pct = round(float(largest / supply * 100), 4)
                if top_10 is not None:
                    snapshot.top_10_scanned_owner_share_pct = round(float(top_10 / supply * 100), 4)
            successful_sections += 1
        except Exception as exc:
            snapshot.warnings.append(f"Token supply was unavailable: {exc}")

        try:
            activity = self._fetch_transfer_activity(
                token_address,
                transfer_limit,
                snapshot.activity_window_hours,
            )
            snapshot.__dict__.update(activity)
            if activity["unknown_owner_changes"]:
                snapshot.warnings.append(
                    "Some balance changes had no owner field; active-wallet counts are incomplete."
                )
            if not activity["transfer_transaction_count_24h"] and snapshot.transfer_scan_returned:
                snapshot.warnings.append(
                    "Transactions were returned but no token balance changes could be parsed from them."
                )
            if snapshot.transfer_scan_truncated:
                snapshot.warnings.append(
                    "Transfer scan reached its page limit; activity counts are a lower bound for the window."
                )
            successful_sections += 1
        except Exception as exc:
            snapshot.errors.append(f"transfer activity scan: {exc}")

        if successful_sections == 3:
            snapshot.status = "complete"
        elif successful_sections:
            snapshot.status = "partial"
        else:
            snapshot.status = "failed"
        return snapshot.to_dict()
