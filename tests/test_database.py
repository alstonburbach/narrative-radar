from app.database import db
from app.database.models import Evidence


def test_initialize_database_migrates_and_persists_evidence_metadata(monkeypatch, tmp_path):
    database_path = tmp_path / "narrative.db"
    monkeypatch.setattr(db, "DATABASE_PATH", database_path)

    with db.get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE evidence_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                claim TEXT NOT NULL,
                source_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                published_at TEXT,
                author TEXT,
                quote TEXT,
                relevance TEXT,
                confidence REAL NOT NULL,
                discovered_at TEXT NOT NULL
            )
            """
        )

    db.initialize_database()
    evidence = Evidence(
        "Builder activity",
        "https://github.com/example/project",
        "primary_candidate",
        confidence=0.7,
        claim_type="lead",
        verification_status="content_match",
        research_lens="official_builders",
        retrieved_at="2026-08-27T00:00:00+00:00",
    )
    db.save_evidence("0xtest", evidence)

    with db.get_connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence_items)")}
        row = connection.execute(
            "SELECT claim_type, verification_status, research_lens, retrieved_at FROM evidence_items"
        ).fetchone()

    assert {
        "claim_type",
        "verification_status",
        "research_lens",
        "retrieved_at",
    } <= columns
    assert tuple(row) == (
        "lead",
        "content_match",
        "official_builders",
        "2026-08-27T00:00:00+00:00",
    )


def test_narrative_run_history_persists_compact_adoption_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "narrative.db")
    db.initialize_database()
    report = {
        "started_at": "2026-08-27T00:00:00+00:00",
        "market": {"contract_address": "0xtest", "chain": "base"},
        "research": {"status": "complete"},
        "narrative_quality": {
            "quality_score": 61,
            "classification": "corroborated_leads",
            "independent_domain_count": 3,
            "positive_lenses_covered": ["adoption_usage", "official_builders"],
            "counterevidence_leads": 1,
            "content_matches": 2,
        },
        "narrative": {
            "verified_evidence": [],
            "uncertain_evidence": [
                {
                    "research_lens": "adoption_usage",
                    "verification_status": "content_match",
                },
                {
                    "research_lens": "adoption_usage",
                    "verification_status": "unverified_search_lead",
                },
            ],
        },
    }

    run_id = db.save_narrative_run(report)
    history = db.get_narrative_history("0xtest")

    assert run_id == 1
    assert len(history) == 1
    assert history[0]["adoption_evidence_count"] == 2
    assert history[0]["adoption_content_matches"] == 1
    assert history[0]["counterevidence_leads"] == 1


def test_onchain_activity_history_persists_descriptive_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "narrative.db")
    db.initialize_database()
    snapshot = {
        "token_address": "mint",
        "chain": "solana",
        "observed_at": "2026-08-27T00:00:00+00:00",
        "status": "complete",
        "source": "helius",
        "holder_count": 12,
        "holder_count_is_lower_bound": True,
        "token_account_count": 15,
        "holder_scan_total": 20,
        "holder_scan_returned": 15,
        "holder_scan_complete": False,
        "last_indexed_slot": 123,
        "scanned_token_amount_raw": "500000",
        "scanned_supply_coverage_pct": 50.0,
        "largest_scanned_owner_share_pct": 30.0,
        "top_10_scanned_owner_share_pct": 45.0,
        "holder_concentration_is_lower_bound": True,
        "token_supply": 1000,
        "token_supply_raw": "1000000",
        "token_decimals": 3,
        "activity_window_hours": 24,
        "transfer_transaction_count_24h": 8,
        "transfer_event_count_24h": 13,
        "unique_active_wallets_24h": 7,
        "unique_inflow_wallets_24h": 6,
        "unique_outflow_wallets_24h": 5,
        "transfer_scan_returned": 8,
        "transfer_scan_limit": 100,
        "transfer_scan_truncated": False,
    }

    snapshot_id = db.save_onchain_activity_snapshot(snapshot)
    history = db.get_onchain_activity_history("mint", chain="solana")

    assert snapshot_id == 1
    assert history[0]["holder_count"] == 12
    assert history[0]["holder_count_is_lower_bound"] == 1
    assert history[0]["transfer_event_count_24h"] == 13
    assert history[0]["unique_active_wallets_24h"] == 7
    assert history[0]["scanned_supply_coverage_pct"] == 50.0
    assert history[0]["largest_scanned_owner_share_pct"] == 30.0
    assert history[0]["holder_concentration_is_lower_bound"] == 1


def test_discovery_history_persists_compact_signal_labels(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "narrative.db")
    db.initialize_database()
    report = {
        "topic": "stablecoin rails",
        "chain": "base",
        "started_at": "2026-08-27T00:00:00+00:00",
        "status": "complete",
        "lead_count": 9,
        "independent_domain_count": 3,
        "searched_lenses": ["official_builders", "adoption_usage"],
        "lenses": {
            "official_builders": {"status": "complete"},
            "adoption_usage": {"status": "complete"},
            "counterevidence": {"status": "failed"},
        },
        "candidate_signals": [
            {"label": "stablecoin rails"},
            {"label": "payment APIs"},
        ],
        "quality": {"quality_score": 48, "classification": "promising_leads"},
    }

    run_id = db.save_discovery_run(report)
    history = db.get_discovery_history("stablecoin rails", chain="base")

    assert run_id == 1
    assert history[0]["candidate_signal_labels"] == ["stablecoin rails", "payment APIs"]
    assert history[0]["failed_lens_count"] == 1


def test_wallet_history_persists_realized_pnl_and_contamination_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "narrative.db")
    db.initialize_database()
    report = {
        "wallet_address": "wallet",
        "analyzed_at": "2026-08-27T00:00:00+00:00",
        "quality_score": 72,
        "research_candidate": True,
        "copy_trade_ready": False,
        "flags": ["incomplete_cost_basis_or_inbound_tokens"],
        "pnl": {
            "closed_trades": 21,
            "wins": 13,
            "losses": 8,
            "primary_realized_pnl": 12.5,
            "primary_quote_asset": "USD",
            "realized_pnl_usd": 12.5,
            "unmatched_sell_value_usd": 3,
            "profit_factor": 1.5,
            "win_rate_pct": 61.9,
            "quote_assets": ["USD"],
        },
        "external_flow": {
            "external_inflow_usd": 100,
            "external_outflow_usd": 25,
        },
    }

    run_id = db.save_wallet_run(report)
    history = db.get_wallet_history("wallet")

    assert run_id == 1
    assert history[0]["primary_realized_pnl"] == 12.5
    assert history[0]["primary_quote_asset"] == "USD"
    assert history[0]["external_inflow_usd"] == 100
    assert history[0]["flags"] == ["incomplete_cost_basis_or_inbound_tokens"]
