from app.execution.order_preview import build_order_preview


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
        },
        side="buy",
        amount_usd=100,
    )

    assert preview["status"] == "ready_for_manual_review"
    assert preview["estimated_token_amount"] == 10_000
    assert preview["manual_approval_required"] is True
    assert preview["execution_enabled"] is False
    assert preview["estimated_fee_usd"] is None
    assert preview["estimated_slippage_pct"] is None


def test_order_preview_blocks_size_that_is_too_large_for_liquidity():
    preview = build_order_preview(
        {"found": True, "price_usd": 1, "liquidity_usd": 1_000},
        side="sell",
        amount_usd=100,
    )

    assert preview["status"] == "blocked"
    assert "liquidity_size" in preview["blocked_checks"]
    assert preview["liquidity_context"]["position_to_liquidity_pct"] == 10.0


def test_order_preview_blocks_missing_market_inputs():
    preview = build_order_preview(
        {"found": False},
        side="buy",
        amount_usd=25,
    )

    assert preview["status"] == "blocked"
    assert set(preview["blocked_checks"]) == {
        "market_pair",
        "reference_price",
        "liquidity",
        "liquidity_size",
    }
    assert preview["execution_enabled"] is False
