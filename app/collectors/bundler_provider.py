"""Bounded Solana linked-wallet and launch-bundle screening through Helius.

The collector reports observable relationships only. Shared fee payers, shared
SOL funders, or same-slot acquisitions can have legitimate explanations and do
not prove common ownership. Concentrated clusters fail closed for manual review;
the module never signs or submits a transaction.
"""

import os
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

import requests
from dotenv import load_dotenv

from app.collectors.adoption_provider import HELIUS_RPC_URL, is_solana_chain


load_dotenv()


HELIUS_HISTORY_URL = (
    "https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"
)


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _integer(value: Any) -> Optional[int]:
    number = _decimal(value)
    return int(number) if number is not None else None


def _share(amount: Optional[Decimal], supply: Optional[Decimal]) -> Optional[float]:
    if amount is None or supply is None or supply <= 0:
        return None
    return round(float(amount / supply * 100), 4)


def _raw_token_amount(entry: Mapping[str, Any]) -> Optional[Decimal]:
    ui_amount = entry.get("uiTokenAmount")
    if isinstance(ui_amount, Mapping):
        return _decimal(ui_amount.get("amount"))
    return _decimal(entry.get("amount"))


def _public_key(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("pubkey") or value.get("address") or "").strip()
    return str(value or "").strip()


class HeliusBundlerProvider:
    """Inspect a bounded token-launch window for observable wallet links."""

    provider_name = "helius"

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Any = None,
        timeout: int = 30,
        launch_transaction_limit: int = 200,
        holder_account_limit: int = 500,
        funding_wallet_limit: int = 12,
        funding_history_limit: int = 50,
        funding_window_hours: int = 24 * 7,
        minimum_funding_lamports: int = 5_000_000,
    ):
        self.api_key = api_key or os.getenv("HELIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Add it as a secret or .env value.")
        self.session = session or requests.Session()
        self.timeout = max(1, int(timeout))
        self.launch_transaction_limit = max(
            10, min(int(launch_transaction_limit), 1_000)
        )
        self.holder_account_limit = max(10, min(int(holder_account_limit), 2_000))
        self.funding_wallet_limit = max(2, min(int(funding_wallet_limit), 25))
        self.funding_history_limit = max(5, min(int(funding_history_limit), 100))
        self.funding_window_hours = max(1, min(int(funding_window_hours), 24 * 30))
        self.minimum_funding_lamports = max(1, int(minimum_funding_lamports))

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc)
        return message.replace(self.api_key, "[redacted]") if self.api_key else message

    def _rpc(self, method: str, params: list | dict) -> Any:
        try:
            response = self.session.post(
                f"{HELIUS_RPC_URL}?api-key={self.api_key}",
                json={
                    "jsonrpc": "2.0",
                    "id": "narrative-radar-bundler",
                    "method": method,
                    "params": params,
                },
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f" with HTTP {status}" if status else ""
            raise RuntimeError(f"Helius {method} request failed{detail}.") from None
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"Helius returned an invalid {method} response")
        if payload.get("error"):
            error = payload["error"]
            message = error.get("message") if isinstance(error, Mapping) else str(error)
            raise RuntimeError(f"Helius {method} failed: {message}")
        if "result" not in payload:
            raise RuntimeError(f"Helius returned no result for {method}")
        return payload["result"]

    def _fetch_holder_balances(self, token_address: str) -> dict:
        page = 1
        page_limit = min(100, self.holder_account_limit)
        returned = 0
        total = None
        balances: dict[str, Decimal] = defaultdict(Decimal)
        while returned < self.holder_account_limit:
            result = self._rpc(
                "getTokenAccounts",
                {
                    "mint": token_address,
                    "page": page,
                    "limit": page_limit,
                    "options": {"showZeroBalance": False},
                },
            )
            if not isinstance(result, Mapping):
                raise RuntimeError("Helius returned an invalid getTokenAccounts result")
            rows = result.get("token_accounts")
            if not isinstance(rows, list):
                raise RuntimeError("Helius returned no token_accounts list")
            if total is None:
                total = _integer(result.get("total"))
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                returned += 1
                owner = str(row.get("owner") or "").strip()
                amount = _decimal(row.get("amount"))
                if owner and amount is not None and amount > 0:
                    balances[owner] += amount
                if returned >= self.holder_account_limit:
                    break
            if not rows or len(rows) < page_limit:
                break
            if total is not None and returned >= total:
                break
            page += 1
        complete = total is not None and returned >= total
        if total is None and returned < self.holder_account_limit:
            complete = True
        return {
            "balances": dict(balances),
            "returned": returned,
            "total": total,
            "complete": bool(complete),
        }

    def _fetch_supply(self, token_address: str) -> Decimal:
        result = self._rpc("getTokenSupply", [token_address])
        value = result.get("value") if isinstance(result, Mapping) else None
        amount = _decimal(value.get("amount")) if isinstance(value, Mapping) else None
        if amount is None or amount <= 0:
            raise RuntimeError("Helius returned no positive token supply")
        return amount

    def _fetch_launch_transactions(self, token_address: str) -> dict:
        result = self._rpc(
            "getTransactionsForAddress",
            [
                token_address,
                {
                    "transactionDetails": "full",
                    "limit": self.launch_transaction_limit,
                    "sortOrder": "asc",
                    "commitment": "finalized",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "filters": {
                        "status": "succeeded",
                        "tokenTransfer": {"mint": token_address},
                    },
                },
            ],
        )
        if not isinstance(result, Mapping) or not isinstance(result.get("data"), list):
            raise RuntimeError("Helius returned no launch transaction list")
        return {
            "rows": result["data"],
            "truncated": bool(result.get("paginationToken")),
        }

    @staticmethod
    def _signature(row: Mapping[str, Any]) -> str:
        direct = str(row.get("signature") or "").strip()
        if direct:
            return direct
        transaction = row.get("transaction")
        signatures = transaction.get("signatures") if isinstance(transaction, Mapping) else None
        return str(signatures[0]).strip() if isinstance(signatures, list) and signatures else ""

    @staticmethod
    def _fee_payer(row: Mapping[str, Any]) -> str:
        direct = str(row.get("feePayer") or row.get("fee_payer") or "").strip()
        if direct:
            return direct
        transaction = row.get("transaction")
        message = transaction.get("message") if isinstance(transaction, Mapping) else None
        keys = message.get("accountKeys") if isinstance(message, Mapping) else None
        if not isinstance(keys, list) or not keys:
            return ""
        for key in keys:
            if isinstance(key, Mapping) and key.get("signer") is True:
                return _public_key(key)
        return _public_key(keys[0])

    @staticmethod
    def _positive_token_changes(
        row: Mapping[str, Any], token_address: str
    ) -> dict[str, Decimal]:
        meta = row.get("meta")
        if not isinstance(meta, Mapping):
            return {}
        before: dict[tuple[Any, str], Decimal] = {}
        after: dict[tuple[Any, str], Decimal] = {}
        for entry in meta.get("preTokenBalances") or []:
            if not isinstance(entry, Mapping) or entry.get("mint") != token_address:
                continue
            owner = str(entry.get("owner") or "").strip()
            amount = _raw_token_amount(entry)
            if owner and amount is not None:
                before[(entry.get("accountIndex"), owner)] = amount
        for entry in meta.get("postTokenBalances") or []:
            if not isinstance(entry, Mapping) or entry.get("mint") != token_address:
                continue
            owner = str(entry.get("owner") or "").strip()
            amount = _raw_token_amount(entry)
            if owner and amount is not None:
                after[(entry.get("accountIndex"), owner)] = amount
        changes: dict[str, Decimal] = defaultdict(Decimal)
        for key in set(before) | set(after):
            delta = after.get(key, Decimal(0)) - before.get(key, Decimal(0))
            if delta > 0:
                changes[key[1]] += delta
        return dict(changes)

    def _first_acquisitions(
        self, rows: list[Any], token_address: str
    ) -> dict[str, dict]:
        acquisitions: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            slot = _integer(row.get("slot"))
            timestamp = _integer(row.get("blockTime") or row.get("timestamp"))
            signature = self._signature(row)
            fee_payer = self._fee_payer(row)
            for owner, amount in self._positive_token_changes(row, token_address).items():
                if owner in acquisitions:
                    continue
                acquisitions[owner] = {
                    "owner": owner,
                    "amount": amount,
                    "slot": slot,
                    "timestamp": timestamp,
                    "signature": signature,
                    "fee_payer": fee_payer,
                }
        return acquisitions

    def _fetch_funding_history(
        self, wallet_address: str, acquisition_timestamp: int
    ) -> list[dict]:
        params = {
            "api-key": self.api_key,
            "limit": self.funding_history_limit,
            "commitment": "finalized",
            "token-accounts": "none",
            "sort-order": "desc",
            "gte-time": acquisition_timestamp - self.funding_window_hours * 3600,
            "lte-time": acquisition_timestamp + 60,
        }
        try:
            response = self.session.get(
                HELIUS_HISTORY_URL.format(wallet_address=wallet_address),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f" with HTTP {status}" if status else ""
            raise RuntimeError(f"Helius funding-history request failed{detail}.") from None
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        if isinstance(payload, Mapping) and isinstance(payload.get("transactions"), list):
            return [row for row in payload["transactions"] if isinstance(row, Mapping)]
        raise RuntimeError("Helius returned an invalid funding-history response")

    def _find_funder(
        self,
        rows: list[dict],
        wallet_address: str,
        acquisition_timestamp: int,
    ) -> Optional[dict]:
        matches = []
        for row in rows:
            timestamp = _integer(row.get("timestamp") or row.get("blockTime"))
            if timestamp is not None and timestamp > acquisition_timestamp + 60:
                continue
            for transfer in row.get("nativeTransfers") or []:
                if not isinstance(transfer, Mapping):
                    continue
                source = str(transfer.get("fromUserAccount") or "").strip()
                target = str(transfer.get("toUserAccount") or "").strip()
                amount = _integer(transfer.get("amount"))
                if (
                    target == wallet_address
                    and source
                    and source != wallet_address
                    and amount is not None
                    and amount >= self.minimum_funding_lamports
                ):
                    matches.append(
                        {
                            "funder": source,
                            "amount_lamports": amount,
                            "timestamp": timestamp,
                            "signature": self._signature(row),
                        }
                    )
        if not matches:
            return None
        return max(matches, key=lambda item: item.get("timestamp") or 0)

    @staticmethod
    def _blocks_cluster(owner_count: int, share_pct: Optional[float]) -> bool:
        if share_pct is None:
            return False
        return (owner_count >= 3 and share_pct >= 5) or (
            owner_count >= 2 and share_pct >= 10
        )

    def _cluster(
        self,
        cluster_type: str,
        identifier: Any,
        records: list[dict],
        holder_balances: Mapping[str, Decimal],
        supply: Decimal,
        note: str,
        *,
        same_slot_only: bool = False,
    ) -> dict:
        by_owner = {record["owner"]: record for record in records}
        owners = sorted(by_owner)
        acquisition_amount = sum(
            (record["amount"] for record in by_owner.values()), Decimal(0)
        )
        current_amount = sum(
            (holder_balances.get(owner, Decimal(0)) for owner in owners),
            Decimal(0),
        )
        acquisition_share = _share(acquisition_amount, supply)
        current_share = _share(current_amount, supply)
        measured_shares = [
            value for value in (acquisition_share, current_share) if value is not None
        ]
        concentration_share = max(measured_shares) if measured_shares else None
        blocked = self._blocks_cluster(len(owners), concentration_share)
        if same_slot_only:
            blocked = (
                concentration_share is not None
                and len(owners) >= 5
                and concentration_share >= 10
            )
        return {
            "type": cluster_type,
            "identifier": str(identifier),
            "owner_count": len(owners),
            "wallets": owners[:10],
            "wallets_truncated": len(owners) > 10,
            "initial_acquisition_amount_raw": str(acquisition_amount),
            "initial_acquisition_supply_share_pct": acquisition_share,
            "current_scanned_balance_raw": str(current_amount),
            "current_scanned_supply_share_pct": current_share,
            "concentration_share_pct": concentration_share,
            "hard_blocker": blocked,
            "note": note,
        }

    def fetch(self, token_address: str, chain: str = "solana") -> dict:
        token_address = str(token_address or "").strip()
        normalized_chain = str(chain or "").strip().lower()
        if not token_address:
            raise ValueError("token_address is required")
        if not is_solana_chain(normalized_chain):
            return {
                "status": "unsupported_chain",
                "provider": self.provider_name,
                "chain": normalized_chain or "unknown",
                "hard_blockers": [],
                "flags": [],
                "execution_enabled": False,
                "note": "The current linked-wallet adapter supports Solana mainnet only.",
            }

        warnings: list[str] = []
        errors: list[str] = []
        holder_balances: dict[str, Decimal] = {}
        holder_scan = {"returned": 0, "total": None, "complete": False}
        try:
            holder_scan = self._fetch_holder_balances(token_address)
            holder_balances = holder_scan.pop("balances")
            if not holder_scan["complete"]:
                warnings.append(
                    "Current-holder matching is bounded; cluster current-balance shares may be lower bounds."
                )
        except Exception as exc:  # noqa: BLE001 - report partial coverage safely
            errors.append(f"holder matching: {self._safe_error(exc)}")

        supply = None
        try:
            supply = self._fetch_supply(token_address)
        except Exception as exc:  # noqa: BLE001 - report partial coverage safely
            errors.append(f"token supply: {self._safe_error(exc)}")

        try:
            launch_scan = self._fetch_launch_transactions(token_address)
        except Exception as exc:  # noqa: BLE001 - fail closed with no inference
            return {
                "status": "failed",
                "provider": self.provider_name,
                "chain": normalized_chain,
                "contract_address": token_address,
                "hard_blockers": [],
                "flags": [],
                "errors": errors + [f"launch scan: {self._safe_error(exc)}"],
                "warnings": warnings,
                "execution_enabled": False,
                "note": "The launch-window collector failed; manual bundle review is required.",
            }

        rows = launch_scan["rows"]
        acquisitions = self._first_acquisitions(rows, token_address)
        ordered_acquisitions = sorted(
            acquisitions.values(), key=lambda row: row["amount"], reverse=True
        )
        funding_candidates = [
            row for row in ordered_acquisitions if row.get("timestamp") is not None
        ][: self.funding_wallet_limit]
        funding_records = []
        funding_checks_failed = 0
        funding_wallets_checked = 0
        for acquisition in funding_candidates:
            try:
                history = self._fetch_funding_history(
                    acquisition["owner"], acquisition["timestamp"]
                )
                funding_wallets_checked += 1
                funder = self._find_funder(
                    history,
                    acquisition["owner"],
                    acquisition["timestamp"],
                )
                if funder:
                    funding_records.append({**acquisition, **funder})
            except Exception as exc:  # noqa: BLE001 - one wallet must not erase others
                funding_checks_failed += 1
                errors.append(
                    f"funding history for {acquisition['owner'][:8]}…: {self._safe_error(exc)}"
                )

        clusters = []
        grouped_funders: dict[str, list[dict]] = defaultdict(list)
        for record in funding_records:
            grouped_funders[record["funder"]].append(record)
        for funder, records in grouped_funders.items():
            if len({record["owner"] for record in records}) >= 2 and supply is not None:
                clusters.append(
                    self._cluster(
                        "shared_pre_acquisition_funder",
                        funder,
                        records,
                        holder_balances,
                        supply,
                        "Multiple early wallets received SOL from the same address before acquisition; this does not prove common ownership.",
                    )
                )

        for field, cluster_type, note in (
            (
                "fee_payer",
                "shared_fee_payer",
                "One fee payer submitted first-acquisition transactions for multiple token owners.",
            ),
            (
                "signature",
                "single_transaction_multi_wallet",
                "One transaction credited multiple token owners during the bounded launch window.",
            ),
        ):
            groups: dict[str, list[dict]] = defaultdict(list)
            for record in acquisitions.values():
                identifier = str(record.get(field) or "").strip()
                if identifier:
                    groups[identifier].append(record)
            for identifier, records in groups.items():
                if len({record["owner"] for record in records}) >= 2 and supply is not None:
                    clusters.append(
                        self._cluster(
                            cluster_type,
                            identifier,
                            records,
                            holder_balances,
                            supply,
                            note,
                        )
                    )

        slot_groups: dict[int, list[dict]] = defaultdict(list)
        for record in acquisitions.values():
            if record.get("slot") is not None:
                slot_groups[record["slot"]].append(record)
        for slot, records in slot_groups.items():
            if len({record["owner"] for record in records}) >= 3 and supply is not None:
                clusters.append(
                    self._cluster(
                        "same_slot_first_acquisition",
                        slot,
                        records,
                        holder_balances,
                        supply,
                        "Several first observed acquisitions landed in one slot; high Solana throughput can also cause this pattern.",
                        same_slot_only=True,
                    )
                )

        blocker_codes = {
            "shared_pre_acquisition_funder": "shared_funder_concentration",
            "shared_fee_payer": "shared_fee_payer_concentration",
            "single_transaction_multi_wallet": "multi_wallet_transaction_concentration",
            "same_slot_first_acquisition": "same_slot_acquisition_concentration",
        }
        blocking_clusters = [cluster for cluster in clusters if cluster["hard_blocker"]]
        hard_blockers = sorted(
            {blocker_codes[cluster["type"]] for cluster in blocking_clusters}
        )
        flags = [
            {
                "code": blocker_codes[cluster["type"]],
                "severity": "high",
                "message": (
                    "Concentrated early-wallet links require manual review before this token can advance."
                ),
                "details": {
                    "cluster_type": cluster["type"],
                    "owner_count": cluster["owner_count"],
                    "concentration_share_pct": cluster["concentration_share_pct"],
                },
            }
            for cluster in blocking_clusters
        ]

        if launch_scan["truncated"]:
            warnings.append(
                "Only the earliest bounded transaction window was inspected; later activity was intentionally excluded."
            )
        if funding_checks_failed:
            warnings.append(
                f"{funding_checks_failed} funding-history check(s) failed; shared-funder coverage is incomplete."
            )
        if not funding_candidates and acquisitions:
            warnings.append(
                "Acquisition timestamps were unavailable, so pre-acquisition funding could not be checked."
            )

        status = "complete"
        if not rows or len(acquisitions) < 3:
            status = "insufficient_data"
        elif supply is None or errors:
            status = "partial"
        elif launch_scan["truncated"] and len(acquisitions) < 10:
            status = "partial"
        elif funding_candidates and funding_wallets_checked < min(3, len(funding_candidates)):
            status = "partial"
        elif acquisitions and not funding_candidates:
            status = "partial"

        measured_cluster_shares = [
            cluster["concentration_share_pct"]
            for cluster in clusters
            if cluster["concentration_share_pct"] is not None
        ]
        clusters.sort(
            key=lambda item: (
                not item["hard_blocker"],
                -(item["concentration_share_pct"] or 0),
                item["type"],
            )
        )
        return {
            "status": status,
            "provider": self.provider_name,
            "chain": normalized_chain,
            "contract_address": token_address,
            "analysis_scope": "earliest_bounded_token_transactions",
            "launch_transactions_scanned": len(rows),
            "launch_transaction_limit": self.launch_transaction_limit,
            "launch_scan_truncated": launch_scan["truncated"],
            "first_acquisition_owner_count": len(acquisitions),
            "holder_accounts_scanned": holder_scan["returned"],
            "holder_account_total": holder_scan["total"],
            "holder_scan_complete": holder_scan["complete"],
            "funding_wallets_requested": len(funding_candidates),
            "funding_wallets_checked": funding_wallets_checked,
            "funding_checks_failed": funding_checks_failed,
            "linked_cluster_count": len(clusters),
            "blocking_cluster_count": len(blocking_clusters),
            "largest_cluster_supply_share_pct": (
                max(measured_cluster_shares) if measured_cluster_shares else None
            ),
            "clusters": clusters[:10],
            "clusters_truncated": len(clusters) > 10,
            "hard_blockers": hard_blockers,
            "flags": flags,
            "warnings": warnings,
            "errors": errors,
            "execution_enabled": False,
            "note": (
                "Observable shared funders, fee payers, and same-slot acquisition patterns are bounded risk indicators, not proof of common ownership or fraud."
            ),
        }
