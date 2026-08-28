import pytest
import requests

from app.collectors.wallet_provider import HeliusWalletProvider


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.request_params = None

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_helius_provider_paginates_and_uses_finalized_token_accounts(monkeypatch):
    calls = []
    pages = [
        [{"signature": "newest"}, {"signature": "older"}],
        [{"signature": "oldest"}],
    ]

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return Response(pages[len(calls) - 1])

    monkeypatch.setattr("requests.get", fake_get)
    provider = HeliusWalletProvider(api_key="test-key")
    result = provider.fetch_history("wallet", max_transactions=3)

    assert [item["signature"] for item in result] == ["newest", "older", "oldest"]
    assert calls[0][1]["commitment"] == "finalized"
    assert calls[0][1]["token-accounts"] == "balanceChanged"
    assert calls[1][1]["before-signature"] == "older"


def test_helius_provider_does_not_leak_key_in_request_errors(monkeypatch):
    def failed_get(url, params, timeout):
        request = requests.Request("GET", url, params=params).prepare()
        response = requests.Response()
        response.status_code = 401
        response.request = request
        raise requests.HTTPError(
            f"401 Client Error for url: {request.url}",
            response=response,
        )

    monkeypatch.setattr("requests.get", failed_get)
    provider = HeliusWalletProvider(api_key="super-secret-key")

    with pytest.raises(RuntimeError) as error:
        provider.fetch_page("wallet")

    assert "super-secret-key" not in str(error.value)
    assert "HTTP 401" in str(error.value)
