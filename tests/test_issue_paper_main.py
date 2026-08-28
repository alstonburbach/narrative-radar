import json

import app.issue_paper_main as issue_paper_main


CONTRACT = "0x1111111111111111111111111111111111111111"


def _event():
    return {
        "repository": {"owner": {"login": "owner"}},
        "issue": {
            "number": 9,
            "title": "[RADAR PAPER] Signal",
            "created_at": "2026-08-01T12:00:00Z",
            "user": {"login": "owner"},
            "body": f"""### Contract address

{CONTRACT}

### Chain

base

### Paper stake USD

50

### Target multiple

10

### Narrative family

payments

### Signal source

Narrative Radar
""",
        },
    }


def _analysis():
    return {
        "status": "complete",
        "started_at": "2026-08-01T12:01:00Z",
        "market": {
            "found": True,
            "market_cap": 100_000,
            "chain": "base",
            "token_name": "Signal",
            "token_symbol": "SIG",
            "collected_at": "2026-08-01T12:01:00Z",
        },
        "decision_gate": {"status": "research_only"},
        "narrative_quality": {"quality_score": 30},
        "score": {"radar_score": 25},
        "red_team": {"risk_level": "high"},
        "research": {"error": None},
    }


def test_issue_main_freezes_then_preserves_existing_entry(tmp_path, monkeypatch):
    event_path = tmp_path / "event.json"
    json_path = tmp_path / "paper.json"
    markdown_path = tmp_path / "paper.md"
    existing_path = tmp_path / "existing.md"
    event_path.write_text(json.dumps(_event()), encoding="utf-8")
    monkeypatch.setattr(issue_paper_main, "run_analysis", lambda **kwargs: _analysis())
    monkeypatch.setattr(
        issue_paper_main,
        "_research_provider_or_none",
        lambda: (None, None),
    )

    exit_code = issue_paper_main.main(
        [
            "--event",
            str(event_path),
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--no-persist",
        ]
    )

    assert exit_code == 0
    first = json.loads(json_path.read_text(encoding="utf-8"))
    assert first["status"] == "paper_signal_started"
    assert first["state"]["entry_market_cap"] == 100_000
    assert first["execution_enabled"] is False
    existing_path.write_text(markdown_path.read_text(encoding="utf-8"), encoding="utf-8")

    def should_not_reenter(**kwargs):
        raise AssertionError("rerun must not create a later paper entry")

    monkeypatch.setattr(issue_paper_main, "run_analysis", should_not_reenter)
    exit_code = issue_paper_main.main(
        [
            "--event",
            str(event_path),
            "--existing-comment",
            str(existing_path),
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--no-persist",
        ]
    )

    preserved = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert preserved["status"] == "existing_entry_preserved"
    assert preserved["state"]["entry_recorded_at"] == first["state"]["entry_recorded_at"]
    assert preserved["execution_enabled"] is False
