import requests

from app.collectors.token_security import GoPlusTokenSecurityProvider


CONTRACT = "0x1111111111111111111111111111111111111111"
SOLANA_MINT = "9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump"


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def _evm_payload(**overrides):
    item = {
        "is_open_source": "1",
        "is_honeypot": "0",
        "cannot_buy": "0",
        "cannot_sell_all": "0",
        "is_proxy": "0",
        "hidden_owner": "0",
        "selfdestruct": "0",
        "can_take_back_ownership": "0",
        "owner_change_balance": "0",
        "slippage_modifiable": "0",
        "personal_slippage_modifiable": "0",
        "transfer_pausable": "0",
        "is_blacklisted": "0",
        "is_mintable": "0",
        "buy_tax": "0.01",
        "sell_tax": "0.01",
        "is_in_dex": "1",
        "holder_count": "500",
        "holders": [
            {"percent": "0.05", "is_locked": "0", "tag": ""},
            {"percent": "0.04", "is_locked": "0", "tag": ""},
        ],
        "lp_holder_count": "1",
        "lp_holders": [
            {"percent": "1", "is_locked": "1", "tag": "Locker"},
        ],
        "creator_percent": "0.01",
    }
    item.update(overrides)
    return {"code": 1, "message": "OK", "result": {CONTRACT: item}}


def test_safe_evm_report_normalizes_taxes_holders_and_locked_lp():
    session = Session(_evm_payload())
    report = GoPlusTokenSecurityProvider(session=session).fetch(CONTRACT, "base")

    assert report["status"] == "complete"
    assert report["risk_level"] == "low"
    assert report["buy_tax_pct"] == 1
    assert report["sell_tax_pct"] == 1
    assert report["holder_distribution"]["largest_unlocked_unexcluded_share_pct"] == 5
    assert report["lp_distribution"]["top_unlocked_unexcluded_share_pct"] is None
    assert report["hard_blockers"] == []
    assert report["promotion_eligible"] is True
    assert report["bundler_analysis"]["status"] == "not_available"
    assert report["execution_enabled"] is False
    assert session.calls[0][0].endswith("/8453")
    assert session.calls[0][1]["params"] == {"contract_addresses": CONTRACT}


def test_evm_honeypot_admin_tax_concentration_and_unlocked_lp_block():
    payload = _evm_payload(
        is_honeypot="1",
        hidden_owner="1",
        sell_tax="0.6",
        holders=[{"percent": "0.8", "is_locked": "0", "tag": ""}],
        lp_holders=[{"percent": "0.8", "is_locked": "0", "tag": ""}],
    )
    report = GoPlusTokenSecurityProvider(session=Session(payload)).fetch(
        CONTRACT, "bsc"
    )
    blockers = set(report["hard_blockers"])

    assert report["risk_level"] == "critical"
    assert "honeypot_detected" in blockers
    assert "hidden_owner" in blockers
    assert "prohibitive_sell_tax" in blockers
    assert "single_holder_concentration" in blockers
    assert "unlocked_lp_concentration" in blockers
    assert report["promotion_eligible"] is False


def test_solana_authorities_and_holder_concentration_block_promotion():
    payload = {
        "code": 1,
        "message": "ok",
        "result": {
            SOLANA_MINT: {
                "trusted_token": 0,
                "mintable": {"status": "1", "authority": ["creator"]},
                "freezable": {"status": "0", "authority": []},
                "closable": {"status": "0", "authority": []},
                "balance_mutable_authority": {"status": "0", "authority": []},
                "holders": [
                    {"percent": "0.75", "is_locked": 0, "tag": ""},
                ],
                "holder_count": "100",
            }
        },
    }
    report = GoPlusTokenSecurityProvider(session=Session(payload)).fetch(
        SOLANA_MINT, "solana"
    )

    assert report["risk_level"] == "high"
    assert "mint_authority_active" in report["hard_blockers"]
    assert "single_holder_concentration" in report["hard_blockers"]
    assert report["promotion_eligible"] is False


def test_unsupported_chain_and_missing_provider_data_fail_closed():
    provider = GoPlusTokenSecurityProvider(session=Session({"code": 1, "result": {}}))

    unsupported = provider.fetch(CONTRACT, "arbitrum")
    missing = provider.fetch(CONTRACT, "ethereum")

    assert unsupported["status"] == "unsupported_chain"
    assert unsupported["promotion_eligible"] is False
    assert missing["status"] == "no_data"
    assert missing["hard_blockers"] == ["token_security_no_data"]
