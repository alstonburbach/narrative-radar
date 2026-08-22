from datetime import datetime, timezone

from app.collectors.market import fetch_market_data


def create_research_job(contract_address: str, chain: str) -> dict:
    return {
        "contract_address": contract_address,
        "requested_chain": chain.lower(),
        "status": "research_pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def print_section(title: str):
    print(f"\n{'=' * 45}")
    print(title)
    print("=" * 45)


def main():
    print_section("NARRATIVE RADAR V0.1")

    contract = input("\nToken contract: ").strip()
    chain = input("Chain (base/bsc/solana/etc): ").strip()

    job = create_research_job(contract, chain)

    print_section("RESEARCH JOB")

    for key, value in job.items():
        print(f"{key}: {value}")

    print("\nCollecting live market data...")

    try:
        market = fetch_market_data(contract)

    except Exception as exc:
        print(f"\nMarket collector failed: {exc}")
        return

    print_section("MARKET SNAPSHOT")

    if not market["found"]:
        print("No active DEX pair found for this contract.")
        return

    for key, value in market.items():
        print(f"{key}: {value}")

    print_section("PIPELINE STATUS")
    print("Market Collector: COMPLETE")
    print("Narrative Detective: NOT YET CONNECTED")
    print("Red Team: NOT YET CONNECTED")
    print("Scoring Engine: NOT YET CONNECTED")
    print("Paper Tracker: NOT YET CONNECTED")


if __name__ == "__main__":
    main()