from datetime import datetime, timezone

from app.execution.order_preview import build_order_preview


AS_OF = datetime(2026, 8, 27, 19, 0, tzinfo=timezone.utc)


def test_order_preview_is_reviewable_but_never_executable():
    preview = build_order_preview(
        {
            "found": True,
            "token_name": "Test",
            "token_symbol": "TEST",
            "chain": "base",
            "contract_address": "0xtest",
            "pair_address": "0xpair",
            "dex": "uniswap",
            "price_usd": 0.01,
            "liquidity_usd": 50_000,
            "collected_at": "2026-08-27T18:59:30Z",
        },
        side="buy",
        amount_usd=100,
        as_of=AS_OF,
    )

    assert preview["status"] == "ready_for_manual_review"
    assert preview["estimated_token_amount"] == 10_000
    assert preview["manual_approval_required"] is True
    assert preview["execution_enabled"] is False
    assert preview["estimated_fee_usd"] is None
    assert preview["estimated_slippage_pct"] is None


def test_order_preview_blocks_size_that_is_too_large_for_liquidity():
    preview = build_order_preview(
        {
            "found": True,
            "price_usd": 1,
            "liquidity_usd": 1_000,
            "collected_at": "2026-08-27T18:59:30Z",
        },
        side="sell",
        amount_usd=100,
        as_of=AS_OF,
    )

    assert preview["status"] == "blocked"
    assert "liquidity_size" in preview["blocked_checks"]
    assert preview["liquidity_context"]["position_to_liquidity_pct"] == 10.0


def test_order_preview_blocks_missing_market_inputs():
    preview = build_order_preview(
        {"found": False},
        side="buy",
        amount_usd=25,
        as_of=AS_OF,
    )

    assert preview["status"] == "blocked"
    assert set(preview["blocked_checks"]) == {
        "market_pair",
        "market_snapshot_freshness",
        "reference_price",
        "liquidity",
        "liquidity_size",
    }
    assert preview["execution_enabled"] is False


def test_order_preview_blocks_stale_market_snapshot():
    preview = build_order_preview(
        {
            "found": True,
            "price_usd": 1,
            "liquidity_usd": 50_000,
            "collected_at": "2026-08-27T18:50:00Z",
        },
        side="buy",
        amount_usd=100,
        as_of=AS_OF,
        max_snapshot_age_seconds=300,
    )

    assert preview["status"] == "blocked"
    assert preview["snapshot_age_seconds"] == 600.0
    assert "market_snapshot_freshness" in preview["blocked_checks"]


def test_order_preview_blocks_invalid_or_future_market_timestamp():
    invalid = build_order_preview(
        {"found": True, "price_usd": 1, "liquidity_usd": 50_000},
        side="buy",
        amount_usd=100,
        as_of=AS_OF,
    )
    future = build_order_preview(
        {
            "found": True,
            "price_usd": 1,
            "liquidity_usd": 50_000,
            "collected_at": "2026-08-27T19:02:00Z",
        },
        side="buy",
        amount_usd=100,
        as_of=AS_OF,
    )

    assert "market_snapshot_freshness" in invalid["blocked_checks"]
    assert "market_snapshot_freshness" in future["blocked_checks"]
