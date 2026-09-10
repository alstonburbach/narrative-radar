"""Collect live ecosystem activity and classify chain/launchpad rotation."""

from __future__ import annotations

import argparse
import json

from app.collectors.ecosystem_activity import DefiLlamaEcosystemActivityProvider
from app.market_rotation import build_market_rotation
from app.market_rotation_history import (
    prepare_rotation_observation,
    save_activity_snapshot,
)


def build_report(chains: tuple[str, ...], *, persist: bool = True) -> dict:
    collected = DefiLlamaEcosystemActivityProvider().collect(chains=chains)
    raw_observations = collected.get("observations") or []

    prepared = []
    for snapshot in raw_observations:
        # Build the comparison from prior Narra observations first so the current
        # sample can never leak into its own baseline.
        enriched = prepare_rotation_observation(snapshot)
        prepared.append(enriched)
        if persist and snapshot.get("coverage_status") != "failed":
            save_activity_snapshot(snapshot)

    rotation = build_market_rotation(prepared)
    return {
        "status": collected.get("status"),
        "chains_requested": list(chains),
        "observation_count": len(prepared),
        "failures": collected.get("failures") or [],
        "market_rotation": rotation,
        "history_persisted": persist,
        "execution_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chains",
        default="solana,robinhood,base,ethereum,bsc",
        help="Comma-separated chain keys.",
    )
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    chains = tuple(value.strip().lower() for value in args.chains.split(",") if value.strip())
    report = build_report(chains, persist=not args.no_persist)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Narrative Radar ecosystem rotation")
        for row in report["market_rotation"]["chains"]:
            rotation = row.get("rotation") or {}
            samples = row.get("baseline_sample_count", 0)
            print(
                f"{row.get('chain')}: {rotation.get('status')} "
                f"({rotation.get('score')}) history={samples}"
            )
        for row in report["market_rotation"]["venues"]:
            rotation = row.get("rotation") or {}
            samples = row.get("baseline_sample_count", 0)
            print(
                f"{row.get('chain')}/{row.get('venue')}: {rotation.get('status')} "
                f"({rotation.get('score')}) history={samples}"
            )
        if report["failures"]:
            print(f"provider failures: {len(report['failures'])}")


if __name__ == "__main__":
    main()
