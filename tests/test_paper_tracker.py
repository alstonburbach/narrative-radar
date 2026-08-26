from pathlib import Path

import app.database.db as db
from app.tracking.paper_tracker import PaperTracker


def test_paper_tracker_marks_and_closes_position(tmp_path: Path):
    original_path = db.DATABASE_PATH
    db.DATABASE_PATH = tmp_path / "paper.db"

    try:
        tracker = PaperTracker()
        opened = tracker.open_position(
            contract_address="0xtest",
            token_symbol="TEST",
            entry_price_usd=2,
            invested_usd=100,
        )
        assert opened["quantity"] == 50
        assert opened["status"] == "open"

        marked = tracker.mark_to_market(opened["id"], 2.5)
        assert marked["current_value_usd"] == 125
        assert marked["pnl_usd"] == 25
        assert marked["pnl_pct"] == 25

        closed = tracker.close_position(opened["id"], 1.5)
        assert closed["status"] == "closed"
        assert closed["pnl_usd"] == -25
    finally:
        db.DATABASE_PATH = original_path
