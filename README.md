# Narrative Radar

Research-first crypto narrative intelligence for screening tokens without placing
live orders. The current pipeline combines:

- DexScreener market data, with chain-aware pair selection
- optional Tavily web research and normalized evidence records
- a transparent narrative score with visible components
- red-team warnings for liquidity, momentum, dilution, and source-quality risks
- SQLite persistence for market snapshots and evidence

## Run it

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Offline/deterministic market mode:

```bash
python -m app.main <contract-address> --chain base --no-web --json
```

Interactive mode:

```bash
python -m app.main
```

Web research uses `TAVILY_API_KEY` from `.env`. Copy `.env.example` to `.env`
and add the key when live research is wanted. Without a key, the market report
still completes and clearly reports the research warning.

The output is a research report only. `execution.live_orders` is always
`false`; this project does not connect to a wallet or place trades.

## Tests

```bash
python -m pytest -q
```

The Tavily integration test is skipped unless `TAVILY_API_KEY` is set.
