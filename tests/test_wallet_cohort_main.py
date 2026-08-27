import pytest

from app.wallet_cohort_main import MAX_WALLETS, parse_wallets


def test_parse_wallets_deduplicates_and_ignores_comments():
    assert parse_wallets("A\nB # note\nA\n\n") == ["A", "B"]


def test_parse_wallets_bounds_cohort_size():
    with pytest.raises(ValueError, match="At most"):
        parse_wallets("\n".join(str(index) for index in range(MAX_WALLETS + 1)))
