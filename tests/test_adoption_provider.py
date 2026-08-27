from datetime import datetime, timezone

import pytest

from app.collectors.adoption_provider import HeliusAdoptionProvider


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers, timeout))
        method = json["method"]
        return Response(self.payloads[method])


def _balance(account_index, owner, amount, mint="MINT"):
    return {
        "accountIndex": account_index,
        "owner": owner,
        "mint": mint,
        "uiTokenAmount": {"amount": str(amount), "decimals": 6},
    }


def test_helius_adoption_provider_collects_holders_supply_and_bounded_activity():
    session = Session(
        {
            "getTokenAccounts": {
                "jsonrpc": "2.0",
                "result": {
                    "last_indexed_slot": 123,
                    "total": 2,
                    "token_accounts": [
                        {"address": "ata-1", "mint": "MINT", "owner": "wallet-1", "amount": 100},
                        {"address": "ata-2", "mint": "MINT", "owner": "wallet-1", "amount": 25},
                    ],
                },
            },
            "getTokenSupply": {
                "jsonrpc": "2.0",
                "result": {
                    "value": {"amount": "125", "decimals": 6, "uiAmount": 0.000125}
                },
            },
            "getTransactionsForAddress": {
                "jsonrpc": "2.0",
                "result": {
                    "data": [
                        {
                            "meta": {
                                "preTokenBalances": [
                                    _balance(1, "wallet-1", 100),
                                    _balance(2, "wallet-2", 50),
                                ],
                                "postTokenBalances": [
                                    _balance(1, "wallet-1", 120),
                                    _balance(2, "wallet-2", 30),
                                ],
                            }
                        },
                        {
                            "meta": {
                                "preTokenBalances": [],
                                "postTokenBalances": [_balance(3, "wallet-3", 10)],
                            }
                        },
                    ],
                    "paginationToken": "next-page",
                },
            },
        }
    )
    provider = HeliusAdoptionProvider(
        api_key="test-key",
        session=session,
        clock=lambda: datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    snapshot = provider.fetch_snapshot(
        "MINT",
        chain="solana",
        holder_limit=10,
        transfer_limit=2,
        activity_window_hours=24,
    )

    assert snapshot["status"] == "complete"
    assert snapshot["holder_count"] == 1
    assert snapshot["token_account_count"] == 2
    assert snapshot["holder_scan_complete"] is True
    assert snapshot["token_supply"] == 0.000125
    assert snapshot["scanned_supply_coverage_pct"] == 100.0
    assert snapshot["largest_scanned_owner_share_pct"] == 100.0
    assert snapshot["top_10_scanned_owner_share_pct"] == 100.0
    assert snapshot["holder_concentration_is_lower_bound"] is False
    assert snapshot["transfer_transaction_count_24h"] == 2
    assert snapshot["transfer_event_count_24h"] == 3
    assert snapshot["unique_active_wallets_24h"] == 3
    assert snapshot["unique_inflow_wallets_24h"] == 2
    assert snapshot["unique_outflow_wallets_24h"] == 1
    assert snapshot["transfer_scan_truncated"] is True
    assert any("lower bound" in warning for warning in snapshot["warnings"])
    assert [call[1]["method"] for call in session.calls] == [
        "getTokenAccounts",
        "getTokenSupply",
        "getTransactionsForAddress",
    ]
    transfer_call = session.calls[-1][1]
    assert transfer_call["params"][0] == "MINT"
    assert transfer_call["params"][1]["filters"]["tokenTransfer"]["mint"] == "MINT"


def test_helius_adoption_provider_fails_closed_for_unsupported_chain():
    provider = HeliusAdoptionProvider(api_key="test-key", session=Session({}))

    snapshot = provider.fetch_snapshot("MINT", chain="base")

    assert snapshot["status"] == "unsupported_chain"
    assert snapshot["holder_count"] is None


def test_helius_adoption_provider_requires_a_key(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="HELIUS_API_KEY"):
        HeliusAdoptionProvider()
