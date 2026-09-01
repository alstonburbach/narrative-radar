import pytest
import requests

from app.collectors.evm_bundler_provider import (
    RobinhoodBundlerProvider,
    TRANSFER_TOPIC,
)


TOKEN = "0x1111111111111111111111111111111111111111"
PAIR = "0x2222222222222222222222222222222222222222"
NO_CODE_PAIR = "0x3333333333333333333333333333333333333333"
POOL_ID = "0x" + "ab" * 32
CONTRACT_RECIPIENT = "0x4444444444444444444444444444444444444444"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEAD_ADDRESS = "0x000000000000000000000000000000000000dead"
OWNERS = [f"0x{index:040x}" for index in range(100, 110)]
FUNDERS = [f"0x{index:040x}" for index in range(200, 210)]
CREATED_AT = 1_700_000_100_000


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class HttpErrorResponse(Response):
    def __init__(self, status_code, payload=None):
        super().__init__(payload or {})
        self.status_code = status_code

    def raise_for_status(self):
        raise requests.HTTPError(
            f"HTTP {self.status_code}",
            response=self,
        )


class RpcSequenceSession:
    def __init__(self, events):
        self.events = list(events)
        self.post_calls = []

    def post(self, url, json, headers, timeout):
        self.post_calls.append((url, json, headers, timeout))
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def _topic(address):
    return "0x" + "0" * 24 + address[2:]


def _log(
    owner,
    amount,
    *,
    block,
    tx_hash,
    tx_index=0,
    log_index=0,
    sender=PAIR,
):
    return {
        "address": TOKEN,
        "topics": [TRANSFER_TOPIC, _topic(sender), _topic(owner)],
        "data": hex(amount),
        "blockNumber": hex(block),
        "transactionHash": tx_hash,
        "transactionIndex": hex(tx_index),
        "logIndex": hex(log_index),
        "removed": False,
    }


def _funding_row(funder, owner, *, timestamp, block=99):
    return {
        "from": funder,
        "to": owner,
        "value": str(200_000_000_000_000),
        "timeStamp": str(timestamp),
        "blockNumber": str(block),
        "hash": f"0xfund{funder[-4:]}{owner[-4:]}",
    }


class Session:
    def __init__(
        self,
        *,
        logs,
        transactions,
        funding_by_wallet,
        supply=1_000,
        chain_id="0x1237",
        fail_funding_for=None,
        contract_addresses=None,
    ):
        self.logs = logs
        self.transactions = transactions
        self.funding_by_wallet = funding_by_wallet
        self.supply = supply
        self.chain_id = chain_id
        self.fail_funding_for = set(fail_funding_for or [])
        self.contract_addresses = {
            address.lower() for address in (contract_addresses or [])
        }
        self.post_calls = []
        self.get_calls = []

    def post(self, url, json, headers, timeout):
        self.post_calls.append((url, json, headers, timeout))
        method = json["method"]
        params = json["params"]
        if method == "eth_chainId":
            result = self.chain_id
        elif method == "eth_getCode":
            result = (
                "0x6000"
                if params[0].lower()
                in {TOKEN, PAIR} | self.contract_addresses
                else "0x"
            )
        elif method == "eth_blockNumber":
            result = hex(200)
        elif method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            result = {
                "number": hex(number),
                "timestamp": hex(1_700_000_000 + number),
            }
        elif method == "eth_getLogs":
            start = int(params[0]["fromBlock"], 16)
            end = int(params[0]["toBlock"], 16)
            result = [
                row
                for row in self.logs
                if start <= int(row["blockNumber"], 16) <= end
            ]
        elif method == "eth_call":
            result = hex(self.supply)
        elif method == "eth_getTransactionByHash":
            result = self.transactions.get(params[0])
        else:
            raise AssertionError(f"unexpected method: {method}")
        return Response({"jsonrpc": "2.0", "id": 1, "result": result})

    def get(self, url, params, timeout):
        self.get_calls.append((url, params, timeout))
        wallet = params["address"].lower()
        if wallet in self.fail_funding_for:
            return Response({"status": "0", "message": "rate limit", "result": "error"})
        rows = self.funding_by_wallet.get(wallet, []) if params["action"] == "txlist" else []
        return Response({"status": "1", "message": "OK", "result": rows})


def _tx_hash(index):
    return "0x" + f"{index:064x}"


def _session(*, blocks, amounts, shared_funder=None, same_sender=False, fail_funding_for=None):
    logs = []
    transactions = {}
    funding = {}
    for index, (owner, block, amount) in enumerate(zip(OWNERS, blocks, amounts), start=1):
        tx_hash = _tx_hash(index)
        logs.append(
            _log(owner, amount, block=block, tx_hash=tx_hash, log_index=index)
        )
        transactions[tx_hash] = {
            "hash": tx_hash,
            "from": OWNERS[-1] if same_sender else owner,
        }
        funder = shared_funder or FUNDERS[index - 1]
        funding[owner] = [
            _funding_row(
                funder,
                owner,
                timestamp=1_700_000_000 + block - 10,
                block=block - 1,
            )
        ]
    return Session(
        logs=logs,
        transactions=transactions,
        funding_by_wallet=funding,
        fail_funding_for=fail_funding_for,
    )


def _provider(session, **kwargs):
    return RobinhoodBundlerProvider(
        rpc_url="https://rpc.example",
        blockscout_api_url="https://explorer.example/api/",
        session=session,
        launch_block_limit=20,
        log_chunk_size=10,
        funding_wallet_limit=12,
        **kwargs,
    )


@pytest.mark.parametrize(
    "first_failure",
    [
        requests.ConnectionError("connection reset"),
        requests.Timeout("timed out"),
        HttpErrorResponse(429),
        HttpErrorResponse(503),
    ],
)
def test_rpc_retries_one_transient_failure_then_succeeds(first_failure):
    session = RpcSequenceSession(
        [
            first_failure,
            Response({"jsonrpc": "2.0", "id": 1, "result": "0x1237"}),
        ]
    )
    provider = _provider(session, rpc_retry_backoff_seconds=0)

    assert provider._rpc("eth_chainId", []) == "0x1237"
    assert len(session.post_calls) == 2


def test_rpc_retry_is_bounded_and_fails_closed_after_second_503():
    session = RpcSequenceSession(
        [HttpErrorResponse(503), HttpErrorResponse(503)]
    )
    provider = _provider(session, rpc_retry_backoff_seconds=0)

    report = provider.fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "failed"
    assert "HTTP 503" in report["errors"][0]
    assert len(session.post_calls) == 2


def test_rpc_does_not_retry_non_transient_http_or_json_rpc_errors():
    http_session = RpcSequenceSession([HttpErrorResponse(400)])
    provider = _provider(http_session, rpc_retry_backoff_seconds=0)

    with pytest.raises(RuntimeError, match="HTTP 400"):
        provider._rpc("eth_chainId", [])
    assert len(http_session.post_calls) == 1

    json_rpc_session = RpcSequenceSession(
        [
            Response(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32602, "message": "invalid params"},
                }
            )
        ]
    )
    provider = _provider(json_rpc_session, rpc_retry_backoff_seconds=0)

    with pytest.raises(RuntimeError, match="invalid params"):
        provider._rpc("eth_chainId", [])
    assert len(json_rpc_session.post_calls) == 1


def test_robinhood_provider_completes_independent_bounded_evidence():
    session = _session(blocks=[101, 103, 105], amounts=[10, 10, 10])

    report = _provider(session).fetch(
        TOKEN,
        "robinhood",
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert report["analysis_version"] == "robinhood-links-v1"
    assert report["first_acquisition_owner_count"] == 3
    assert report["funding_wallets_checked"] == 3
    assert report["coverage"] == {
        "same_block": "complete",
        "top_level_sender": "complete",
        "pre_acquisition_funding": "complete",
    }
    assert report["hard_blockers"] == []
    assert report["execution_enabled"] is False
    assert report["launch_block_end"] - report["launch_block_start"] + 1 == 20
    log_calls = [call for call in session.post_calls if call[1]["method"] == "eth_getLogs"]
    assert len(log_calls) == 2
    assert all(
        int(call[1]["params"][0]["toBlock"], 16)
        - int(call[1]["params"][0]["fromBlock"], 16)
        <= 9
        for call in log_calls
    )


def test_bytes32_pool_id_uses_bounded_token_transfer_fallback():
    session = _session(blocks=[101, 103, 105], amounts=[10, 10, 10])

    report = _provider(session).fetch(
        TOKEN,
        "robinhood",
        pair_address=POOL_ID,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert report["pair_address"] == POOL_ID
    assert report["pair_identifier_kind"] == "bytes32_pool_identifier"
    assert report["analysis_method"] == (
        "bounded_token_transfer_first_recipients_fallback"
    )
    assert report["analysis_scope"] == (
        "bounded_token_transfer_recipients_in_launch_blocks_without_exact_pair_attribution"
    )
    assert report["fallback_reason"] == (
        "pair_identifier_is_not_a_20_byte_contract"
    )
    assert report["pair_outflows_decoded"] == 0
    assert report["first_acquisition_owner_count"] is None
    assert report["launch_window_recipient_count"] == 3
    assert report["coverage"] == {
        "same_block": "complete",
        "top_level_sender": "complete",
        "pre_acquisition_funding": "complete",
    }
    assert "cannot attribute" in report["note"]
    code_targets = [
        call[1]["params"][0].lower()
        for call in session.post_calls
        if call[1]["method"] == "eth_getCode"
    ]
    assert POOL_ID not in code_targets


def test_fallback_excludes_mints_dead_token_self_and_contract_recipients():
    valid_logs = [
        _log(
            owner,
            10,
            block=101 + index * 2,
            tx_hash=_tx_hash(20 + index),
            log_index=20 + index,
            sender=FUNDERS[index],
        )
        for index, owner in enumerate(OWNERS[:3])
    ]
    excluded_logs = [
        _log(
            OWNERS[0],
            900,
            block=100,
            tx_hash=_tx_hash(30),
            log_index=30,
            sender=ZERO_ADDRESS,
        ),
        _log(
            DEAD_ADDRESS,
            900,
            block=100,
            tx_hash=_tx_hash(31),
            log_index=31,
            sender=FUNDERS[3],
        ),
        _log(
            TOKEN,
            900,
            block=100,
            tx_hash=_tx_hash(32),
            log_index=32,
            sender=FUNDERS[4],
        ),
        _log(
            OWNERS[3],
            900,
            block=100,
            tx_hash=_tx_hash(33),
            log_index=33,
            sender=OWNERS[3],
        ),
        _log(
            CONTRACT_RECIPIENT,
            900,
            block=100,
            tx_hash=_tx_hash(34),
            log_index=34,
            sender=FUNDERS[5],
        ),
    ]
    transactions = {
        row["transactionHash"]: {
            "hash": row["transactionHash"],
            "from": FUNDERS[index],
        }
        for index, row in enumerate(valid_logs)
    }
    transactions[_tx_hash(34)] = {
        "hash": _tx_hash(34),
        "from": FUNDERS[5],
    }
    funding = {
        owner: [
            _funding_row(
                FUNDERS[index],
                owner,
                timestamp=1_700_000_080 + index * 2,
                block=100 + index * 2,
            )
        ]
        for index, owner in enumerate(OWNERS[:3])
    }
    session = Session(
        logs=excluded_logs + valid_logs,
        transactions=transactions,
        funding_by_wallet=funding,
        contract_addresses={CONTRACT_RECIPIENT},
    )

    report = _provider(session).fetch(
        TOKEN,
        pair_address=POOL_ID,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert report["transfer_logs_returned"] == 8
    assert report["launch_window_transfers_decoded"] == 4
    assert report["launch_window_recipient_count"] == 3
    assert report["contract_recipients_excluded"] == 1
    observed_wallets = {
        wallet for cluster in report["clusters"] for wallet in cluster["wallets"]
    }
    assert DEAD_ADDRESS not in observed_wallets
    assert TOKEN not in observed_wallets
    assert OWNERS[3] not in observed_wallets
    assert CONTRACT_RECIPIENT not in observed_wallets


def test_missing_pair_bytecode_fallback_stays_partial_when_history_is_missing():
    session = _session(
        blocks=[101, 103, 105],
        amounts=[10, 10, 10],
        fail_funding_for={OWNERS[1]},
    )
    for row in session.logs:
        row["topics"][1] = _topic(NO_CODE_PAIR)

    report = _provider(session).fetch(
        TOKEN,
        pair_address=NO_CODE_PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "partial"
    assert report["pair_identifier_kind"] == "evm_address_without_bytecode"
    assert report["fallback_reason"] == "pair_address_has_no_deployed_bytecode"
    assert report["coverage"]["same_block"] == "complete"
    assert report["coverage"]["top_level_sender"] == "complete"
    assert report["coverage"]["pre_acquisition_funding"] == "partial"
    assert report["funding_checks_failed"] == 1
    assert report["hard_blockers"] == []


def test_exact_pair_mode_ignores_other_token_transfers_unchanged():
    session = _session(blocks=[101, 103, 105], amounts=[10, 10, 10])
    session.logs.append(
        _log(
            OWNERS[8],
            900,
            block=101,
            tx_hash=_tx_hash(90),
            log_index=90,
            sender=FUNDERS[8],
        )
    )

    report = _provider(session).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert report["analysis_method"] == "exact_pair_outflow_first_recipients"
    assert report["analysis_scope"] == (
        "exact_pair_outflows_in_bounded_launch_blocks"
    )
    assert report["fallback_reason"] is None
    assert report["pair_outflows_decoded"] == 3
    assert report["launch_window_transfers_decoded"] == 3
    assert report["first_acquisition_owner_count"] == 3
    assert report["launch_window_recipient_count"] == 3


def test_five_wallet_ten_percent_same_block_cluster_blocks():
    session = _session(
        blocks=[101, 101, 101, 101, 101],
        amounts=[20, 20, 20, 20, 20],
    )

    report = _provider(session).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert "same_block_acquisition_concentration" in report["hard_blockers"]
    cluster = next(
        item for item in report["clusters"] if item["type"] == "same_block_first_acquisition"
    )
    assert cluster["owner_count"] == 5
    assert cluster["concentration_share_pct"] == 10.0
    assert cluster["hard_blocker"] is True


def test_shared_funder_cluster_blocks_at_three_wallets_and_five_percent():
    session = _session(
        blocks=[101, 103, 105],
        amounts=[20, 20, 20],
        shared_funder=FUNDERS[0],
    )

    report = _provider(session).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "complete"
    assert "shared_funder_concentration" in report["hard_blockers"]
    cluster = next(
        item for item in report["clusters"] if item["type"] == "shared_pre_acquisition_funder"
    )
    assert cluster["concentration_share_pct"] == 6.0
    assert "does not prove" in cluster["note"]


def test_funding_provider_gap_returns_partial_not_cleared():
    session = _session(
        blocks=[101, 103, 105],
        amounts=[10, 10, 10],
        fail_funding_for={OWNERS[1]},
    )

    report = _provider(session).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "partial"
    assert report["coverage"]["same_block"] == "complete"
    assert report["coverage"]["pre_acquisition_funding"] == "partial"
    assert report["hard_blockers"] == []
    assert report["funding_checks_failed"] == 1


@pytest.mark.parametrize(
    ("pair", "created", "expected_note"),
    [
        (None, CREATED_AT, "exact DEX pair"),
        (PAIR, None, "creation time"),
    ],
)
def test_missing_launch_bounds_return_insufficient_data(pair, created, expected_note):
    report = _provider(_session(blocks=[], amounts=[])).fetch(
        TOKEN,
        pair_address=pair,
        pair_created_at=created,
    )

    assert report["status"] == "insufficient_data"
    assert expected_note in report["note"]


def test_chain_id_mismatch_fails_closed():
    session = _session(blocks=[101, 103, 105], amounts=[10, 10, 10])
    session.chain_id = "0x1"

    report = _provider(session).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "failed"
    assert "does not match Robinhood" in report["errors"][0]


def test_rpc_url_is_redacted_from_failure():
    class FailingSession:
        def post(self, url, json, headers, timeout):
            raise RuntimeError(url)

    report = RobinhoodBundlerProvider(
        rpc_url="https://secret.example/key-value",
        session=FailingSession(),
    ).fetch(
        TOKEN,
        pair_address=PAIR,
        pair_created_at=CREATED_AT,
    )

    assert report["status"] == "failed"
    assert "secret.example" not in " ".join(report["errors"])
    assert "[redacted]" in " ".join(report["errors"])
