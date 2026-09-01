# Narrative Radar

AI-assisted crypto narrative intelligence and paper-analysis platform.

## Current capabilities

- Pulls the strongest-liquidity DEX Screener pair for a contract.
- Stores market snapshots and research evidence in SQLite.
- Searches public web results through Tavily when `TAVILY_API_KEY` is configured.
- Falls back to bounded recent public RSS feeds from crypto publishers and official Solana/Ethereum sources when Tavily is not configured; feed headlines remain unverified leads.
- Separates search leads from manually verified primary-source evidence and reports whether dated evidence is recent, stale, future-dated, or unavailable.
- Searches separate lenses for builders, adoption, funding, token structure, and counterevidence, then measures source independence and corroboration after collapsing highly similar syndicated excerpts.
- Fetches selected primary/on-chain/secondary leads and checks whether the project identity appears in the underlying page, while keeping that content match separate from official verification.
- Persists compact evidence snapshots and reports whether a narrative is strengthening, weakening, or still too new to judge across repeated runs.
- On Solana, optionally records holder counts, token-account scan coverage, token supply, and bounded finalized transfer activity as separate on-chain activity proxies.
- Uses Helius to inspect the earliest bounded Solana token transactions, group first-acquisition owners by shared fee payer, transaction, and slot, and trace bounded pre-acquisition SOL funding for the largest early wallets. Concentrated observable links block promotion; weak same-slot patterns remain review warnings.
- On Robinhood Chain, inspects exact-pair transfer logs in a bounded launch-block window, groups first-acquisition wallets by transaction sender and block, and checks bounded normal/internal Blockscout funding history. Any provider gap remains partial rather than being called safe.
- Persists discovery scans and reports which candidate signals survive across repeated independent runs.
- Runs narrative discovery from an owner-only phone issue form and posts material scheduled discoveries to one GitHub feed issue.
- Scans free public feeds every four hours and runs one deeper Tavily-backed web scan daily when its key is configured, while notifying only on material evidence-backed changes.
- Watches bounded DEX Screener latest-profile feeds every fifteen minutes for exact-contract Pump.fun and Robinhood Chain launch leads. It requires a confirmed launch venue, live pair, recent pair age, minimum liquidity/activity, and separate contract-security and linked-wallet gates before a candidate can reach the phone research feed; one candidate per chain per run can receive the bounded wallet check.
- Normalizes common narrative aliases (for example, stablecoin/digital-dollar and meme-coin/memecoin wording), rejects unsafe prefix matches such as `inside`/`insider`, and ranks cross-source watch options as `research_next`, `watch_for_confirmation`, or `insufficient_evidence`; every option remains blocked from possible-buy review until an exact contract passes token checks.
- Counts recurring signals across the full scan window and attaches transparent follow-up queries for builder, adoption, funding, on-chain, and counterevidence review.
- Runs explainable red-team flags and a non-predictive research score.
- Produces hypothetical market-cap projections and manual-review order previews without placing orders, with position size screened against current liquidity.
- Applies a transparent manual-review gate that reports whether score, evidence quality, freshness, red-team risk, source checks, and optional order-preview requirements pass.
- Uses read-only GoPlus security data on Base, BSC, Ethereum, Robinhood Chain, and Solana to block obvious honeypots, sell restrictions, severe taxes, dangerous admin permissions, exposed LP ownership, and extreme holder concentration.
- Evaluates fixed-stake paper baskets, including target hit rates, break-even winner multiples, known-cost coverage, open versus realized results, narrative-family concentration, and forward-test timestamp integrity.
- Freezes owner-created paper signals from a phone issue, preserves the original timestamp and market-cap snapshot, and marks open signals hourly without custody or execution.
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
python -m app.venue_watch_main --venues pump_fun,robinhood_chain --json
python -m app.paper_basket_main --input paper-basket.json --stake-usd 50 --target-multiple 10 --json
```

## Use from a phone

Open the repository's **Issues** tab, choose **New issue**, and select
**Scan a token**. Paste one public contract address, choose the chain (or
`auto`), and submit the issue. An owner-only GitHub workflow runs the full
market, narrative, red-team, optional Solana activity, paper projection, and
manual-review checks, then replies on the same issue with a compact report.

Choose **Discover narratives** when you do not know a contract yet. Keep the
broad default or enter a theme such as `AI agents`, `stablecoin payments`, or
`Solana consumer apps`. The phone report shows recent evidence links and only
labels a candidate when a term survives at least two independent domains and
two positive research lenses.

The scheduled **Pump.fun + Robinhood Chain launch watch** is the faster exact-
contract lane. Every fifteen minutes it checks bounded latest token profiles,
confirms the contract against a live pair, applies transparent liquidity,
activity, age, drawdown, sell-pressure, and market-cap/liquidity gates, and then
runs read-only GoPlus security on the strongest bounded candidates. When a new
Pump.fun token's authority data is available before GoPlus holder indexing, one
bounded complete Helius holder scan may fill only that distribution gap; missing
coverage still fails closed. It posts to
one `[RADAR LAUNCH WATCH]` issue only when a new candidate reaches the available
gates or materially strengthens. A Pump.fun address-pattern match alone is not
enough; its launch DEX must also confirm the venue. Robinhood candidates now run
a bounded exact-pair same-block, transaction-sender, and indexed pre-funding
check. The report exposes each coverage dimension, and partial RPC or explorer
history remains unknown rather than passing.

The launch-watch issue body is refreshed on every successful scheduled pass so
the phone beta can read the current bounded screen without treating old alert
comments as live candidates. New comments remain change-only alerts: they are
added only when a candidate first clears a gate, materially strengthens, or is
downgraded for safety.

Choose **Start a paper signal** once you want to measure a token prospectively.
The issue workflow freezes the issue time and first live market-cap snapshot,
runs the full research and safety gate, and starts with a hypothetical $50 stake
and 10x target by default. A separate hourly workflow updates the same bot
comment and posts a new alert only when a sampled 2x, 3x, 5x, or selected target
is first crossed. Closing the issue stops tracking. The highest value is only
the highest scheduled sample; intrahour moves, fees, taxes, slippage, supply
changes, and real fill constraints are not known.

Editing a token-scan or discovery issue reruns that research and updates the
existing bot comment. Paper-signal issues run only when opened, so an edit
cannot rewrite the original entry. Workflow reruns recover the existing bot
state instead of creating a later entry. Requests
from accounts other than the repository owner are ignored so outsiders cannot
consume the configured Tavily or Helius credits. Never place a private key or
seed phrase in an issue. The phone report never signs or submits a transaction.

Without a Tavily key, Narrative Radar uses the free public-feed fallback. It
checks only recent feed items, skips slow or failed sources, reports source
failures, and never upgrades a headline to verified evidence. Tavily remains
the broader search provider when its repository secret is configured.
When the daily `auto` scan cannot find that secret, the report now states that
the deep web scan is inactive instead of silently presenting RSS as the
requested provider.

The narrative report is intentionally skeptical: search results are leads, not proof. A high-quality result needs multiple independent domains, more than social discussion, and manual verification of primary sources. The counterevidence lens is included so a project is not judged only from promotional claims.

Repeated token analyses use the local SQLite history to compare evidence quality, independent-source count, adoption-lens coverage, and counterevidence. The GitHub token workflow caches that database between runs; this tracks evidence durability, not investment returns.

When `HELIUS_API_KEY` is configured, Solana token analyses also collect a bounded on-chain snapshot. Holder counts come from token accounts by mint; transfer activity is measured from a finalized 24-hour transaction window. The report keeps this separate from DEX volume and labels incomplete scans as lower bounds. These metrics can include pools, routers, bots, exchanges, airdrop recipients, and other non-user addresses, so they are activity proxies rather than proof of human adoption.

The Solana snapshot also reports scanned supply coverage and largest/top-10 scanned-owner shares. These are concentration and scan-coverage diagnostics—not a claim that the owners are humans—and concentration is marked as a lower bound when the holder scan is incomplete.

The `discover narratives` GitHub workflow checks up to ten results per lens
from free public feeds every four hours and performs one deeper `auto` scan
daily at 13:43 UTC (Tavily when its
key exists, otherwise the public-feed fallback). It can also run manually. It
caches compact discovery history and opens or comments on one
`[RADAR FEED]` issue. Every successful scheduled pass refreshes that issue body
so the private beta can distinguish current unattended evidence from an old
alert. Comments remain change-only alerts: unchanged or weak scans update the
current evidence without notifying, while fresh cross-source candidates that
first appear, change, or materially strengthen also add an alert comment. Set
`TAVILY_API_KEY` for broader live web research; set `HELIUS_API_KEY` for Solana
on-chain activity collection. Scheduled public-feed checks never consume the
Tavily key; the single daily deep scan is the spend-bounded web-search pass.

To analyze a Solana wallet, add `HELIUS_API_KEY` and run `python -m app.wallet_main WALLET_ADDRESS`. SOL-quoted PnL is reported in SOL unless a historical quote-price resolver is added; it is never converted using today’s price.

For a bounded research watchlist, run `python -m app.wallet_cohort_main --wallets "$WALLETS" --json`, where `WALLETS` is newline-separated. The cohort report ranks only wallets with repeated clean realized-PnL evidence, marks shorter histories as early-watch, and excludes contaminated, mixed, unchanged, or failed results from candidate ranking. A run accepts at most 50 wallets.

Repeated wallet analyses use the same SQLite history to test whether positive realized PnL persists. A strategy candidate also requires complete recognition of the fetched transaction types; skipped history is never silently treated as non-trading activity. Missing or unpriced Solana network fees fail closed instead of being silently treated as zero, skipped transaction types are reported as incomplete coverage, and strategies whose matched fees consume more than half of pre-fee realized profit are excluded from candidate status. A candidate is downgraded when cost basis is incomplete, quote assets are mixed without conversion, transfers are unpriced, or external inflows are large relative to realized PnL. Three clean positive snapshots are still only a research candidate—not a guarantee and never an automatic copy-trading instruction.

Wallet reports also measure whether profit is concentrated in a few winning trades. With a meaningful sample, a wallet whose largest win supplies more than 75% of gross winning PnL or whose top three wins supply more than 90% is flagged and removed from research-candidate status; this helps separate repeatable activity from one-trade luck.

Wallet reports also show the realized-PnL observation window, profitable calendar months, approximate realized ROI on matched cost basis, holding style, realized drawdown, and known external-flow counterparties. A meaningful sample compressed into less than seven days, dominated by one profitable period, funded mostly by one known external source, or carrying a drawdown above 50% of matched cost basis is flagged. These are risk filters for research, not proof that a wallet owner is a scammer or that a strategy will continue.

## Manual order previews

Every supported contract scan now requests a read-only GoPlus security report. The gate
fails closed when that report is unavailable and blocks high-risk findings such
as honeypot behavior, restrictive selling, severe taxes, closed or mutable
contract controls, exposed liquidity ownership, or concentrated holders. These
are heuristics, not proof that a token is safe or fraudulent. GoPlus holder data
alone does not establish whether apparently separate wallets were funded
together or bought in the same bundle. When `HELIUS_API_KEY` is configured for
a Solana scan, Narrative Radar adds a bounded launch-window adapter: it checks
the earliest token transactions, shared fee payers, multi-wallet transactions,
same-slot first acquisitions, and recent SOL funding sources for the largest
early wallets. A concentrated cluster blocks promotion; incomplete coverage
leaves `bundler_concentration` in manual review. Shared funders or same-slot
activity can come from exchanges, sponsored transactions, airdrops, routers, or
organic high-throughput trading, so these are observable risk links—not proof
of common ownership or fraud.

Robinhood Chain uses the official public RPC by default, or `ROBINHOOD_RPC_URL`
for a production/archive provider. Bounded pre-acquisition history uses the
official Blockscout instance and accepts an optional
`ROBINHOOD_BLOCKSCOUT_API_KEY`. The adapter verifies mainnet chain ID 4663,
chunks transfer-log queries, rejects removed/malformed logs, and reports partial
coverage whenever an RPC chunk, transaction lookup, or funding page is missing.

Pass `--order-preview-usd 100` and optionally `--order-side sell` to `app.main` to generate a paper-only proposal. It includes the selected pair, reference price, estimated token quantity, a five-minute market-snapshot freshness gate, liquidity-size checks, and explicit blocking conditions. It never checks balances, estimates exact slippage, signs a transaction, or submits an order. Every preview requires manual approval and reports `execution_enabled: false`.

The JSON report also includes `decision_gate`. `manual_review_ready` means the research requirements passed for a human to inspect; `research_only` means one or more non-blocking requirements still need work; `blocked` means a hard safety requirement failed. If no order preview is requested, the gate evaluates research only. The gate always reports `execution_enabled: false` and never authorizes a transaction.

To test the fixed-risk basket idea, provide a JSON list (or `{ "positions": [...] }`) where each position has `label`, `entry_market_cap`, and an explicit `outcome`: `closed` with `exit_market_cap`, `lost`, or `open` with `mark_market_cap`. Optional `fees_usd`, `slippage_usd`, and `narrative_family` fields are tracked transparently. Missing costs are flagged, and open positions remain marked rather than being counted as realized profit.

For a basket to count as a forward-tested strategy result, every position must also include timezone-aware `signal_detected_at`, `entry_recorded_at`, and `outcome_observed_at` timestamps. The evaluator rejects impossible ordering and future-dated observations, reports signal-to-entry latency and observed holding time, and keeps untimestamped PnL descriptive rather than presenting it as proof the radar found the move in advance.

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
