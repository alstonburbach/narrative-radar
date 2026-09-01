import copy

from app.database import db
from app.github_issue_venue import render_venue_report
from app.venue_watch import run_venue_watch


PUMP = "9b6CWNzoTarGJ7KacCkegJt8Js3g9j52MpxQFmhEpump"
ROBINHOOD = "0x1111111111111111111111111111111111111111"


def _candidate(venue, chain, contract):
    return {
        "rank": 1,
        "venue": venue,
        "chain": chain,
        "contract_address": contract,
        "token_name": "Test Token",
        "token_symbol": "TEST",
        "venue_confidence": "launch_dex_confirmed" if venue == "pump_fun" else "chain_confirmed",
        "dex_url": f"https://dexscreener.com/{chain}/pair",
        "pair_age_minutes": 30,
        "market_cap": 100_000,
        "liquidity_usd": 20_000,
        "volume_1h": 25_000,
        "buys_1h": 60,
        "sells_1h": 20,
        "price_change_5m": 5,
        "price_change_1h": 20,
        "observed_at": "2026-09-01T12:00:00+00:00",
        "market_screen": {
            "status": "research_next",
            "score": 95,
            "blockers": [],
            "cautions": [],
        },
        "execution_enabled": False,
    }


class Provider:
    def __init__(self, candidates):
        self.candidates = candidates

    def collect(self, **kwargs):
        return {
            "status": "complete",
            "provider": "test",
            "observed_at": "2026-09-01T12:00:00+00:00",
            "profiles_received": len(self.candidates),
            "eligible_profiles": len(self.candidates),
            "candidate_count": len(self.candidates),
            "candidates": copy.deepcopy(self.candidates),
            "execution_enabled": False,
        }


class Security:
    provider_name = "test-security"

    def __init__(self, blocked=None):
        self.blocked = set(blocked or [])

    def fetch(self, contract_address, chain):
        blockers = ["honeypot_detected"] if contract_address in self.blocked else []
        return {
            "status": "complete",
            "provider": self.provider_name,
            "chain": chain,
            "risk_level": "critical" if blockers else "low",
            "hard_blockers": blockers,
            "promotion_eligible": not blockers,
            "execution_enabled": False,
        }


class Bundler:
    provider_name = "test-bundler"

    def __init__(self):
        self.calls = 0

    def fetch(self, token_address, chain):
        self.calls += 1
        return {
            "status": "complete",
            "provider": self.provider_name,
            "hard_blockers": [],
            "linked_cluster_count": 0,
            "execution_enabled": False,
        }


class IncompleteFreshSolanaSecurity:
    provider_name = "test-security"

    def fetch(self, contract_address, chain):
        return {
            "status": "complete",
            "provider": self.provider_name,
            "chain": "solana",
            "authority_data_complete": True,
            "data_complete": False,
            "risk_level": "medium",
            "flags": [
                {
                    "code": "holder_distribution_unknown",
                    "severity": "medium",
                    "message": "Holder rows are pending.",
                }
            ],
            "hard_blockers": ["security_data_incomplete"],
            "promotion_eligible": False,
            "execution_enabled": False,
        }


class HolderProvider:
    provider_name = "test-helius-holders"

    def __init__(self, largest=5, top_ten=30):
        self.largest = largest
        self.top_ten = top_ten
        self.calls = []

    def fetch_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "complete",
            "source": "helius",
            "holder_count": 100,
            "holder_scan_complete": True,
            "scanned_supply_coverage_pct": 100,
            "largest_scanned_owner_share_pct": self.largest,
            "top_10_scanned_owner_share_pct": self.top_ten,
            "concentration_excluded_owner_count": 1,
            "errors": [],
            "warnings": [],
        }


def test_venue_watch_alerts_once_and_reuses_completed_bundler(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "radar.db")
    provider = Provider(
        [
            _candidate("pump_fun", "solana", PUMP),
            _candidate("robinhood_chain", "robinhood", ROBINHOOD),
        ]
    )
    bundler = Bundler()

    first = run_venue_watch(
        provider=provider,
        security_provider=Security(),
        bundler_provider=bundler,
    )
    second = run_venue_watch(
        provider=provider,
        security_provider=Security(),
        bundler_provider=bundler,
    )
    downgraded = run_venue_watch(
        provider=provider,
        security_provider=Security(blocked={PUMP, ROBINHOOD}),
        bundler_provider=bundler,
    )

    first_by_venue = {item["venue"]: item for item in first["candidates"]}
    assert first_by_venue["pump_fun"]["signal_status"] == "screened_research"
    assert first_by_venue["robinhood_chain"]["signal_status"] == "research_now"
    assert first["notification"]["candidate_count"] == 2
    assert second["notification"]["notify"] is False
    assert downgraded["notification"]["safety_downgrade_count"] == 2
    assert all(
        item["notification_kind"] == "safety_downgrade"
        for item in downgraded["notification"]["candidates"]
    )
    assert bundler.calls == 1


def test_venue_watch_blocks_failed_contract_security(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "radar.db")
    report = run_venue_watch(
        provider=Provider([_candidate("robinhood_chain", "robinhood", ROBINHOOD)]),
        security_provider=Security(blocked={ROBINHOOD}),
        bundler_provider=Bundler(),
    )

    candidate = report["candidates"][0]
    assert candidate["signal_status"] == "blocked_security"
    assert candidate["token_security"]["hard_blockers"] == ["honeypot_detected"]
    assert report["notification"]["notify"] is False


def test_complete_helius_holders_fill_only_fresh_solana_distribution_gap(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "radar.db")
    candidate = _candidate("pump_fun", "solana", PUMP)
    candidate["pair_address"] = "curve-owner"
    holders = HolderProvider()
    report = run_venue_watch(
        provider=Provider([candidate]),
        security_provider=IncompleteFreshSolanaSecurity(),
        adoption_provider=holders,
        bundler_provider=Bundler(),
    )

    result = report["candidates"][0]
    assert result["signal_status"] == "screened_research"
    assert result["token_security"]["provider"] == "goplus+helius"
    assert result["token_security"]["promotion_eligible"] is True
    assert result["token_security"]["hard_blockers"] == []
    assert result["onchain_holder_analysis"]["holder_scan_complete"] is True
    assert holders.calls[0]["concentration_excluded_owners"] == ["curve-owner"]
    assert report["holder_scans"] == 1


def test_helius_holder_concentration_stays_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "radar.db")
    report = run_venue_watch(
        provider=Provider([_candidate("pump_fun", "solana", PUMP)]),
        security_provider=IncompleteFreshSolanaSecurity(),
        adoption_provider=HolderProvider(largest=25, top_ten=70),
        bundler_provider=Bundler(),
    )

    result = report["candidates"][0]
    assert result["signal_status"] == "blocked_security"
    assert "single_holder_concentration" in result["token_security"]["hard_blockers"]
    assert "top_holder_concentration" in result["token_security"]["hard_blockers"]
    assert report["notification"]["notify"] is False


def test_phone_report_includes_exact_contract_and_remaining_link_check():
    candidate = _candidate("robinhood_chain", "robinhood", ROBINHOOD)
    candidate.update(
        {
            "signal_status": "research_now",
            "change_state": "new",
            "signal_note": "Market and contract checks passed.",
            "token_security": {
                "status": "complete",
                "risk_level": "low",
                "hard_blockers": [],
            },
            "bundler_analysis": {"status": "not_available"},
        }
    )
    report = {
        "status": "complete",
        "provider": "test",
        "observed_at": "2026-09-01T12:00:00+00:00",
        "profiles_received": 1,
        "eligible_profiles": 1,
        "security_scans": 1,
        "bundler_scans": 0,
        "candidates": [candidate],
        "notification": {
            "notify": True,
            "candidate_count": 1,
            "candidates": [candidate],
        },
    }

    markdown = render_venue_report(report)

    assert ROBINHOOD in markdown
    assert "Robinhood Chain" in markdown
    assert "RESEARCH NOW — MANUAL LINK CHECK" in markdown
    assert "No wallet, private key, order, or automatic execution" in markdown
