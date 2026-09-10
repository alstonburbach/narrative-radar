"""Collect live ecosystem activity and classify chain/launchpad rotation."""

from __future__ import annotations

import argparse
import json

from app.collectors.ecosystem_activity import DefiLlamaEcosystemActivityProvider
from app.market_rotation import build_market_rotation


def build_report(chains: tuple[str, ...]) -> dict:
    collected = DefiLlamaEcosystemActivityProvider().collect(chains=chains)
    observations = collected.get("observations") or []
    rotation = build_market_rotation(observations)
    return {
        "status": collected.get("status"),
        "chains_requested": list(chains),
        "observation_count": len(observations),
        "failures": collected.get("failures") or [],
        "market_rotation": rotation,
        "execution_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chains",
        default="solana,robinhood,base,ethereum,bsc",
        help="Comma-separated chain keys.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    chains = tuple(value.strip().lower() for value in args.chains.split(",") if value.strip())
    report = build_report(chains)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Narrative Radar ecosystem rotation")
        for row in report["market_rotation"]["chains"]:
            rotation = row.get("rotation") or {}
            print(f"{row.get('chain')}: {rotation.get('status')} ({rotation.get('score')})")
        for row in report["market_rotation"]["venues"]:
            rotation = row.get("rotation") or {}
            print(f"{row.get('chain')}/{row.get('venue')}: {rotation.get('status')} ({rotation.get('score')})")
        if report["failures"]:
            print(f"provider failures: {len(report['failures'])}")


if __name__ == "__main__":
    main()
