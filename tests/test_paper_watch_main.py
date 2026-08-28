from app.github_issue_paper import render_paper_signal_report
from app.paper_signal import create_paper_signal_state
from app.paper_watch_main import run_watch


def _state():
    return create_paper_signal_state(
        {
            "contract_address": "0x1111111111111111111111111111111111111111",
            "chain": "base",
            "stake_usd": 50,
            "target_multiple": 10,
        },
        {
            "market": {
                "found": True,
                "market_cap": 100_000,
                "chain": "base",
                "token_name": "Signal",
                "token_symbol": "SIG",
                "collected_at": "2026-08-01T12:01:00Z",
            },
            "decision_gate": {"status": "research_only"},
            "narrative_quality": {},
            "score": {},
            "red_team": {},
        },
        issue_number=4,
        issue_created_at="2026-08-01T12:00:00Z",
    )


def test_watch_updates_comment_and_emits_only_new_milestone(monkeypatch):
    state = _state()
    monkeypatch.setattr(
        "app.paper_watch_main.fetch_market_data",
        lambda contract, chain: {
            "found": True,
            "chain": "base",
            "market_cap": 250_000,
            "collected_at": "2026-08-01T13:00:00Z",
        },
    )

    result = run_watch(
        {
            "signals": [
                {
                    "issue_number": 4,
                    "comment_id": 99,
                    "body": render_paper_signal_report(state),
                }
            ]
        }
    )

    assert result["status"] == "complete"
    assert result["execution_enabled"] is False
    assert result["aggregate"]["gross_sampled_value_usd"] == 125
    assert result["updates"][0]["comment_id"] == 99
    assert result["updates"][0]["notification"]["multiple"] == 2
    assert "scheduled snapshot" in result["updates"][0]["alert_body"]
    assert "narrative-radar-paper-state:" in result["updates"][0]["body"]


def test_watch_isolates_a_mismatched_issue_state():
    state = _state()
    result = run_watch(
        {
            "signals": [
                {
                    "issue_number": 5,
                    "comment_id": 99,
                    "body": render_paper_signal_report(state),
                }
            ]
        }
    )

    assert result["status"] == "partial"
    assert result["updates"] == []
    assert result["errors"][0]["error_type"] == "ValueError"
    assert result["execution_enabled"] is False
