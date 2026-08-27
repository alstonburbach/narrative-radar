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
