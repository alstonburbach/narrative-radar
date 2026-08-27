from app.wallet_cohort_main import parse_wallets


def test_parse_wallets_deduplicates_and_ignores_comments():
    assert parse_wallets("A\nB # note\nA\n\n") == ["A", "B"]
