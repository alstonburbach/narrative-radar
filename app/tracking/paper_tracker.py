from datetime import datetime, timezone
from typing import Optional

from app.database.db import (
    close_paper_position,
    get_paper_position,
    initialize_database,
    list_open_paper_positions,
    save_paper_position,
    update_paper_position,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperTracker:
    """A journal for hypothetical positions; it never submits a live order."""

    def __init__(self):
        initialize_database()

    def open_position(
        self,
        contract_address: str,
        entry_price_usd: float,
        invested_usd: float,
        token_symbol: Optional[str] = None,
    ) -> dict:
        entry_price_usd = float(entry_price_usd)
        invested_usd = float(invested_usd)

        if entry_price_usd <= 0:
            raise ValueError("entry_price_usd must be greater than zero")
        if invested_usd <= 0:
            raise ValueError("invested_usd must be greater than zero")

        opened_at = _now()
        position_id = save_paper_position(
            contract_address=contract_address,
            token_symbol=token_symbol or "UNKNOWN",
            entry_price_usd=entry_price_usd,
            quantity=invested_usd / entry_price_usd,
            invested_usd=invested_usd,
            opened_at=opened_at,
        )
        return get_paper_position(position_id)

    def mark_to_market(self, position_id: int, current_price_usd: float) -> dict:
        current_price_usd = float(current_price_usd)
        if current_price_usd <= 0:
            raise ValueError("current_price_usd must be greater than zero")

        update_paper_position(position_id, current_price_usd, _now())
        return get_paper_position(position_id)

    def close_position(self, position_id: int, exit_price_usd: float) -> dict:
        exit_price_usd = float(exit_price_usd)
        if exit_price_usd <= 0:
            raise ValueError("exit_price_usd must be greater than zero")

        close_paper_position(position_id, exit_price_usd, _now())
        return get_paper_position(position_id)

    def open_positions(self):
        return list_open_paper_positions()
