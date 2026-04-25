# Hyperliquid Client

> `src/prospector/data/client.py` — Info-API wrapper for Hyperliquid
> perpetuals: OHLCV, funding rate history, premium index.

---

## What it does

Hyperliquid exposes a public Info API that returns market data without
authentication. The client wraps the endpoints we depend on and persists
the results to the `data/hyperliquid/` and `data/ohlcv/` parquet trees.

Strategy code does not call the client directly — it reads parquet via
DuckDB. The client is touched only by the daily cron and one-off backfills.

---

## Coverage

| Data | Granularity | History | Source endpoint |
|---|---|---|---|
| OHLCV | 1m | ~3 days (live retention) | `/info` candles |
| OHLCV | 1h, 4h, 1d, 1w | Full (since coin listing) | `/info` candles |
| Funding | Hourly | Full (since coin listing; HL launched May 2023) | `/info` funding history |
| Premium index | Live | Forward-only | `/info` |

**1m retention is ~3 days** — the only painful gap. For deeper sub-hour
crypto history we use [Coinbase](coinbase-client.md) (US-accessible
historical 1m source).

---

## Coins covered

Default backfill: `BTC`, `ETH`, `SOL`. Adding a coin is a one-line
addition to the `--coins` arg of `scripts/backfill_hyperliquid.py`.

---

## Scripts that use it

| Script | Purpose |
|---|---|
| `scripts/backfill_hyperliquid.py` | One-shot backfill of funding + 1m/1h/4h/1d/1w OHLCV |
| `data_incremental_launchd.sh` | Daily cron: incremental refresh, called from the consolidated cron job |

Storage layout:

```
data/hyperliquid/funding/<COIN>.parquet         # hourly funding
data/ohlcv/<COIN>_PERP/{1m,1h,4h,1d,1w}.parquet # candles
```

---

## What the client does NOT do

- **Trade execution** — separate concern; handled by the (future) live
  trader, not this client. The crypto-copy-bot sibling project has a
  Hyperliquid execution client we'd reference but not import.
- **L2 orderbook capture at scale** — the orderbook poller in
  `src/prospector/data/orderbook.py` exists but isn't actively used in any
  current strategy. Forward orderbook capture is a Phase 5 / future-track
  investment.
- **Premium index time-series persistence** — currently we read the live
  premium index when needed (e.g., the abandoned vol-surface work) but
  don't persist it.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (pre-project) | Use Hyperliquid as the perp exchange | CFTC-compatible, no securities classification, deep liquidity in BTC/ETH/SOL |
| 2026-04-22 | `funding_history()` added | Required for #10 vol-surface analysis (drift term in lognormal reference) and any cross-venue funding work |
| 2026-04-22 | 1m candle backfill added | Required for #4 narrative-spread re-run (granularity mismatch was the Phase-1 failure mode) |
| 2026-04-25 | Doc consolidated into platform/ | Was inline in implementation/data-pipeline.md |
