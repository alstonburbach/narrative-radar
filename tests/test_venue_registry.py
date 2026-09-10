from app.venue_registry import (
    enabled_chains,
    enabled_venues,
    identify_factory_venue,
    normalize_chain,
    venue_config,
)


def test_chain_aliases_normalize():
    assert normalize_chain("SOL") == "solana"
    assert normalize_chain("robinhood_chain") == "robinhood"
    assert normalize_chain("BNB") == "bsc"


def test_pons_factory_is_verified_on_robinhood_chain():
    assert identify_factory_venue(
        chain="robinhood_chain",
        factory_address="0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB",
    ) == "pons"


def test_same_factory_does_not_match_wrong_chain():
    assert identify_factory_venue(
        chain="base",
        factory_address="0xA5aAb3F0c6EeadF30Ef1D3Eb997108E976351feB",
    ) is None


def test_registry_exposes_future_multichain_targets():
    assert {"solana", "robinhood", "base", "ethereum", "bsc"}.issubset(enabled_chains())
    assert {"pump_fun", "pons", "robinhood_chain"}.issubset(enabled_venues())
    assert venue_config("pons")["detection"] == "factory_contract"
