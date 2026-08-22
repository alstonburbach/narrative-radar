from pathlib import Path

from app.database.models import Evidence
import app.database.db as db


def test_save_evidence(tmp_path: Path):
    original_path = db.DATABASE_PATH
    db.DATABASE_PATH = tmp_path / "test_radar.db"

    try:
        db.initialize_database()

        evidence = Evidence(
            claim="Binance posted an unusual cat image",
            source_url="https://example.com/binance-post",
            source_type="primary",
            published_at="2025-12-23T00:00:00Z",
            author="Binance",
            relevance="Possible origin of token narrative",
            confidence=0.95,
        )

        evidence_id = db.save_evidence(
            contract_address="0xtest",
            evidence=evidence,
        )

        assert evidence_id == 1

        with db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM evidence_items
                WHERE id = ?
                """,
                (evidence_id,),
            ).fetchone()

        assert row["claim"] == "Binance posted an unusual cat image"
        assert row["source_type"] == "primary"
        assert row["confidence"] == 0.95

    finally:
        db.DATABASE_PATH = original_path