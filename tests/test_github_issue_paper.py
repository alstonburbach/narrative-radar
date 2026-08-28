import base64
import json

import pytest

from app.github_issue_paper import (
    encode_paper_state,
    extract_paper_state,
    parse_paper_signal_request,
    render_paper_signal_report,
    validate_owner_paper_event,
)
from app.paper_signal import create_paper_signal_state


CONTRACT = "0x1111111111111111111111111111111111111111"


def _body(stake="50", target="10", chain="base"):
    return f"""### Contract address

{CONTRACT}

### Chain

{chain}

### Paper stake USD

{stake}

### Target multiple

{target}

### Narrative family

AI agents | early

### Signal source

Narrative Radar
"""


def _event(login="owner", title="[RADAR PAPER] SIG"):
    return {
        "repository": {"owner": {"login": "owner"}},
        "issue": {
            "number": 7,
            "title": title,
            "body": _body(),
            "created_at": "2026-08-01T12:00:00Z",
            "user": {"login": login},
        },
    }


def _state():
    return create_paper_signal_state(
        parse_paper_signal_request(_body()),
        {
            "market": {
                "found": True,
                "market_cap": 100_000,
                "chain": "base",
                "token_name": "Signal",
                "token_symbol": "SIG",
                "collected_at": "2026-08-01T12:01:00Z",
                "dex_url": "https://dexscreener.com/base/pair",
            },
            "decision_gate": {"status": "blocked"},
            "narrative_quality": {"quality_score": 10},
            "score": {"radar_score": 15},
            "red_team": {"risk_level": "high"},
        },
        issue_number=7,
        issue_created_at="2026-08-01T12:00:00Z",
    )


def test_parse_bounded_owner_paper_request():
    request = validate_owner_paper_event(_event())

    assert request["contract_address"] == CONTRACT
    assert request["chain"] == "base"
    assert request["stake_usd"] == 50
    assert request["target_multiple"] == 10
    assert request["signal_source"] == "narrative_radar"


@pytest.mark.parametrize(
    ("login", "title"),
    [("outsider", "[RADAR PAPER] SIG"), ("owner", "Paper SIG")],
)
def test_non_owner_or_wrong_title_fails_closed(login, title):
    with pytest.raises(ValueError):
        validate_owner_paper_event(_event(login=login, title=title))


@pytest.mark.parametrize(
    "body",
    [_body(stake="0"), _body(stake="100001"), _body(target="1"), _body(chain="solana")],
)
def test_invalid_amounts_or_chain_contract_mismatch_are_rejected(body):
    with pytest.raises(ValueError):
        parse_paper_signal_request(body)


def test_machine_state_round_trips_and_report_keeps_execution_off():
    state = _state()
    encoded = encode_paper_state(state)
    report = render_paper_signal_report(state)

    assert extract_paper_state(
        f"prefix <!-- narrative-radar-paper-state:{encoded} --> suffix"
    ) == state
    assert "Execution enabled | `False`" in report
    assert "AI agents \\| early" in report
    assert "No transaction was created" in report


def test_tampered_execution_state_is_rejected():
    state = _state()
    state["execution_enabled"] = True
    payload = json.dumps(state, separators=(",", ":")).encode()
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    with pytest.raises(ValueError, match="execution boundary"):
        extract_paper_state(f"<!-- narrative-radar-paper-state:{token} -->")
