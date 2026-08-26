import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database.models import Evidence


DATABASE_PATH = Path(
    os.getenv("NARRATIVE_RADAR_DB_PATH", "data/narrative_radar.db")
)


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
                discovered_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                token_symbol TEXT,
                entry_price_usd REAL NOT NULL,
                quantity REAL NOT NULL,
                invested_usd REAL NOT NULL,
                current_price_usd REAL NOT NULL,
                current_value_usd REAL NOT NULL,
                pnl_usd REAL NOT NULL,
                pnl_pct REAL NOT NULL,
                status TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )


def save_market_snapshot(market: dict) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO market_snapshots (
                contract_address,
                chain,
                token_name,
                token_symbol,
                price_usd,
                market_cap,
                fdv,
                liquidity_usd,
                volume_24h,
                volume_6h,
                volume_1h,
                price_change_24h,
                price_change_6h,
                price_change_1h,
                pair_address,
                dex,
                dex_url,
                collected_at,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                contract_address,
                claim,
                source_url,
                source_type,
                published_at,
                author,
                quote,
                relevance,
                confidence,
                discovered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

        return cursor.lastrowid


def list_evidence(contract_address: str):
    """Return stored evidence for a contract in insertion order."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM evidence_items
            WHERE contract_address = ?
            ORDER BY id ASC
            """,
            (contract_address,),
        ).fetchall()

    return [dict(row) for row in rows]


def save_paper_position(
    contract_address: str,
    token_symbol: str,
    entry_price_usd: float,
    quantity: float,
    invested_usd: float,
    opened_at: str,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO paper_positions (
                contract_address,
                token_symbol,
                entry_price_usd,
                quantity,
                invested_usd,
                current_price_usd,
                current_value_usd,
                pnl_usd,
                pnl_pct,
                status,
                opened_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                contract_address,
                token_symbol,
                entry_price_usd,
                quantity,
                invested_usd,
                entry_price_usd,
                invested_usd,
                0.0,
                0.0,
                opened_at,
                opened_at,
            ),
        )

        return cursor.lastrowid


def get_paper_position(position_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM paper_positions WHERE id = ?",
            (position_id,),
        ).fetchone()

    return dict(row) if row else None


def update_paper_position(
    position_id: int,
    current_price_usd: float,
    updated_at: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE paper_positions
            SET current_price_usd = ?,
                current_value_usd = quantity * ?,
                pnl_usd = (quantity * ?) - invested_usd,
                pnl_pct = CASE
                    WHEN invested_usd = 0 THEN 0
                    ELSE (((quantity * ?) - invested_usd) / invested_usd) * 100
                END,
                updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                current_price_usd,
                current_price_usd,
                current_price_usd,
                current_price_usd,
                updated_at,
                position_id,
            ),
        )


def close_paper_position(
    position_id: int,
    current_price_usd: float,
    closed_at: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE paper_positions
            SET current_price_usd = ?,
                current_value_usd = quantity * ?,
                pnl_usd = (quantity * ?) - invested_usd,
                pnl_pct = CASE
                    WHEN invested_usd = 0 THEN 0
                    ELSE (((quantity * ?) - invested_usd) / invested_usd) * 100
                END,
                status = 'closed',
                updated_at = ?,
                closed_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (
                current_price_usd,
                current_price_usd,
                current_price_usd,
                current_price_usd,
                closed_at,
                closed_at,
                position_id,
            ),
        )


def list_open_paper_positions():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM paper_positions
            WHERE status = 'open'
            ORDER BY id ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]
