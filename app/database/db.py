import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database.models import Evidence


DATABASE_PATH = Path("data/narrative_radar.db")


def get_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                chain TEXT,
                token_name TEXT,
                token_symbol TEXT,
                price_usd REAL,
                market_cap REAL,
                fdv REAL,
                liquidity_usd REAL,
                volume_24h REAL,
                volume_6h REAL,
                volume_1h REAL,
                price_change_24h REAL,
                price_change_6h REAL,
                price_change_1h REAL,
                pair_address TEXT,
                dex TEXT,
                dex_url TEXT,
                collected_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_items (
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
                discovered_at TEXT NOT NULL,
                claim_type TEXT NOT NULL DEFAULT 'lead',
                verification_status TEXT NOT NULL DEFAULT 'unverified_search_lead',
                research_lens TEXT,
                retrieved_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                chain TEXT,
                started_at TEXT NOT NULL,
                research_status TEXT,
                quality_score REAL,
                classification TEXT,
                independent_domain_count INTEGER NOT NULL DEFAULT 0,
                positive_lens_count INTEGER NOT NULL DEFAULT 0,
                adoption_evidence_count INTEGER NOT NULL DEFAULT 0,
                adoption_content_matches INTEGER NOT NULL DEFAULT 0,
                counterevidence_leads INTEGER NOT NULL DEFAULT 0,
                content_matches INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS onchain_activity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address TEXT NOT NULL,
                chain TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                holder_count INTEGER,
                holder_count_is_lower_bound INTEGER NOT NULL DEFAULT 0,
                token_account_count INTEGER,
                holder_scan_total INTEGER,
                holder_scan_returned INTEGER NOT NULL DEFAULT 0,
                holder_scan_complete INTEGER,
                last_indexed_slot INTEGER,
                token_supply REAL,
                token_supply_raw TEXT,
                token_decimals INTEGER,
                activity_window_hours INTEGER,
                transfer_transaction_count_24h INTEGER,
                transfer_event_count_24h INTEGER,
                unique_active_wallets_24h INTEGER,
                unique_inflow_wallets_24h INTEGER,
                unique_outflow_wallets_24h INTEGER,
                transfer_scan_returned INTEGER NOT NULL DEFAULT 0,
                transfer_scan_limit INTEGER,
                transfer_scan_truncated INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                chain TEXT NOT NULL,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL,
                quality_score REAL,
                classification TEXT,
                independent_domain_count INTEGER NOT NULL DEFAULT 0,
                lead_count INTEGER NOT NULL DEFAULT 0,
                candidate_signal_count INTEGER NOT NULL DEFAULT 0,
                searched_lens_count INTEGER NOT NULL DEFAULT 0,
                failed_lens_count INTEGER NOT NULL DEFAULT 0,
                candidate_signal_labels TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(evidence_items)")
        }
        migrations = {
            "claim_type": "TEXT NOT NULL DEFAULT 'lead'",
            "verification_status": "TEXT NOT NULL DEFAULT 'unverified_search_lead'",
            "research_lens": "TEXT",
            "retrieved_at": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing_columns:
                conn.execute(
                    f"ALTER TABLE evidence_items ADD COLUMN {column} {definition}"
                )


def save_market_snapshot(market: dict) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO market_snapshots (
                contract_address, chain, token_name, token_symbol,
                price_usd, market_cap, fdv, liquidity_usd, volume_24h,
                volume_6h, volume_1h, price_change_24h, price_change_6h,
                price_change_1h, pair_address, dex, dex_url, collected_at,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market.get("contract_address"),
                market.get("chain"),
                market.get("token_name"),
                market.get("token_symbol"),
                market.get("price_usd"),
                market.get("market_cap"),
                market.get("fdv"),
                market.get("liquidity_usd"),
                market.get("volume_24h"),
                market.get("volume_6h"),
                market.get("volume_1h"),
                market.get("price_change_24h"),
                market.get("price_change_6h"),
                market.get("price_change_1h"),
                market.get("pair_address"),
                market.get("dex"),
                market.get("dex_url"),
                market.get("collected_at"),
                json.dumps(market),
            ),
        )
        return cursor.lastrowid


def save_evidence(contract_address: str, evidence: Evidence) -> int:
    discovered_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO evidence_items (
                contract_address, claim, source_url, source_type,
                published_at, author, quote, relevance, confidence,
                discovered_at, claim_type, verification_status, research_lens,
                retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract_address,
                evidence.claim,
                evidence.source_url,
                evidence.source_type,
                evidence.published_at,
                evidence.author,
                evidence.quote,
                evidence.relevance,
                evidence.confidence,
                discovered_at,
                evidence.claim_type,
                evidence.verification_status,
                evidence.research_lens,
                evidence.retrieved_at,
            ),
        )
        return cursor.lastrowid


def _evidence_items_from_report(report: dict) -> list[dict]:
    narrative = report.get("narrative") or {}
    return (narrative.get("verified_evidence") or []) + (
        narrative.get("uncertain_evidence") or []
    )


def save_narrative_run(report: dict) -> int:
    """Persist compact evidence metrics for later durability comparisons."""
    market = report.get("market") or {}
    research = report.get("research") or {}
    quality = report.get("narrative_quality") or {}
    evidence = _evidence_items_from_report(report)
    adoption_items = [
        item for item in evidence if item.get("research_lens") == "adoption_usage"
    ]
    metrics = {
        "contract_address": market.get("contract_address"),
        "chain": market.get("chain"),
        "started_at": report.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "research_status": research.get("status"),
        "quality_score": quality.get("quality_score"),
        "classification": quality.get("classification"),
        "independent_domain_count": quality.get("independent_domain_count", 0),
        "positive_lens_count": len(quality.get("positive_lenses_covered") or []),
        "adoption_evidence_count": len(adoption_items),
        "adoption_content_matches": sum(
            item.get("verification_status") == "content_match"
            for item in adoption_items
        ),
        "counterevidence_leads": quality.get("counterevidence_leads", 0),
        "content_matches": quality.get("content_matches", 0),
    }
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO narrative_runs (
                contract_address, chain, started_at, research_status,
                quality_score, classification, independent_domain_count,
                positive_lens_count, adoption_evidence_count,
                adoption_content_matches, counterevidence_leads,
                content_matches, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics["contract_address"],
                metrics["chain"],
                metrics["started_at"],
                metrics["research_status"],
                metrics["quality_score"],
                metrics["classification"],
                metrics["independent_domain_count"],
                metrics["positive_lens_count"],
                metrics["adoption_evidence_count"],
                metrics["adoption_content_matches"],
                metrics["counterevidence_leads"],
                metrics["content_matches"],
                json.dumps(metrics),
            ),
        )
        return cursor.lastrowid


def get_narrative_history(contract_address: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, contract_address, chain, started_at, research_status,
                   quality_score, classification, independent_domain_count,
                   positive_lens_count, adoption_evidence_count,
                   adoption_content_matches, counterevidence_leads,
                   content_matches
            FROM narrative_runs
            WHERE contract_address = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (contract_address, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def save_onchain_activity_snapshot(snapshot: dict) -> int:
    """Persist descriptive on-chain metrics without turning them into a score."""
    metrics = {
        "token_address": snapshot.get("token_address") or snapshot.get("contract_address"),
        "chain": (snapshot.get("chain") or "unknown").strip().lower(),
        "observed_at": snapshot.get("observed_at") or datetime.now(timezone.utc).isoformat(),
        "status": snapshot.get("status") or "unknown",
        "source": snapshot.get("source") or "unknown",
        "holder_count": snapshot.get("holder_count"),
        "holder_count_is_lower_bound": bool(snapshot.get("holder_count_is_lower_bound")),
        "token_account_count": snapshot.get("token_account_count"),
        "holder_scan_total": snapshot.get("holder_scan_total"),
        "holder_scan_returned": snapshot.get("holder_scan_returned") or 0,
        "holder_scan_complete": snapshot.get("holder_scan_complete"),
        "last_indexed_slot": snapshot.get("last_indexed_slot"),
        "token_supply": snapshot.get("token_supply"),
        "token_supply_raw": snapshot.get("token_supply_raw"),
        "token_decimals": snapshot.get("token_decimals"),
        "activity_window_hours": snapshot.get("activity_window_hours"),
        "transfer_transaction_count_24h": snapshot.get("transfer_transaction_count_24h"),
        "transfer_event_count_24h": snapshot.get("transfer_event_count_24h"),
        "unique_active_wallets_24h": snapshot.get("unique_active_wallets_24h"),
        "unique_inflow_wallets_24h": snapshot.get("unique_inflow_wallets_24h"),
        "unique_outflow_wallets_24h": snapshot.get("unique_outflow_wallets_24h"),
        "transfer_scan_returned": snapshot.get("transfer_scan_returned") or 0,
        "transfer_scan_limit": snapshot.get("transfer_scan_limit"),
        "transfer_scan_truncated": bool(snapshot.get("transfer_scan_truncated")),
    }
    if not metrics["token_address"]:
        raise ValueError("token_address is required")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO onchain_activity_snapshots (
                token_address, chain, observed_at, status, source,
                holder_count, holder_count_is_lower_bound, token_account_count,
                holder_scan_total, holder_scan_returned, holder_scan_complete,
                last_indexed_slot, token_supply, token_supply_raw, token_decimals,
                activity_window_hours, transfer_transaction_count_24h,
                transfer_event_count_24h, unique_active_wallets_24h,
                unique_inflow_wallets_24h, unique_outflow_wallets_24h,
                transfer_scan_returned, transfer_scan_limit,
                transfer_scan_truncated, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics["token_address"],
                metrics["chain"],
                metrics["observed_at"],
                metrics["status"],
                metrics["source"],
                metrics["holder_count"],
                int(metrics["holder_count_is_lower_bound"]),
                metrics["token_account_count"],
                metrics["holder_scan_total"],
                metrics["holder_scan_returned"],
                None
                if metrics["holder_scan_complete"] is None
                else int(bool(metrics["holder_scan_complete"])),
                metrics["last_indexed_slot"],
                metrics["token_supply"],
                metrics["token_supply_raw"],
                metrics["token_decimals"],
                metrics["activity_window_hours"],
                metrics["transfer_transaction_count_24h"],
                metrics["transfer_event_count_24h"],
                metrics["unique_active_wallets_24h"],
                metrics["unique_inflow_wallets_24h"],
                metrics["unique_outflow_wallets_24h"],
                metrics["transfer_scan_returned"],
                metrics["transfer_scan_limit"],
                int(metrics["transfer_scan_truncated"]),
                json.dumps(metrics),
            ),
        )
        return cursor.lastrowid


def get_onchain_activity_history(
    token_address: str,
    chain: str = "unknown",
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    chain = (chain or "unknown").strip().lower()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, token_address, chain, observed_at, status, source,
                   holder_count, holder_count_is_lower_bound, token_account_count,
                   holder_scan_total, holder_scan_returned, holder_scan_complete,
                   last_indexed_slot, token_supply, token_supply_raw, token_decimals,
                   activity_window_hours, transfer_transaction_count_24h,
                   transfer_event_count_24h, unique_active_wallets_24h,
                   unique_inflow_wallets_24h, unique_outflow_wallets_24h,
                   transfer_scan_returned, transfer_scan_limit,
                   transfer_scan_truncated
            FROM onchain_activity_snapshots
            WHERE token_address = ? AND chain = ?
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (token_address, chain, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def save_discovery_run(report: dict) -> int:
    """Persist compact discovery metrics so repeated scans can be compared."""
    quality = report.get("quality") or {}
    lenses = report.get("lenses") or {}
    signals = report.get("candidate_signals") or []
    labels = [signal.get("label") for signal in signals if signal.get("label")]
    metrics = {
        "topic": report.get("topic") or "crypto narratives",
        "chain": (report.get("chain") or "unknown").strip().lower(),
        "started_at": report.get("started_at") or datetime.now(timezone.utc).isoformat(),
        "status": report.get("status") or "unknown",
        "quality_score": quality.get("quality_score"),
        "classification": quality.get("classification"),
        "independent_domain_count": report.get("independent_domain_count") or 0,
        "lead_count": report.get("lead_count") or 0,
        "candidate_signal_count": len(labels),
        "searched_lens_count": len(report.get("searched_lenses") or []),
        "failed_lens_count": sum(
            1 for item in lenses.values() if item.get("status") == "failed"
        ),
        "candidate_signal_labels": labels,
    }
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO discovery_runs (
                topic, chain, started_at, status, quality_score, classification,
                independent_domain_count, lead_count, candidate_signal_count,
                searched_lens_count, failed_lens_count, candidate_signal_labels,
                raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metrics["topic"],
                metrics["chain"],
                metrics["started_at"],
                metrics["status"],
                metrics["quality_score"],
                metrics["classification"],
                metrics["independent_domain_count"],
                metrics["lead_count"],
                metrics["candidate_signal_count"],
                metrics["searched_lens_count"],
                metrics["failed_lens_count"],
                json.dumps(metrics["candidate_signal_labels"]),
                json.dumps(metrics),
            ),
        )
        return cursor.lastrowid


def get_discovery_history(
    topic: str,
    chain: str = "unknown",
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    chain = (chain or "unknown").strip().lower()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, chain, started_at, status, quality_score,
                   classification, independent_domain_count, lead_count,
                   candidate_signal_count, searched_lens_count,
                   failed_lens_count, candidate_signal_labels
            FROM discovery_runs
            WHERE topic = ? AND chain = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (topic, chain, limit),
        ).fetchall()
    history = []
    for row in reversed(rows):
        item = dict(row)
        try:
            item["candidate_signal_labels"] = json.loads(
                item.get("candidate_signal_labels") or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            item["candidate_signal_labels"] = []
        history.append(item)
    return history
