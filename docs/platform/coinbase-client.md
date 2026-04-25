# Coinbase Client

> `src/prospector/data/coinbase_client.py` + `download_coinbase.py` —
> 1m candle backfill for US-accessible deep-history crypto data.

---

## Why Coinbase

The Hyperliquid info API caps 1m OHLCV retention at ~3 days. Binance
global returns 451 to US IPs. Coinbase is the only US-accessible exchange
with deep historical 1m candles for BTC and ETH at the granularity we need.

Empirically, Coinbase BTC-USD tracks Hyperliquid BTC-USD perp at >0.99
correlation on sub-hour bars during active trading windows. So Coinbase 1m
is a fine reference for any analysis whose horizon doesn't depend on the
~10-30 bps perp/spot basis.

---

## Coverage

| Pair | Granularity | History |
|---|---|---|
| BTC-USD | 1m | Full (years; Coinbase exposes deep history) |
| ETH-USD | 1m | Full |

Higher-granularity intervals (1s) are not currently pulled — no strategy
needs them yet.

---

## Storage

```
data/coinbase/BTC-USD/1m.parquet
data/coinbase/ETH-USD/1m.parquet
```

Single-file per pair (not date-partitioned) because the volume is
manageable and downstream queries are typically full-history scans rather
than time-bounded.

---

## What it does NOT do

- **Trade execution** — Coinbase is read-only for this project
- **Spot-vs-perp basis tracking** — the crypto-copy-bot sibling does this
  for its funding-arb strategy; we reference but don't replicate
- **Orderbook capture** — not currently needed by any strategy

---

## Where it's used

- **#4 FOMC event study** — the original failure was at hourly
  granularity; the Phase 3 re-run on 15-min Coinbase data showed correct
  sign but magnitude near zero
- **Future regime-conditional studies** — any analysis that needs sub-hour
  crypto reference outside Hyperliquid's 3-day window

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-23 | Coinbase 1m backfill shipped | Hyperliquid 1m retention insufficient for #4 re-run; Binance global blocked from US |
| 2026-04-25 | Doc consolidated into platform/ | Was inline in implementation/data-pipeline.md and the #4 deep-dive |
