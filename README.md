# Narrative Radar

AI-assisted crypto narrative intelligence and paper-analysis platform.

## Current capabilities

- Pulls the strongest-liquidity DEX Screener pair for a contract.
- Stores market snapshots and research evidence in SQLite.
- Searches public web results through Tavily when `TAVILY_API_KEY` is configured.
- Separates search leads from manually verified primary-source evidence.
- Runs explainable red-team flags and a non-predictive research score.
- Produces hypothetical market-cap projections without placing orders.
- Includes a wallet accounting foundation that matches realized PnL to FIFO cost basis and keeps external deposits/withdrawals separate.
- Can read Solana wallet history through Helius and conservatively normalize complete swaps and priced transfers.

## Run locally

```text
python -m pip install -r requirements.txt
cp .env.example .env
python -m app.main --contract TOKEN_CONTRACT --chain base --paper-usd 100
```

Without a Tavily key, the market, red-team, score, and paper stages still run; web research is marked as unavailable.

To analyze a Solana wallet, add `HELIUS_API_KEY` and run `python -m app.wallet_main WALLET_ADDRESS`. SOL-quoted PnL is reported in SOL unless a historical quote-price resolver is added; it is never converted using today’s price.

## Run from GitHub Actions

Open Actions, choose `analyze token`, select `Run workflow`, and enter a contract and chain. Add `TAVILY_API_KEY` as a repository secret if live web research is wanted. The run produces a JSON report artifact and a short job summary.

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
