"""Bounded Robinhood Chain launch-wallet screening.

The collector inspects exact-pair ERC-20 outflows, transaction senders, block
cohorts, and bounded pre-acquisition funding history. These are observable risk
indicators only: shared infrastructure and account abstraction can link
unrelated users, while off-chain funding and private coordination can remain
invisible. Missing history always produces a partial or failed result.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
import re
from typing import Any, Mapping, Optional

import requests
from dotenv import load_dotenv


load_dotenv()


ROBINHOOD_MAINNET_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
ROBINHOOD_BLOCKSCOUT_API_URL = "https://robinhoodchain.blockscout.com/api/"
ROBINHOOD_CHAIN_ID = 4663
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"

_EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_BURN_ADDRESSES = {
    _ZERO_ADDRESS,
    "0x0000000000000000000000000000000000000001",
    "0x000000000000000000000000000000000000dead",
}


def _address(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _EVM_ADDRESS.fullmatch(candidate) else ""


def _hex_integer(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return int(candidate, 16) if candidate.lower().startswith("0x") else int(candidate)
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _timestamp(value: Any) -> Optional[int]:
    numeric = _decimal(value)
    if numeric is not None:
        if numeric > 10_000_000_000:
            numeric /= 1_000
        return int(numeric) if numeric > 0 else None
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _share(amount: Decimal, supply: Optional[Decimal]) -> Optional[float]:
    if supply is None or supply <= 0:
        return None
    return round(float(amount / supply * 100), 4)


class RobinhoodBundlerProvider:
    """Inspect a bounded Robinhood Chain launch window for wallet links."""

    provider_name = "robinhood_rpc_blockscout"
    analysis_version = "robinhood-links-v1"

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        blockscout_api_url: Optional[str] = None,
        blockscout_api_key: Optional[str] = None,
        session: Any = None,
        timeout: int = 20,
        launch_block_limit: int = 120,
        log_chunk_size: int = 10,
        recipient_limit: int = 40,
        transaction_limit: int = 40,
        funding_wallet_limit: int = 12,
        funding_history_limit: int = 50,
        funding_page_limit: int = 2,
        funding_window_hours: int = 24 * 7,
        minimum_funding_wei: int = 100_000_000_000_000,
    ):
        self.rpc_url = (
            rpc_url
            or os.getenv("ROBINHOOD_RPC_URL")
            or ROBINHOOD_MAINNET_RPC_URL
        )
        self.blockscout_api_url = (
            blockscout_api_url
            or os.getenv("ROBINHOOD_BLOCKSCOUT_API_URL")
            or ROBINHOOD_BLOCKSCOUT_API_URL
        )
        self.blockscout_api_key = blockscout_api_key or os.getenv(
            "ROBINHOOD_BLOCKSCOUT_API_KEY"
        )
        self.session = session or requests.Session()
        self.timeout = max(1, int(timeout))
        self.launch_block_limit = max(20, min(int(launch_block_limit), 1_000))
        self.log_chunk_size = max(1, min(int(log_chunk_size), 100))
        self.recipient_limit = max(3, min(int(recipient_limit), 100))
        self.transaction_limit = max(3, min(int(transaction_limit), 100))
        self.funding_wallet_limit = max(3, min(int(funding_wallet_limit), 25))
        self.funding_history_limit = max(10, min(int(funding_history_limit), 100))
        self.funding_page_limit = max(1, min(int(funding_page_limit), 5))
        self.funding_window_hours = max(1, min(int(funding_window_hours), 24 * 30))
        self.minimum_funding_wei = max(1, int(minimum_funding_wei))

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc)
        for secret in (
            self.rpc_url,
            self.blockscout_api_key,
        ):
            if secret:
                message = message.replace(secret, "[redacted]")
        return message

    def _rpc(self, method: str, params: list[Any]) -> Any:
        try:
            response = self.session.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "narrative-radar-robinhood-links",
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
            raise RuntimeError(f"Robinhood RPC {method} request failed{detail}.") from None
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"Robinhood RPC returned an invalid {method} response")
        if payload.get("error"):
            error = payload["error"]
            message = error.get("message") if isinstance(error, Mapping) else str(error)
            raise RuntimeError(f"Robinhood RPC {method} failed: {message}")
        if "result" not in payload:
            raise RuntimeError(f"Robinhood RPC returned no result for {method}")
        return payload["result"]

    def _block(self, number: int, full_transactions: bool = False) -> dict:
        result = self._rpc("eth_getBlockByNumber", [hex(number), full_transactions])
        if not isinstance(result, Mapping):
            raise RuntimeError(f"Robinhood RPC returned no block {number}")
        return dict(result)

    def _find_launch_block(self, target_timestamp: int, latest_number: int) -> int:
        low = 0
        high = latest_number
        latest_timestamp = _hex_integer(self._block(high).get("timestamp"))
        if latest_timestamp is None:
            raise RuntimeError("Latest Robinhood block has no timestamp")
        if target_timestamp >= latest_timestamp:
            return high
        while low < high:
            middle = (low + high) // 2
            block_timestamp = _hex_integer(self._block(middle).get("timestamp"))
            if block_timestamp is None:
                raise RuntimeError(f"Robinhood block {middle} has no timestamp")
            if block_timestamp < target_timestamp:
                low = middle + 1
            else:
                high = middle
        return low

    def _logs(self, token_address: str, start_block: int, end_block: int) -> dict:
        rows: list[dict] = []
        errors: list[str] = []
        chunks_requested = 0
        chunks_completed = 0
        for chunk_start in range(start_block, end_block + 1, self.log_chunk_size):
            chunk_end = min(end_block, chunk_start + self.log_chunk_size - 1)
            chunks_requested += 1
            try:
                result = self._rpc(
                    "eth_getLogs",
                    [
                        {
                            "address": token_address,
                            "fromBlock": hex(chunk_start),
                            "toBlock": hex(chunk_end),
                            "topics": [TRANSFER_TOPIC],
                        }
                    ],
                )
                if not isinstance(result, list):
                    raise RuntimeError("Robinhood RPC returned a non-list log result")
                chunks_completed += 1
                rows.extend(dict(row) for row in result if isinstance(row, Mapping))
            except Exception as exc:  # noqa: BLE001 - preserve partial bounded evidence
                errors.append(
                    f"log blocks {chunk_start}-{chunk_end}: {self._safe_error(exc)}"
                )
        return {
            "rows": rows,
            "chunks_requested": chunks_requested,
            "chunks_completed": chunks_completed,
            "errors": errors,
        }

    @staticmethod
    def _decode_transfer(row: Mapping[str, Any]) -> Optional[dict]:
        if row.get("removed") is True:
            return None
        topics = row.get("topics")
        if not isinstance(topics, list) or len(topics) < 3:
            return None
        if str(topics[0]).lower() != TRANSFER_TOPIC:
            return None
        sender = _address("0x" + str(topics[1])[-40:])
        recipient = _address("0x" + str(topics[2])[-40:])
        amount = _hex_integer(row.get("data"))
        block_number = _hex_integer(row.get("blockNumber"))
        transaction_index = _hex_integer(row.get("transactionIndex"))
        log_index = _hex_integer(row.get("logIndex"))
        tx_hash = str(row.get("transactionHash") or "").strip().lower()
        if (
            not sender
            or not recipient
            or amount is None
            or amount <= 0
            or block_number is None
            or log_index is None
            or not tx_hash.startswith("0x")
        ):
            return None
        return {
            "from": sender,
            "owner": recipient,
            "amount": Decimal(amount),
            "block_number": block_number,
            "transaction_index": transaction_index or 0,
            "log_index": log_index,
            "transaction_hash": tx_hash,
        }

    def _total_supply(self, token_address: str) -> Decimal:
        result = self._rpc(
            "eth_call",
            [{"to": token_address, "data": TOTAL_SUPPLY_SELECTOR}, "latest"],
        )
        supply = _hex_integer(result)
        if supply is None or supply <= 0:
            raise RuntimeError("Robinhood token returned no positive totalSupply")
        return Decimal(supply)

    def _is_contract(self, address: str) -> bool:
        result = str(self._rpc("eth_getCode", [address, "latest"]) or "").lower()
        return result not in {"", "0x", "0x0", "0x00"}

    def _transaction(self, tx_hash: str) -> dict:
        result = self._rpc("eth_getTransactionByHash", [tx_hash])
        if not isinstance(result, Mapping):
            raise RuntimeError(f"Robinhood RPC returned no transaction {tx_hash[:12]}")
        return dict(result)

    def _history_page(
        self,
        action: str,
        wallet: str,
        end_block: int,
        page: int,
    ) -> list[dict]:
        params = {
            "module": "account",
            "action": action,
            "address": wallet,
            "startblock": 0,
            "endblock": end_block,
            "page": page,
            "offset": self.funding_history_limit,
            "sort": "desc",
        }
        if self.blockscout_api_key:
            params["apikey"] = self.blockscout_api_key
        try:
            response = self.session.get(
                self.blockscout_api_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f" with HTTP {status}" if status else ""
            raise RuntimeError(f"Blockscout {action} request failed{detail}.") from None
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"Blockscout returned an invalid {action} response")
        result = payload.get("result")
        if isinstance(result, list):
            return [dict(row) for row in result if isinstance(row, Mapping)]
        message = str(payload.get("message") or result or "").lower()
        if "no transactions" in message or "no records" in message:
            return []
        raise RuntimeError(f"Blockscout {action} failed: {message or 'unknown error'}")

    def _funding_history(
        self,
        wallet: str,
        acquisition_block: int,
        acquisition_transaction_index: int,
        acquisition_timestamp: int,
    ) -> dict:
        rows: list[dict] = []
        truncated = False
        minimum_timestamp = acquisition_timestamp - self.funding_window_hours * 3600
        for action in ("txlist", "txlistinternal"):
            action_complete = False
            for page in range(1, self.funding_page_limit + 1):
                page_rows = self._history_page(
                    action, wallet, acquisition_block, page
                )
                rows.extend(page_rows)
                if len(page_rows) < self.funding_history_limit:
                    action_complete = True
                    break
                oldest = min(
                    (_timestamp(row.get("timeStamp")) or acquisition_timestamp)
                    for row in page_rows
                )
                if oldest < minimum_timestamp:
                    action_complete = True
                    break
            if not action_complete:
                truncated = True

        matches = []
        for row in rows:
            target = _address(row.get("to"))
            source = _address(row.get("from"))
            value = _decimal(row.get("value"))
            timestamp = _timestamp(row.get("timeStamp"))
            block_number = _hex_integer(row.get("blockNumber"))
            transaction_index = _hex_integer(row.get("transactionIndex"))
            if (
                target != wallet
                or not source
                or source == wallet
                or value is None
                or value < self.minimum_funding_wei
                or timestamp is None
                or timestamp < minimum_timestamp
                or timestamp > acquisition_timestamp
                or block_number is None
                or block_number > acquisition_block
                or (
                    block_number == acquisition_block
                    and (
                        transaction_index is None
                        or transaction_index >= acquisition_transaction_index
                    )
                )
            ):
                continue
            matches.append(
                {
                    "funder": source,
                    "funding_amount_wei": str(value),
                    "funding_timestamp": timestamp,
                    "funding_transaction_hash": str(row.get("hash") or ""),
                }
            )
        return {
            "funder": max(matches, key=lambda item: item["funding_timestamp"])
            if matches
            else None,
            "truncated": truncated,
        }

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
        supply: Optional[Decimal],
        note: str,
        *,
        same_block_only: bool = False,
    ) -> dict:
        by_owner = {record["owner"]: record for record in records}
        owners = sorted(by_owner)
        amount = sum(
            (record["amount"] for record in by_owner.values()), Decimal(0)
        )
        concentration_share = _share(amount, supply)
        blocked = self._blocks_cluster(len(owners), concentration_share)
        if same_block_only:
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
            "initial_acquisition_amount_raw": str(amount),
            "initial_acquisition_supply_share_pct": concentration_share,
            "concentration_share_pct": concentration_share,
            "hard_blocker": blocked,
            "note": note,
        }

    def _base_result(self, token_address: str, status: str, note: str) -> dict:
        return {
            "status": status,
            "provider": self.provider_name,
            "analysis_version": self.analysis_version,
            "chain": "robinhood",
            "contract_address": token_address,
            "hard_blockers": [],
            "flags": [],
            "errors": [],
            "warnings": [],
            "execution_enabled": False,
            "note": note,
        }

    def fetch(
        self,
        token_address: str,
        chain: str = "robinhood",
        *,
        pair_address: Any = None,
        pair_created_at: Any = None,
        pair_created_at_iso: Any = None,
    ) -> dict:
        token = _address(token_address)
        pair = _address(pair_address)
        normalized_chain = str(chain or "").strip().lower()
        if normalized_chain not in {"robinhood", "robinhood_chain"}:
            result = self._base_result(
                token or str(token_address or ""),
                "unsupported_chain",
                "The Robinhood linked-wallet adapter supports Robinhood Chain mainnet only.",
            )
            result["chain"] = normalized_chain or "unknown"
            return result
        if not token:
            raise ValueError("A valid EVM token_address is required")
        if not pair:
            return self._base_result(
                token,
                "insufficient_data",
                "The exact DEX pair is missing, so pair-outflow acquisition evidence cannot be attributed.",
            )
        created_timestamp = _timestamp(pair_created_at) or _timestamp(pair_created_at_iso)
        if created_timestamp is None:
            return self._base_result(
                token,
                "insufficient_data",
                "The pair creation time is missing, so a bounded launch block window cannot be selected.",
            )

        errors: list[str] = []
        warnings: list[str] = []
        try:
            chain_id = _hex_integer(self._rpc("eth_chainId", []))
            if chain_id != ROBINHOOD_CHAIN_ID:
                raise RuntimeError(
                    f"RPC chain ID {chain_id!r} does not match Robinhood mainnet {ROBINHOOD_CHAIN_ID}"
                )
            if not self._is_contract(token):
                raise RuntimeError("The supplied token address has no deployed bytecode")
            if not self._is_contract(pair):
                raise RuntimeError("The supplied DEX pair address has no deployed bytecode")
            latest_number = _hex_integer(self._rpc("eth_blockNumber", []))
            if latest_number is None:
                raise RuntimeError("Robinhood RPC returned no latest block number")
            launch_block = self._find_launch_block(created_timestamp, latest_number)
        except Exception as exc:  # noqa: BLE001 - return fail-closed structured result
            result = self._base_result(
                token,
                "failed",
                "The Robinhood launch-window setup failed; linked-wallet risk remains unknown.",
            )
            result["pair_address"] = pair
            result["errors"] = [self._safe_error(exc)]
            return result

        start_block = max(0, launch_block - 2)
        end_block = min(latest_number, launch_block + self.launch_block_limit - 1)
        log_scan = self._logs(token, start_block, end_block)
        errors.extend(log_scan["errors"])
        if log_scan["chunks_completed"] == 0:
            result = self._base_result(
                token,
                "failed",
                "No launch log chunk completed; linked-wallet risk remains unknown.",
            )
            result.update(
                {
                    "pair_address": pair,
                    "launch_block_start": start_block,
                    "launch_block_end": end_block,
                    "errors": errors,
                }
            )
            return result

        decoded = []
        seen_logs: set[tuple[str, int]] = set()
        malformed_logs = 0
        for row in log_scan["rows"]:
            transfer = self._decode_transfer(row)
            if transfer is None:
                malformed_logs += 1
                continue
            identity = (transfer["transaction_hash"], transfer["log_index"])
            if identity in seen_logs:
                continue
            seen_logs.add(identity)
            if transfer["from"] != pair or transfer["owner"] in _BURN_ADDRESSES | {token, pair}:
                continue
            decoded.append(transfer)

        by_owner: dict[str, dict] = {}
        for transfer in sorted(
            decoded,
            key=lambda item: (
                item["block_number"],
                item["transaction_index"],
                item["log_index"],
            ),
        ):
            by_owner.setdefault(transfer["owner"], transfer)
        ordered = sorted(by_owner.values(), key=lambda item: item["amount"], reverse=True)
        recipients_truncated = len(ordered) > self.recipient_limit
        ordered = ordered[: self.recipient_limit]

        eoa_records: list[dict] = []
        contract_recipients = 0
        recipient_code_failures = 0
        for record in ordered:
            try:
                if self._is_contract(record["owner"]):
                    contract_recipients += 1
                else:
                    eoa_records.append(record)
            except Exception as exc:  # noqa: BLE001 - one lookup must not erase evidence
                recipient_code_failures += 1
                errors.append(
                    f"recipient code {record['owner'][:10]}…: {self._safe_error(exc)}"
                )

        supply = None
        try:
            supply = self._total_supply(token)
        except Exception as exc:  # noqa: BLE001 - blockers need a measured denominator
            errors.append(f"total supply: {self._safe_error(exc)}")

        tx_records: dict[str, dict] = {}
        tx_lookup_failures = 0
        unique_hashes = list(dict.fromkeys(row["transaction_hash"] for row in eoa_records))
        transactions_truncated = len(unique_hashes) > self.transaction_limit
        for tx_hash in unique_hashes[: self.transaction_limit]:
            try:
                tx_records[tx_hash] = self._transaction(tx_hash)
            except Exception as exc:  # noqa: BLE001 - preserve same-block evidence
                tx_lookup_failures += 1
                errors.append(f"transaction {tx_hash[:12]}…: {self._safe_error(exc)}")

        for record in eoa_records:
            transaction = tx_records.get(record["transaction_hash"])
            record["top_level_sender"] = (
                _address(transaction.get("from")) if transaction else ""
            )

        funding_candidates = eoa_records[: self.funding_wallet_limit]
        funding_records = []
        funding_wallets_checked = 0
        funding_checks_failed = 0
        funding_histories_truncated = 0
        for record in funding_candidates:
            try:
                block = self._block(record["block_number"])
                acquisition_timestamp = _hex_integer(block.get("timestamp"))
                if acquisition_timestamp is None:
                    raise RuntimeError("acquisition block has no timestamp")
                history = self._funding_history(
                    record["owner"],
                    record["block_number"],
                    record["transaction_index"],
                    acquisition_timestamp,
                )
                funding_wallets_checked += 1
                if history["truncated"]:
                    funding_histories_truncated += 1
                if history["funder"]:
                    funding_records.append({**record, **history["funder"]})
            except Exception as exc:  # noqa: BLE001 - missing indexed history is partial
                funding_checks_failed += 1
                errors.append(
                    f"funding history {record['owner'][:10]}…: {self._safe_error(exc)}"
                )

        clusters = []
        groups: dict[str, list[dict]] = defaultdict(list)
        for record in eoa_records:
            groups[record["transaction_hash"]].append(record)
        for identifier, records in groups.items():
            if len({record["owner"] for record in records}) >= 2:
                clusters.append(
                    self._cluster(
                        "single_transaction_multi_wallet",
                        identifier,
                        records,
                        supply,
                        "One pair-outflow transaction credited multiple wallets; a router or account-abstraction flow can also create this pattern.",
                    )
                )

        groups = defaultdict(list)
        for record in eoa_records:
            if record.get("top_level_sender"):
                groups[record["top_level_sender"]].append(record)
        for identifier, records in groups.items():
            if len({record["owner"] for record in records}) >= 2:
                clusters.append(
                    self._cluster(
                        "shared_top_level_sender",
                        identifier,
                        records,
                        supply,
                        "One top-level transaction sender initiated acquisitions for multiple wallets; smart-wallet infrastructure can also cause this.",
                    )
                )

        block_groups: dict[int, list[dict]] = defaultdict(list)
        for record in eoa_records:
            block_groups[record["block_number"]].append(record)
        for identifier, records in block_groups.items():
            if len({record["owner"] for record in records}) >= 3:
                clusters.append(
                    self._cluster(
                        "same_block_first_acquisition",
                        identifier,
                        records,
                        supply,
                        "Several first observed pair acquisitions landed in one block; Robinhood's fast blocks and organic bursts can also cause this.",
                        same_block_only=True,
                    )
                )

        groups = defaultdict(list)
        for record in funding_records:
            groups[record["funder"]].append(record)
        for identifier, records in groups.items():
            if len({record["owner"] for record in records}) >= 2:
                clusters.append(
                    self._cluster(
                        "shared_pre_acquisition_funder",
                        identifier,
                        records,
                        supply,
                        "Multiple early wallets received native funds from one address before acquisition; that association does not prove common control.",
                    )
                )

        blocker_codes = {
            "single_transaction_multi_wallet": "multi_wallet_transaction_concentration",
            "shared_top_level_sender": "shared_sender_concentration",
            "same_block_first_acquisition": "same_block_acquisition_concentration",
            "shared_pre_acquisition_funder": "shared_funder_concentration",
        }
        blocking_clusters = [cluster for cluster in clusters if cluster["hard_blocker"]]
        hard_blockers = sorted(
            {blocker_codes[cluster["type"]] for cluster in blocking_clusters}
        )
        flags = [
            {
                "code": blocker_codes[cluster["type"]],
                "severity": "high",
                "message": "Concentrated early-wallet links require manual review before this token can advance.",
                "details": {
                    "cluster_type": cluster["type"],
                    "owner_count": cluster["owner_count"],
                    "concentration_share_pct": cluster["concentration_share_pct"],
                },
            }
            for cluster in blocking_clusters
        ]

        if malformed_logs:
            warnings.append(
                f"{malformed_logs} removed or malformed transfer log(s) were excluded."
            )
        if recipients_truncated:
            warnings.append("The EOA recipient sample hit its configured bound.")
        if transactions_truncated:
            warnings.append("The transaction lookup sample hit its configured bound.")
        if contract_recipients:
            warnings.append(
                f"{contract_recipients} contract recipient(s) were excluded to avoid treating routers as wallets."
            )
        if funding_histories_truncated:
            warnings.append(
                f"{funding_histories_truncated} funding history result(s) hit the pagination bound."
            )

        status = "complete"
        if len(eoa_records) < 3:
            status = "insufficient_data"
        elif (
            errors
            or supply is None
            or log_scan["chunks_completed"] != log_scan["chunks_requested"]
            or recipients_truncated
            or transactions_truncated
            or recipient_code_failures
            or tx_lookup_failures
            or funding_checks_failed
            or funding_histories_truncated
            or funding_wallets_checked != len(funding_candidates)
        ):
            status = "partial"

        measured_shares = [
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
            "analysis_version": self.analysis_version,
            "chain": "robinhood",
            "contract_address": token,
            "pair_address": pair,
            "analysis_scope": "exact_pair_outflows_in_bounded_launch_blocks",
            "launch_block_start": start_block,
            "launch_block_end": end_block,
            "launch_block_limit": self.launch_block_limit,
            "log_chunks_requested": log_scan["chunks_requested"],
            "log_chunks_completed": log_scan["chunks_completed"],
            "transfer_logs_returned": len(log_scan["rows"]),
            "pair_outflows_decoded": len(decoded),
            "first_acquisition_owner_count": len(eoa_records),
            "contract_recipients_excluded": contract_recipients,
            "recipient_sample_truncated": recipients_truncated,
            "transactions_requested": min(len(unique_hashes), self.transaction_limit),
            "transactions_completed": len(tx_records),
            "transaction_sample_truncated": transactions_truncated,
            "funding_wallets_requested": len(funding_candidates),
            "funding_wallets_checked": funding_wallets_checked,
            "funding_checks_failed": funding_checks_failed,
            "funding_histories_truncated": funding_histories_truncated,
            "funding_window_hours": self.funding_window_hours,
            "coverage": {
                "same_block": (
                    "complete"
                    if log_scan["chunks_completed"] == log_scan["chunks_requested"]
                    and not recipients_truncated
                    else "partial"
                ),
                "top_level_sender": (
                    "complete"
                    if not tx_lookup_failures and not transactions_truncated
                    else "partial"
                ),
                "pre_acquisition_funding": (
                    "complete"
                    if funding_wallets_checked == len(funding_candidates)
                    and not funding_checks_failed
                    and not funding_histories_truncated
                    else "partial"
                ),
            },
            "linked_cluster_count": len(clusters),
            "blocking_cluster_count": len(blocking_clusters),
            "largest_cluster_supply_share_pct": (
                max(measured_shares) if measured_shares else None
            ),
            "clusters": clusters[:10],
            "clusters_truncated": len(clusters) > 10,
            "hard_blockers": hard_blockers,
            "flags": flags,
            "warnings": warnings,
            "errors": errors,
            "execution_enabled": False,
            "note": (
                "This bounded check can find observable same-block, transaction-sender, and indexed funding links. It cannot prove separate human ownership or reveal every off-chain relationship."
            ),
        }
