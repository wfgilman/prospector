# Data Pipeline

> The unified Kalshi + Hyperliquid + Coinbase data tree, the daily
> incremental cron, the retention model, and the validation discipline
> that lets us trust quantitative findings.

**Status:** Operational. M1 (Kalshi historical + incremental), M2
(Hyperliquid funding + 1m candles + OHLCV), M3 (daily cron) all shipped.

---

## Why we own the data layer

Strategies in this project are quantitatively driven; quantitative
conclusions require data whose bugs, shortcuts, and design flaws we own.
This was elevated from "nice-to-have" to **core project competency** on
2026-04-22 after the #10 vol-surface Week-1 spike revealed how sensitive
signal detection is to reference-distribution choice — debugging that is
tractable only when we fully own the data layer.

We also do not build:
- Real-time market-data infrastructure (no L3 / full-tick / colocation)
- A derivatives-pricing library (the pipeline delivers raw data; strategies derive)
- A replacement for the sibling-project execution clients

---

## What's in the tree

### Canonical Kalshi tree

```
data/kalshi/
├── markets/date=YYYY-MM-DD/part.parquet     # 1,665+ partitions, ~17.5M rows
├── trades/date=YYYY-MM-DD/part.parquet      # 1,674+ partitions, ~154.6M rows
└── _state.json                              # per-ticker watermark for incremental
```

- Date range: **2021-06-30 → present**, daily incremental
- Built from two sources, merged + deduped by the writers:
  - **TrevorJS HuggingFace** dataset migrated once via `scripts/migrate_trevorjs.py` (Jun 2021 → Jan 2026)
  - **In-house `/historical/*` + live endpoints** via `scripts/backfill_kalshi.py` and `scripts/pull_kalshi_incremental.py` (Feb 2026 → present)
- Cross-check on overlap window: **byte-for-byte agreement** (22 tickers, 12,862 trades; per-ticker count_delta=0, trade_id overlap=100%, weighted-sum delta ≤ 2.3e-16)

### Hyperliquid

```
data/hyperliquid/
└── funding/<COIN>.parquet                   # BTC, ETH, SOL — full history

data/ohlcv/<COIN>_PERP/
├── 1m.parquet
├── 1h.parquet
├── 4h.parquet
├── 1d.parquet
└── 1w.parquet
```

- Funding: hourly, full history (Hyperliquid launched May 2023)
- 1m OHLCV: ~3-day live retention (the reason we use Coinbase for deeper 1m)
- 1h/4h/1d/1w OHLCV: full history

### Coinbase

```
data/coinbase/<PAIR>/1m.parquet              # BTC-USD, ETH-USD
```

The only US-accessible deep-history source for sub-hour BTC/ETH (Binance
global returns 451 to US IPs). Used by the #4 FOMC event study and any
other strategy that needs >3-day 1m crypto history.

---

## Schema

### Trades (`data/kalshi/trades/`)

| Column | Type | Notes |
|---|---|---|
| `trade_id` | VARCHAR | Stable Kalshi trade ID; primary dedup key |
| `ticker` | VARCHAR | Market ticker |
| `event_ticker` | VARCHAR | Event ticker (parent of market) |
| `count` | BIGINT | Trade size |
| `yes_price` | DOUBLE | YES price in [0, 1] |
| `no_price` | DOUBLE | NO price in [0, 1] (= 1 - yes_price) |
| `taker_side` | VARCHAR | "yes" or "no" — which side took liquidity |
| `created_time` | TIMESTAMP WITH TZ | UTC |
| `date` | DATE | Hive-partition column (UTC date of `created_time`) |

### Markets (`data/kalshi/markets/`)

| Column | Type | Notes |
|---|---|---|
| `ticker` | VARCHAR | Market ticker |
| `event_ticker` | VARCHAR | Parent event |
| `series_ticker` | VARCHAR | Series prefix (e.g. `KXNFL`, `KXBTC`) |
| `title`, `yes_sub_title`, `no_sub_title` | VARCHAR | Human-readable; `yes_sub_title` carries strike-range text used by PM calibration |
| `status` | VARCHAR | `active`, `settled`, `finalized`, `voided` |
| `result` | VARCHAR | `yes`, `no`, or empty |
| `open_time`, `close_time`, `expiration_time` | TIMESTAMP WITH TZ | UTC |
| `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price` | DOUBLE | All prices in [0, 1] |
| `volume`, `volume_24h`, `open_interest` | BIGINT | |
| `category` | VARCHAR | Kalshi-supplied category |
| `pulled_at` | TIMESTAMP WITH TZ | When this snapshot was taken |
| `date` | DATE | Hive-partition (UTC date of `pulled_at`) |

The markets table is **per-snapshot**, not per-market. Multiple rows for
the same ticker on the same day reflect multiple snapshots. The writer
collapses to the latest per (ticker, date) on write.

---

## Endpoints — retention map

| Data | Live endpoint retention-gated? | Historical alternative |
|---|---|---|
| Trades | Yes — `/markets/trades` returns 0 for old tickers | `/historical/trades` — full history, ticker-filtered, public no-auth |
| Market metadata | Yes — `/markets/{tkr}` 404s for old, `/events/{evt}` returns `markets:[]` | `/historical/markets` — full history, richer schema (includes `settlement_ts`, `rules_primary`) |
| Event metadata | No — `/events` always works (back to 2021) | n/a |
| L2 orderbook | **Yes — no historical counterpart** | **Unrecoverable** — must capture live going forward |
| Account orders | n/a | `/historical/orders` (auth-required) |

**Implication:** L2 orderbook history is the one thing we cannot
backfill. Strategies that need orderbook depth must either capture it
forward in time or operate without it.

---

## Daily cron

`scripts/data_incremental_launchd.sh` runs three pulls sequentially, daily
at 03:00 local:

1. **Kalshi incremental** (`scripts/pull_kalshi_incremental.py`) — appends
   trades since per-ticker watermark in `_state.json`. Snapshots open
   markets that have movements.
2. **Hyperliquid incremental** (`scripts/backfill_hyperliquid.py`) —
   funding + 1m/1h/4h/1d/1w candles for BTC, ETH, SOL.
3. **Coinbase incremental** (`python -m prospector.data.download_coinbase`) —
   1m BTC-USD / ETH-USD; the only US-accessible deep-history source.

Installed via `scripts/launchd/com.prospector.data-incremental.plist`,
loaded with `launchctl bootstrap gui/$UID`. Catch-up-on-wake. Logs at
`data/incremental/logs/incremental-YYYYMMDD.log`.

A previously-separate `com.prospector.ohlcv-refresh` job was retired
2026-04-23; the consolidated job now covers the full interval set.

---

## API gotchas (memorialize-once-and-forget)

These are consequential surprises that cost time the first time and
shouldn't cost time again:

- **`/events?status=` is single-value only.** Comma-separated silently returns 0 results.
- **`FED-YYMMM` event tickers live under the `KXFED` series**, not `FED`.
- **`/markets?event_ticker=X` fails for resolved events.** Use `/events/{event_ticker}` which embeds markets.
- **Trades API** uses `count_fp` (fractional) instead of legacy `count`. Both parsers handle both.
- **Kalshi markets schema migrated to `*_dollars` string fields** in January 2026; we parse those and fall back to legacy cents fields.
- **`yes_price` is float [0, 1]** in our unified tree. PM scripts cast back to int cents via SQL for downstream arithmetic preservation.
- **Hyperliquid 1m OHLCV has ~3-day retention.** Use Coinbase for deeper 1m crypto history.
- **Binance global returns 451 to US IPs.** Coinbase is our historical source.

---

## Data quality monitoring

What we check:

- **Internal consistency** — yes_price + no_price = 1.0 per trade (Kalshi
  construction)
- **Per-event ladder sum** — should be close to 1.0 on snapshots with
  sufficiently complete strike ladders (sum-to-1 wedge is what
  `kalshi-autoagent` exploits)
- **Non-zero trade counts** after the `count_fp` fix
- **Trade-count deltas vs. recent trend** on incremental runs (sanity
  check for upstream drift)
- **Spot-verify against Kalshi web UI** for one currently-open event when
  the in-house pull is the only source

What we explicitly don't check:
- Mid-flight schema breakage during a daily run — surfaces as parser
  errors which fail loudly
- Future Kalshi product launches with new event-ticker prefixes — would
  fall into "other" category until added to `categorize.py`

---

## Module layout

```
src/prospector/
├── kalshi/
│   ├── client.py               # REST client, RSA-PSS auth
│   └── models.py               # Market, Trade, Orderbook, Position
├── data/
│   ├── client.py               # Hyperliquid info-API wrapper
│   ├── coinbase_client.py      # Coinbase 1m candle fetcher
│   ├── download.py             # Hyperliquid OHLCV writer
│   ├── download_coinbase.py    # Coinbase 1m writer
│   ├── download_funding.py     # Hyperliquid funding writer
│   ├── orderbook.py            # L2 snapshot handling
│   └── ingest/kalshi/
│       ├── writer.py           # Partitioned parquet writers
│       ├── watermark.py        # Per-ticker incremental state
│       ├── backfill.py         # Historical-pull driver
│       └── incremental.py      # Cron driver
└── strategies/pm_underwriting/
    └── categorize.py           # Canonical category taxonomy
```

The strategy code (PM Underwriting) reuses `categorize.py` so categorization
is applied consistently at both ingest-time and analysis-time.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Elevate in-house data pipeline to core project competency | #10 Week-1 spike revealed sensitivity to reference-distribution choice; debugging is tractable only when we own the data |
| 2026-04-22 | M1 (Kalshi REST + backfill) shipped | RSA-PSS auth, pagination, idempotent writes, watermark state |
| 2026-04-22 | Retention discovery: live endpoints only expose recent events | Binary-searched KXBTC settled events; oldest accessible 2026-02-15 (~18%) |
| 2026-04-22 | M2 (Hyperliquid funding + 1m candles) shipped | `funding_history()`, `download_funding.py`, `backfill_hyperliquid.py` |
| 2026-04-23 | `/historical/*` namespace discovered; cross-check passes 100% | Public endpoints for full history (trades + markets); validates pipeline byte-for-byte against TrevorJS on overlap |
| 2026-04-23 | TrevorJS migrated into unified tree; `data/kalshi_hf/` deletable | `scripts/migrate_trevorjs.py`; ~27 min wall time, schema unified |
| 2026-04-23 | Daily cron consolidated (data-incremental absorbs ohlcv-refresh) | Single launchd plist runs all three pulls sequentially |
| 2026-04-25 | Doc moved from `implementation/data-pipeline.md` to `platform/data-pipeline.md` | Documentation reorg; this is platform infrastructure, not a one-time implementation plan |
