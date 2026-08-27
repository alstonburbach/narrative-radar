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
