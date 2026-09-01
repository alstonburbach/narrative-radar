import pytest

from app.collectors.bundler_provider import HeliusBundlerProvider


MINT = "9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(
        self,
        *,
        holders,
        supply,
        launch_rows,
        funding_by_wallet,
        launch_truncated=False,
    ):
        self.holders = holders
        self.supply = supply
        self.launch_rows = launch_rows
        self.funding_by_wallet = funding_by_wallet
        self.launch_truncated = launch_truncated
        self.post_calls = []
        self.get_calls = []

    def post(self, url, json, headers, timeout):
        self.post_calls.append((url, json, headers, timeout))
        method = json["method"]
        if method == "getTokenAccounts":
            return Response(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "total": len(self.holders),
                        "token_accounts": self.holders,
                    },
                }
            )
        if method == "getTokenSupply":
            return Response(
                {
                    "jsonrpc": "2.0",
                    "result": {"value": {"amount": str(self.supply), "decimals": 6}},
                }
            )
        if method == "getTransactionsForAddress":
            result = {"data": self.launch_rows}
            if self.launch_truncated:
                result["paginationToken"] = "next"
            return Response(
                {
                    "jsonrpc": "2.0",
                    "result": result,
                }
            )
        raise AssertionError(f"unexpected method: {method}")

    def get(self, url, params, timeout):
        self.get_calls.append((url, params, timeout))
        wallet = url.split("/addresses/", 1)[1].split("/transactions", 1)[0]
        return Response(self.funding_by_wallet.get(wallet, []))


def _holder(owner, amount):
    return {"address": f"ata-{owner}", "owner": owner, "amount": str(amount)}


def _acquisition(owner, amount, *, slot, timestamp, payer, signature):
    return {
        "slot": slot,
        "blockTime": timestamp,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": payer, "signer": True, "writable": True}
                ]
            },
        },
        "meta": {
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "owner": owner,
                    "mint": MINT,
                    "uiTokenAmount": {"amount": str(amount), "decimals": 6},
                }
            ],
        },
    }


def _funding(funder, owner, *, timestamp):
    return [
        {
            "signature": f"fund-{funder}-{owner}",
            "timestamp": timestamp,
            "nativeTransfers": [
                {
                    "fromUserAccount": funder,
                    "toUserAccount": owner,
                    "amount": 20_000_000,
                }
            ],
        }
    ]


def _provider(session):
    return HeliusBundlerProvider(
        api_key="test-key",
        session=session,
        launch_transaction_limit=20,
        holder_account_limit=20,
        funding_wallet_limit=3,
        funding_history_limit=10,
    )


def test_bundler_provider_clears_independent_bounded_launch_activity():
    owners = ["wallet-1", "wallet-2", "wallet-3"]
    session = Session(
        holders=[_holder(owner, 10) for owner in owners],
        supply=1_000,
        launch_rows=[
            _acquisition(
                owner,
                10,
                slot=100 + index,
                timestamp=1_700_000_000 + index,
                payer=owner,
                signature=f"buy-{index}",
            )
            for index, owner in enumerate(owners)
        ],
        funding_by_wallet={
            owner: _funding(f"funder-{index}", owner, timestamp=1_699_999_900)
            for index, owner in enumerate(owners)
        },
    )

    report = _provider(session).fetch(MINT, "solana")

    assert report["status"] == "complete"
    assert report["first_acquisition_owner_count"] == 3
    assert report["funding_wallets_checked"] == 3
    assert report["linked_cluster_count"] == 0
    assert report["hard_blockers"] == []
    assert report["execution_enabled"] is False
    launch_call = [
        call for call in session.post_calls if call[1]["method"] == "getTransactionsForAddress"
    ][0]
    assert launch_call[1]["params"][1]["sortOrder"] == "asc"
    assert launch_call[1]["params"][1]["transactionDetails"] == "full"


def test_shared_pre_acquisition_funder_blocks_concentrated_cluster():
    owners = ["wallet-1", "wallet-2", "wallet-3"]
    session = Session(
        holders=[_holder(owner, 20) for owner in owners],
        supply=1_000,
        launch_rows=[
            _acquisition(
                owner,
                20,
                slot=200 + index,
                timestamp=1_700_000_000 + index,
                payer=owner,
                signature=f"buy-{index}",
            )
            for index, owner in enumerate(owners)
        ],
        funding_by_wallet={
            owner: _funding("shared-funder", owner, timestamp=1_699_999_900)
            for owner in owners
        },
    )

    report = _provider(session).fetch(MINT, "solana")

    assert report["status"] == "complete"
    assert report["blocking_cluster_count"] == 1
    assert report["hard_blockers"] == ["shared_funder_concentration"]
    cluster = report["clusters"][0]
    assert cluster["type"] == "shared_pre_acquisition_funder"
    assert cluster["owner_count"] == 3
    assert cluster["concentration_share_pct"] == 6.0
    assert cluster["hard_blocker"] is True
    assert report["flags"][0]["severity"] == "high"


def test_shared_fee_payer_blocks_without_claiming_shared_ownership():
    owners = ["wallet-1", "wallet-2", "wallet-3"]
    session = Session(
        holders=[_holder(owner, 20) for owner in owners],
        supply=1_000,
        launch_rows=[
            _acquisition(
                owner,
                20,
                slot=300 + index,
                timestamp=1_700_000_000 + index,
                payer="shared-payer",
                signature=f"buy-{index}",
            )
            for index, owner in enumerate(owners)
        ],
        funding_by_wallet={
            owner: _funding(f"funder-{index}", owner, timestamp=1_699_999_900)
            for index, owner in enumerate(owners)
        },
    )

    report = _provider(session).fetch(MINT, "solana")

    assert "shared_fee_payer_concentration" in report["hard_blockers"]
    cluster = next(
        item for item in report["clusters"] if item["type"] == "shared_fee_payer"
    )
    assert cluster["concentration_share_pct"] == 6.0
    assert "not proof" in report["note"]


def test_truncated_launch_window_with_too_few_owners_stays_partial():
    owners = ["wallet-1", "wallet-2", "wallet-3"]
    session = Session(
        holders=[_holder(owner, 10) for owner in owners],
        supply=1_000,
        launch_rows=[
            _acquisition(
                owner,
                10,
                slot=400 + index,
                timestamp=1_700_000_000 + index,
                payer=owner,
                signature=f"buy-{index}",
            )
            for index, owner in enumerate(owners)
        ],
        funding_by_wallet={
            owner: _funding(f"funder-{index}", owner, timestamp=1_699_999_900)
            for index, owner in enumerate(owners)
        },
        launch_truncated=True,
    )

    report = _provider(session).fetch(MINT, "solana")

    assert report["status"] == "partial"
    assert report["launch_scan_truncated"] is True
    assert report["hard_blockers"] == []
    assert any("earliest bounded" in warning for warning in report["warnings"])


def test_bundler_provider_requires_key_and_redacts_it_from_failures(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="HELIUS_API_KEY"):
        HeliusBundlerProvider()

    class FailingSession:
        def post(self, url, json, headers, timeout):
            raise RuntimeError(url)

    report = HeliusBundlerProvider(
        api_key="super-secret-key",
        session=FailingSession(),
    ).fetch(MINT, "solana")
    serialized_errors = " ".join(report["errors"])

    assert report["status"] == "failed"
    assert "super-secret-key" not in serialized_errors
    assert "[redacted]" in serialized_errors
