import pytest

from app.github_issue_scan import (
    parse_issue_scan_request,
    render_issue_error,
    render_issue_report,
    validate_owner_event,
)

BODY = """### Contract address

9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump

### Chain

solana

### Paper position size USD

50

### Manual review order size USD

$25
"""


def test_issue_form_parses_a_safe_phone_scan_request():
    request = parse_issue_scan_request(BODY)

    assert request == {
        "contract_address": "9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump",
        "chain": "solana",
        "paper_usd": 50.0,
        "order_preview_usd": 25.0,
        "order_side": "buy",
    }


def test_issue_event_is_owner_only_and_requires_radar_title():
    event = {
        "repository": {"owner": {"login": "alstonburbach"}},
        "issue": {
            "user": {"login": "alstonburbach"},
            "title": "[RADAR SCAN] token",
            "body": BODY,
        },
    }

    assert validate_owner_event(event)["chain"] == "solana"

    event["issue"]["user"]["login"] = "someone-else"
    with pytest.raises(ValueError, match="repository owner"):
        validate_owner_event(event)


def test_issue_request_rejects_chain_address_mismatch_and_invalid_amount():
    mismatch = BODY.replace("solana", "base")
    with pytest.raises(ValueError, match="EVM 0x address"):
        parse_issue_scan_request(mismatch)

    invalid_amount = BODY.replace("$25", "all in")
    with pytest.raises(ValueError, match="positive number"):
        parse_issue_scan_request(invalid_amount)


def test_phone_report_surfaces_gate_risk_and_disabled_execution():
    report = {
        "market": {
            "token_name": "Test Token",
            "token_symbol": "TEST",
            "chain": "solana",
            "dex": "raydium",
            "market_cap": 250_000,
            "liquidity_usd": 50_000,
            "volume_24h": 125_000,
            "dex_url": "https://dexscreener.com/solana/pair",
        },
        "score": {"radar_score": 62, "rating": "watch"},
        "narrative_quality": {
            "quality_score": 72,
            "classification": "corroborated_leads",
            "independent_domain_count": 3,
        },
        "red_team": {
            "risk_level": "medium",
            "flags": [{"severity": "medium", "message": "Review concentration."}],
        },
        "decision_gate": {
            "status": "manual_review_ready",
            "failed_requirements": [],
            "requirements": [],
        },
        "order_preview": {
            "status": "ready_for_manual_review",
            "notional_usd": 50,
            "estimated_token_amount": 1000,
            "snapshot_age_seconds": 5,
            "manual_approval_required": True,
            "execution_enabled": False,
            "checks": [],
        },
        "research": {"error": None},
        "onchain_activity": {"status": "not_requested"},
        "narrative": {"verified_evidence": [], "uncertain_evidence": []},
    }

    markdown = render_issue_report(report)

    assert "Manual Review Ready" in markdown
    assert "$250.0K" in markdown
    assert "Review concentration" in markdown
    assert "Execution enabled: `False`" in markdown
    assert "No transaction was created" in markdown


def test_error_report_preserves_the_no_execution_boundary():
    markdown = render_issue_error("Bad contract.")

    assert "Bad contract" in markdown
    assert "No transaction was created" in markdown
