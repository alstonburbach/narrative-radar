"""On-demand fresh launch candidate batches using the normal safety pipeline.

A fresh batch is a different slice of the latest eligible profile universe. It
never skips market, contract-security, holder, or linked-wallet gates.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.collectors.venue_discovery import DexScreenerVenueProvider
from app.venue_watch import run_venue_watch


class RotatingBatchProvider:
    """Wrap the standard collector and expose a deterministic candidate page."""

    provider_name = "dexscreener_rotating_candidate_batch"

    def __init__(self, *, batch_index: int = 0, batch_size: int = 5):
        self.batch_index = max(0, int(batch_index))
        self.batch_size = max(1, min(int(batch_size), 10))
        self.inner = DexScreenerVenueProvider()

    def collect(
        self,
        *,
        venues,
        profile_limit_per_venue: int = 30,
        candidate_limit: int = 30,
    ) -> dict[str, Any]:
        # Pull a wider bounded universe, then choose a different page before the
        # expensive safety pipeline runs. This keeps refresh fast but honest.
        universe_limit = max(
            self.batch_size,
            min(30, (self.batch_index + 1) * self.batch_size),
        )
        report = self.inner.collect(
            venues=venues,
            profile_limit_per_venue=max(profile_limit_per_venue, universe_limit),
            candidate_limit=max(candidate_limit, universe_limit),
        )
        candidates = list(report.get("candidates") or [])
        start = self.batch_index * self.batch_size
        stop = start + self.batch_size
        page = candidates[start:stop]

        # If the requested page runs beyond the live universe, wrap to page 0
        # rather than fabricating candidates or returning stale hidden data.
        wrapped = False
        if not page and candidates and self.batch_index > 0:
            page = candidates[: self.batch_size]
            start = 0
            stop = len(page)
            wrapped = True

        result = dict(report)
        result["candidates"] = page
        result["candidate_count"] = len(page)
        result["selection"] = {
            "mode": "fresh_batch",
            "requested_batch_index": self.batch_index,
            "batch_size": self.batch_size,
            "universe_candidate_count": len(candidates),
            "slice_start": start,
            "slice_stop": stop,
            "wrapped_to_first_batch": wrapped,
        }
        return result


def build_report(*, batch_index: int, batch_size: int, venues: tuple[str, ...]) -> dict:
    provider = RotatingBatchProvider(batch_index=batch_index, batch_size=batch_size)
    report = run_venue_watch(
        provider=provider,
        venues=venues,
        profile_limit_per_venue=30,
        candidate_limit=30,
        security_limit=batch_size,
        onchain_limit=1,
        bundler_limit=1,
        persist=True,
    )
    report["candidate_selection"] = {
        "mode": "fresh_batch",
        "batch_index": max(0, int(batch_index)),
        "batch_size": max(1, min(int(batch_size), 10)),
        "note": "A new candidate batch still uses the normal fail-closed research gates.",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Find another bounded batch of current launch candidates.")
    parser.add_argument("--batch-index", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--venues", default="pump_fun,robinhood_chain")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    venues = tuple(v.strip().lower() for v in args.venues.split(",") if v.strip())
    try:
        report = build_report(
            batch_index=args.batch_index,
            batch_size=args.batch_size,
            venues=venues,
        )
    except Exception as exc:  # fail closed
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "execution_enabled": False,
            "note": "Fresh candidate selection failed safely; no unchecked token was promoted.",
        }, indent=2, sort_keys=True))
        return 1

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Fresh batch {args.batch_index}: {report.get('candidate_count', 0)} candidates")
        for row in report.get("candidates") or []:
            print(
                f"- {row.get('token_symbol') or 'unknown'} "
                f"{row.get('signal_status')} {row.get('contract_address')}"
            )
        print("Execution enabled: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
