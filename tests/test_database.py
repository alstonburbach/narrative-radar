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
