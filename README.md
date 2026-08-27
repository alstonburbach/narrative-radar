# Narrative Radar

AI-assisted crypto narrative intelligence and paper-analysis platform.

## Current capabilities

- Pulls the strongest-liquidity DEX Screener pair for a contract.
- Stores market snapshots and research evidence in SQLite.
- Searches public web results through Tavily when `TAVILY_API_KEY` is configured.
- Separates search leads from manually verified primary-source evidence and reports whether dated evidence is recent, stale, future-dated, or unavailable.
- Searches separate lenses for builders, adoption, funding, token structure, and counterevidence, then measures source independence and corroboration after collapsing highly similar syndicated excerpts.
- Fetches selected primary/on-chain/secondary leads and checks whether the project identity appears in the underlying page, while keeping that content match separate from official verification.
- Persists compact evidence snapshots and reports whether a narrative is strengthening, weakening, or still too new to judge across repeated runs.
- On Solana, optionally records holder counts, token-account scan coverage, token supply, and bounded finalized transfer activity as separate on-chain activity proxies.
- Persists discovery scans and reports which candidate signals survive across repeated independent runs.
- Counts recurring signals across the full scan window and attaches transparent follow-up queries for builder, adoption, funding, on-chain, and counterevidence review.
- Runs explainable red-team flags and a non-predictive research score.
- Produces hypothetical market-cap projections and manual-review order previews without placing orders, with position size screened against current liquidity.
- Includes a wallet accounting foundation that matches fee-adjusted realized PnL to FIFO cost basis, reports fee drag, and keeps external deposits/withdrawals separate.
- Can read Solana wallet history through Helius and conservatively normalize complete swaps and priced transfers.
- Persists wallet accounting snapshots and requires repeated positive, non-contaminated runs before labeling a wallet a repeatable realized-PnL candidate.

## Run locally

```text
python -m pip install -r requirements.txt
cp .env.example .env
python -m app.main --contract TOKEN_CONTRACT --chain base --paper-usd 100
python -m app.discovery_main --topic "stablecoin rails" --json
python -m app.main --contract SOLANA_MINT --chain solana --json
```

Without a Tavily key, the market, red-team, score, and paper stages still run; web research is marked as unavailable.

The narrative report is intentionally skeptical: search results are leads, not proof. A high-quality result needs multiple independent domains, more than social discussion, and manual verification of primary sources. The counterevidence lens is included so a project is not judged only from promotional claims.

Repeated token analyses use the local SQLite history to compare evidence quality, independent-source count, adoption-lens coverage, and counterevidence. The GitHub token workflow caches that database between runs; this tracks evidence durability, not investment returns.

When `HELIUS_API_KEY` is configured, Solana token analyses also collect a bounded on-chain snapshot. Holder counts come from token accounts by mint; transfer activity is measured from a finalized 24-hour transaction window. The report keeps this separate from DEX volume and labels incomplete scans as lower bounds. These metrics can include pools, routers, bots, exchanges, airdrop recipients, and other non-user addresses, so they are activity proxies rather than proof of human adoption.

The Solana snapshot also reports scanned supply coverage and largest/top-10 scanned-owner shares. These are concentration and scan-coverage diagnostics—not a claim that the owners are humans—and concentration is marked as a lower bound when the holder scan is incomplete.

The `discover narratives` GitHub workflow runs manually and on weekdays at 12:00 UTC. It caches compact discovery history so recurring candidate signals can be reviewed for persistence. Set `TAVILY_API_KEY` for live web research; set `HELIUS_API_KEY` for Solana on-chain activity collection.

To analyze a Solana wallet, add `HELIUS_API_KEY` and run `python -m app.wallet_main WALLET_ADDRESS`. SOL-quoted PnL is reported in SOL unless a historical quote-price resolver is added; it is never converted using today’s price.

For a bounded research watchlist, run `python -m app.wallet_cohort_main --wallets "$WALLETS" --json`, where `WALLETS` is newline-separated. The cohort report ranks only wallets with repeated clean realized-PnL evidence, marks shorter histories as early-watch, and excludes contaminated, mixed, unchanged, or failed results from candidate ranking. A run accepts at most 50 wallets.

Repeated wallet analyses use the same SQLite history to test whether positive realized PnL persists. Missing or unpriced Solana network fees fail closed instead of being silently treated as zero, and strategies whose matched fees consume more than half of pre-fee realized profit are excluded from candidate status. A candidate is downgraded when cost basis is incomplete, quote assets are mixed without conversion, transfers are unpriced, or external inflows are large relative to realized PnL. Three clean positive snapshots are still only a research candidate—not a guarantee and never an automatic copy-trading instruction.

Wallet reports also measure whether profit is concentrated in a few winning trades. With a meaningful sample, a wallet whose largest win supplies more than 75% of gross winning PnL or whose top three wins supply more than 90% is flagged and removed from research-candidate status; this helps separate repeatable activity from one-trade luck.

Wallet reports also show the realized-PnL observation window, profitable calendar months, approximate realized ROI on matched cost basis, holding style, realized drawdown, and known external-flow counterparties. A meaningful sample compressed into less than seven days, dominated by one profitable period, funded mostly by one known external source, or carrying a drawdown above 50% of matched cost basis is flagged. These are risk filters for research, not proof that a wallet owner is a scammer or that a strategy will continue.

## Manual order previews

Pass `--order-preview-usd 100` and optionally `--order-side sell` to `app.main` to generate a paper-only proposal. It includes the selected pair, reference price, estimated token quantity, liquidity-size checks, and explicit blocking conditions. It never checks balances, estimates exact slippage, signs a transaction, or submits an order. Every preview requires manual approval and reports `execution_enabled: false`.

## Run from GitHub Actions

Open Actions, choose `discover narratives` to search a sector before you know a contract, or choose `analyze token` to verify a specific token. Add `TAVILY_API_KEY` as a repository secret if live web research is wanted. Each run produces a JSON report artifact and a short job summary.

## Wallet-quality design

The wallet module is deliberately paper/research-only at this stage. It does not trust a displayed PnL number. A future chain adapter must normalize swaps, fees, transfers, bridges, and timestamps, then the analyzer will:

1. match sells to actual buy lots;
2. exclude inbound deposits and airdrops from trading profit;
3. flag sells with incomplete cost basis;
4. require a meaningful history of closed trades;
5. score consistency, drawdown, liquidity, slippage, and latency before a wallet is considered a study candidate.

Copy-trading execution is intentionally not implemented. A positive wallet score is not proof of future performance.

## Safety

All output is research and paper-analysis output. It is not financial advice, does not predict returns, and never submits a trade.

Paper projections now include a current-liquidity size screen for the hypothetical entry and each target value. Manual order previews reuse that screen. It is a rough risk label—not an exact slippage calculation—and does not change the market-cap multiple math.