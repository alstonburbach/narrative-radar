import json

import pytest

from app.github_issue_discovery import (
    discovery_notification_state,
    parse_discovery_request,
    render_discovery_error,
    render_discovery_report,
    validate_owner_discovery_event,
)
from app.issue_discovery_main import main

BODY = """### Topic or theme

AI agents and crypto payments

### Chain

solana

### Results per research lens

5
"""


def _report():
    return {
        "started_at": "2026-09-01T14:17:00+00:00",
        "topic": "AI agents and crypto payments",
        "chain": "solana",
        "status": "complete",
        "research_provider": "public_rss",
        "provider_warnings": [],
        "lead_count": 8,
        "independent_domain_count": 3,
        "quality": {
            "quality_score": 62,
            "classification": "corroborated_leads",
            "freshness": {"recent_count": 6},
            "warnings": ["Counterevidence requires review."],
        },
        "candidate_signals": [
            {
                "label": "AI agents",
                "signal_score": 70,
                "independent_domains": ["example.com", "example.org"],
                "positive_lenses": ["adoption_usage", "official_builders"],
                "evidence_urls": [
                    "https://example.com/agents",
                    "https://example.org/agents",
                ],
            }
        ],
        "evidence": [
            {
                "claim": "Public search result references AI agents: Payment agents launch",
                "source_url": "https://example.com/agents",
                "research_lens": "adoption_usage",
            }
        ],
        "discovery_history": {
            "state": "insufficient_history",
            "run_count": 1,
        },
    }


def test_phone_discovery_form_is_bounded_and_owner_only():
    assert parse_discovery_request(BODY) == {
        "topic": "AI agents and crypto payments",
        "chain": "solana",
        "limit": 5,
    }
    event = {
        "repository": {"owner": {"login": "alstonburbach"}},
        "issue": {
            "user": {"login": "alstonburbach"},
            "title": "[RADAR DISCOVERY] AI agents",
            "body": BODY,
        },
    }
    assert validate_owner_discovery_event(event)["chain"] == "solana"

    event["issue"]["user"]["login"] = "someone-else"
    with pytest.raises(ValueError, match="repository owner"):
        validate_owner_discovery_event(event)


def test_phone_discovery_form_rejects_bad_limit_and_chain():
    with pytest.raises(ValueError, match="between 1 and 10"):
        parse_discovery_request(BODY.replace("\n5\n", "\n50\n"))
    with pytest.raises(ValueError, match="Chain must be"):
        parse_discovery_request(BODY.replace("solana", "dogechain"))


def test_phone_discovery_report_shows_candidates_sources_and_boundaries():
    markdown = render_discovery_report(_report())

    assert "Narrative Radar discovery" in markdown
    assert "Observed: `2026-09-01T14:17:00+00:00`" in markdown
    assert "AI agents" in markdown
    assert "public_rss" in markdown
    assert "Payment agents launch" in markdown
    assert "not automatic buy signals" in markdown
    assert "does not verify a token contract" in markdown
    assert "Counterevidence requires review" in markdown
    assert "No trade signal or order was created" in render_discovery_error("Bad input")

    report = _report()
    report["candidate_signals"][0]["label"] = "[fake](bad) @someone"
    escaped = render_discovery_report(report)
    assert "\\[fake\\](bad) @\u200bsomeone" in escaped


def test_discovery_notification_requires_a_fresh_material_change():
    report = _report()
    assert discovery_notification_state(report)["notify"] is True

    report["discovery_history"] = {
        "state": "mixed_or_stable",
        "run_count": 2,
        "new_since_previous": [],
        "persisted_since_previous": ["AI agents"],
        "quality_score_since_previous": {
            "available": True,
            "delta": 0,
        },
        "independent_domain_count_since_previous": {
            "available": True,
            "delta": 0,
        },
    }
    assert discovery_notification_state(report) == {
        "notify": False,
        "reason": "no_material_change",
    }

    report["discovery_history"]["new_since_previous"] = ["payment agents"]
    assert discovery_notification_state(report)["reason"] == "new_candidates"

    report["discovery_history"]["new_since_previous"] = []
    report["discovery_history"]["quality_score_since_previous"]["delta"] = 10
    assert discovery_notification_state(report)["reason"] == "strengthening_candidates"

    report["quality"]["freshness"]["recent_count"] = 0
    assert discovery_notification_state(report)["reason"] == "no_recent_evidence"


def test_issue_discovery_cli_writes_safe_phone_outputs(tmp_path, monkeypatch):
    event = {
        "repository": {"owner": {"login": "alstonburbach"}},
        "issue": {
            "user": {"login": "alstonburbach"},
            "title": "[RADAR DISCOVERY] AI agents",
            "body": BODY,
        },
    }
    event_path = tmp_path / "event.json"
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    notification_path = tmp_path / "notification.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")

    monkeypatch.setattr(
        "app.issue_discovery_main.build_default_research_provider",
        lambda: object(),
    )
    monkeypatch.setattr(
        "app.issue_discovery_main.run_discovery",
        lambda **kwargs: _report(),
    )

    exit_code = main(
        [
            "--event",
            str(event_path),
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
            "--notification-output",
            str(notification_path),
            "--no-persist",
        ]
    )

    assert exit_code == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "complete"
    assert "AI agents" in markdown_path.read_text(encoding="utf-8")
    assert json.loads(notification_path.read_text(encoding="utf-8"))["notify"] is True
