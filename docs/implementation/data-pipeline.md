# Implementation Plan — In-House Data Pipeline

**Status:** Scoped 2026-04-22. Triggered by [`docs/rd/deep-dive-kalshi-hyperliquid-vol-surface.md`](../rd/deep-dive-kalshi-hyperliquid-vol-surface.md) §13 investigation. Elevated from "nice-to-have" to **core project competency** — our strategies are quantitatively driven, and quantitative conclusions require data whose bugs, shortcuts, and design flaws we own.

## 1. Rationale

### What's wrong with the status quo

- **Kalshi data is a third-party HF snapshot.** The TrevorJS/kalshi-trades dataset (5.3 GB parquet at `data/kalshi_hf/`) is internally validated (99.71% consistency) and was good enough for PM Underwriting Phase 1–3 because PM's signal survives small per-trade noise. But it:
  - Ends 2026-01-30 (stale by ~3 months and counting).
  - Has no incremental refresh path — we'd have to re-download the full snapshot.
  - Shapes we can't inspect or audit (column semantics, timezone conventions, de-dup rules, fill interpolation).
  - Cannot be extended to new data types (orderbook snapshots, fills-by-side, maker/taker attribution).
- **Hyperliquid data coverage is partial.** We have 1h/4h/1d OHLCV at `data/ohlcv/BTC_PERP/` and similar but:
  - No funding rate time series — blocking for #10 Phase 3 (and any cross-venue funding-spread work).
  - No premium index or mark-vs-index basis — blocking for a perp-implied term structure.
  - No 1m candles — blocking for realized-vol estimation at any finer horizon than hourly.
  - Coverage starts 2025-09-17 despite older events existing in Kalshi data — an incidental artifact of when downloads happened, not by design.

### Why build rather than buy

- **Data quality is load-bearing for all strategies.** PM Underwriting has already been bitten once by PIT-pricing nuances (`docs/rd/sibling-project-insights.md` §2). #10's Week-1 spike revealed how sensitive signal detection is to reference-distribution choice — debugging that is tractable only when we fully own the data layer.
- **Strategy-independence.** A good pipeline serves #10 (cross-market vol arb), #4 (narrative spread), the PM book, and future strategies without re-architecting each time.
- **Audit trail.** "What did we see at time T?" must be a reproducible query, not a question about a black-box third-party snapshot.
- **Known-provenance = credible findings.** Every statistical conclusion we publish for ourselves needs a traceable data lineage.

### What we are *not* building

- Not a real-time market-data infrastructure (no L3 / full tick capture, no colocation-grade latency). Minute-resolution for candles, tick-level for trades, 1s-resolution for order book snapshots is plenty.
- Not a derivatives-pricing library — the pipeline delivers raw data; strategies compute derivatives.
- Not a replacement for the `kalshi-arb-trader` execution client (we reference it for auth patterns, but don't depend on it).

---

## 2. Scope

### Kalshi

| Layer | What | Priority |
|---|---|---|
| **REST client** | Own HTTP wrapper (RSA-PSS auth); no dependency on `kalshi-arb-trader` | P0 |
| **Historical backfill** | Iterate events → trades → markets → fills via public API; paginated, idempotent, resumable | P0 |
| **Incremental pull** | Cron-friendly script: fetch new markets + trades since last high-watermark; append to partitioned parquet | P0 |
| **Orderbook snapshots** | Poll active markets' L2 at fixed cadence (e.g., every 5 min during event life) | P1 |
| **Category/event taxonomy** | Persist normalized `(category, side, event_ticker, ticker, bucket_lower, bucket_upper)` tuple per market | P0 |
| **Schema** | Parquet partitioned by `date=YYYY-MM-DD` under `data/kalshi/{trades,markets,orderbooks}/`; DuckDB-queryable | P0 |

### Hyperliquid

| Layer | What | Priority |
|---|---|---|
| **REST client extensions** | Extend existing `src/prospector/data/client.py` with funding-rate and premium-index endpoints | P0 |
| **Funding-rate backfill** | Historical hourly funding per coin → parquet | P0 |
| **1m candles for realized vol** | Extend `download.py` to support 1m granularity on major coins | P0 |
| **Premium index time series** | Near-real-time polling; sufficient for term-structure reconstruction | P1 |
| **Live orderbook snapshots** | 1s cadence for top N coins during active research windows | P2 |

### Cross-cutting

| Layer | What | Priority |
|---|---|---|
| **Validation harness** | Cross-check in-house pull vs. TrevorJS HF on overlap window; flag discrepancies; expected: ≤ random-trade-ordering noise | P0 |
| **Sanity monitors** | Post-pull checks: trade-count deltas vs. recent trend, price-range sanity, gap detection in incremental runs | P0 |
| **Timestamp discipline** | All timestamps UTC at rest; any conversion is explicit and tested; no tz-naive columns in parquet | P0 |
| **Query API** | Small module (`src/prospector/data/query.py` or similar) that returns DuckDB connections scoped to the partitioned parquet layout | P1 |

---

## 3. Design principles

1. **Parquet + DuckDB** is the storage substrate. Same pattern PM Underwriting and #10 already use — no new technology introduced.
2. **Partitioned by date**. Trivially pruneable for any time-bounded query. Immutable once written (old partitions never rewritten).
3. **Idempotent backfill.** Re-running a backfill command for a given date range produces byte-identical output modulo non-deterministic ordering. Enables safe retries after interruptions.
4. **Incremental = replay-safe.** The incremental pull never overwrites; it appends. High-watermark state is separate from the data.
5. **All upstream schema in one taxonomy file.** One canonical `categorize.py`-style module defines field meanings. If Kalshi adds a new field, we explicitly decide whether to persist it — no silent schema drift.
6. **One validation per source.** Every new data type has a test in `tests/data/` that compares a small pull against a hand-curated expected output. Breaks loudly if the API changes under us.
7. **Keep it in-repo — for now.** Module boundary at `src/prospector/data/ingest/` so a future spin-out to a `prospector-data` repo is mechanical. No premature extraction. Threshold for spin-out: when a second, unrelated consumer needs it (e.g., kalshi-autoagent swapping its own client in for ours).

---

## 4. Milestones and gates

| Milestone | Exit criterion | Owner |
|---|---|---|
| **M1 — Kalshi REST + historical backfill** | Full backfill of 2024–2026 trades + markets for `KXBTC-*`, `KXETH-*`, plus all PM Underwriting categories, matches TrevorJS HF on overlap window to ≤ random-trade-ordering noise | P0 |
| **M2 — Hyperliquid funding + 1m candles** | Funding history for BTC, ETH, SOL across full available history (Hyperliquid launched May 2023); 1m candles for same coins Jan 2024 → present | P0 |
| **M3 — Incremental pull + sanity monitors** | `scripts/pull_kalshi_incremental.py` and `scripts/pull_hyperliquid_incremental.py` runnable on cron; fails loudly on schema or volume anomaly | P0 |
| **M4 — Query API** | `from prospector.data.query import kalshi_trades, hl_candles, hl_funding` returns DuckDB relations scoped to the partitioned layout | P1 |
| **M5 — Validation report** | Written comparison of in-house vs. TrevorJS on 2024-01 → 2026-01 overlap; any systematic disagreement documented and explained | P0 |

### Blocking relationships

- **M1 + M2 are blocking for #10 Phase 3** (re-validation on fresh data requires both).
- **M3 is non-blocking for #10 Phase 3** but required before the PM paper book migrates off TrevorJS.
- **M4–M5 are quality-of-life** but should land before any new strategy is stood up on top.

### Rough sizing

- M1: 4–6 days. RSA-PSS auth, pagination, idempotent backfill, cross-check harness.
- M2: 2–3 days. Straightforward extension of existing `download.py`/`client.py`.
- M3: 2 days. Cron-safe, watermark state in SQLite (same pattern as PM's calibration store).
- M4: 1 day. Thin wrapper.
- M5: 1 day. Plot + short doc.

**Total: ~2 weeks of focused work.**

---

## 5. Existing code we keep

- `src/prospector/data/client.py` — Hyperliquid info-API wrapper. Extend for funding + premium index; don't rewrite.
- `src/prospector/data/download.py` — parquet writer for Hyperliquid candles. Pattern carries to Kalshi.
- `src/prospector/data/orderbook.py` — L2 snapshot handling. Reference for orderbook persistence.
- `src/prospector/strategies/pm_underwriting/categorize.py` — canonical category taxonomy. Share with the pipeline so categorization is applied consistently at ingest-time.

## 6. Existing code we explicitly don't depend on

- `kalshi-arb-trader` client (sibling project). Reference for auth pattern and endpoint shapes, but copy-paste with review rather than importing. Principle: we own every line that touches our data.
- TrevorJS HF dataset — stays on disk for the validation cross-check during M5, removed from any strategy's runtime dependency once M1 is validated.

---

## 7. Open questions

1. **Storage growth rate.** 154M Kalshi trades = 5.3 GB. In-house pull adds orderbook snapshots + our own backfill overhead. Rough estimate: 10–20 GB/year at current market activity. Acceptable on local disk? Yes, but flag for revisit at year-boundary.
2. **Incremental cadence.** Daily cron is fine for research; real-time would be needed only if we stand up a live trader on the vol-surface strategy, which is months out. Start daily.
3. **Credentials.** Kalshi RSA keypair — same as `kalshi-arb-trader` uses. User owns the key.  File locations and .env conventions TBD; defer until M1 starts.
4. **Hyperliquid funding historical depth.** Publicly available funding history may have gaps pre-launch of specific coins. Document, don't remediate.
5. **Spin-out trigger.** Defined as "a second unrelated consumer needs it." We should revisit at M5 — if by then the kalshi-autoagent project has expressed interest in swapping to our pull, that's the trigger.

## 8. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Elevate in-house data pipeline to core project competency | User directive: "our investment strategies are quantitatively driven so we need good quantitative data." Triggered by #10 Week-1 spike revealing how sensitive findings are to reference-distribution and sample-selection choices. |
| 2026-04-22 | Keep in-repo at `src/prospector/data/ingest/` with module boundary for future spin-out | PM Underwriting already depends on the data layer; forcing two-repo coordination before the API is stable adds friction for no benefit. |
| 2026-04-22 | Prioritize M1 (Kalshi) + M2 (Hyperliquid funding) as blocking for #10 Phase 3 | These two data gaps are the only ones strictly required to re-validate #10's thesis. Other M's can slip. |
| 2026-04-22 | **M1 code shipped** (pending user pilot + cross-check) | KalshiClient extended with `iter_trades` + `series_ticker` on events; ingest module at `src/prospector/data/ingest/kalshi/` with writer/watermark/backfill/incremental; CLI scripts (`backfill_kalshi.py`, `pull_kalshi_incremental.py`, `crosscheck_kalshi_hf.py`); 48 unit tests passing. Next: user runs a small pilot (`--max-events 3 --series KXBTC FED`) and cross-checks against TrevorJS HF. |

---

## 9. M1 — current state and next-action runbook

### 9.1 What shipped in this work stream

**Client (`src/prospector/kalshi/client.py`):**
- `iter_trades(ticker, min_ts, max_ts)` — paginated, ts-bounded trade fetch with cursor
- `iter_events(status, series_ticker)` — now takes a series filter and comma-separated status list
- `_parse_trade` + `Trade` dataclass in `models.py`

**Ingest module (`src/prospector/data/ingest/kalshi/`):**
- `writer.py` — partitioned parquet writers for trades/markets/events with atomic writes, trade_id dedup, and per-day deduplication for markets. UTC at rest.
- `watermark.py` — JSON-backed per-ticker watermark state at `data/kalshi/_state.json`. Tracks last_trade_id + last_trade_time per ticker.
- `backfill.py` — driver: walks settled events for a series, pulls markets + full trade history per ticker, writes partitions. Resumable (skips tickers with a watermark unless `--no-skip`).
- `incremental.py` — daily-cron driver: refreshes events, snapshots open markets, appends new trades since watermark. Does not back-fill new tickers (backfill owns initial pulls).

**CLI scripts:**
- `scripts/backfill_kalshi.py` — the historical pull entry point. Supports `--series`, `--max-events`, `--status`, `--rate-limit-sleep`, `--no-skip`.
- `scripts/pull_kalshi_incremental.py` — cron entry point.
- `scripts/crosscheck_kalshi_hf.py` — validates the ingest output against TrevorJS HF on the overlap window. Per-ticker: count delta, trade_id overlap, price-weighted sum delta. Pre-registered thresholds at the top of the file.

**Tests (`tests/data/ingest/kalshi/`, `tests/kalshi/`):**
- Writer idempotency + partition boundary + UTC-date partitioning
- Watermark roundtrip + boundary parsing
- Trade parser (cents and `*_dollars` fields) + created_time validation
- `iter_trades` pagination + min_ts/max_ts URL shape
- `iter_events` series filter
- Total: 48 tests green

### 9.2 Runbook — user's next actions

Because Claude Code cannot access the user's Kalshi credentials or make live API calls for them, the M1 validation is handed off. Minimal pilot to prove the pipeline end-to-end:

1. **Confirm credentials.**
   ```
   echo $KALSHI_API_KEY_ID
   ls -l $KALSHI_PRIVATE_KEY_PATH
   ```
   If unset, point the env to the same RSA keypair `kalshi-arb-trader` uses.

2. **Small pilot — 3 events per series, two series.** Takes ~5 minutes wall time, ≤50 API calls.
   ```
   source .venv/bin/activate
   PYTHONPATH=src python scripts/backfill_kalshi.py \
       --series KXBTC FED \
       --max-events 3 \
       --verbose
   ```
   Expected output: a summary table with events/markets/trades counts and partition paths under `data/kalshi/`.

3. **Cross-check against TrevorJS HF on the overlap window.**
   ```
   PYTHONPATH=src python scripts/crosscheck_kalshi_hf.py
   ```
   Expected pass criteria (per-ticker):
     - `|count_delta| ≤ 1` on > 99% of tickers
     - `trade_id_overlap ≥ 99%`
     - `rel_sum_delta ≤ 0.1%`
   Output at `data/kalshi/_crosscheck.txt` + per-ticker CSV.

4. **Report back.** If cross-check passes, M1 is validated and we scale to the full series list. If it fails, the failure mode tells us what to debug (pricing units, trade_id semantics, boundary inclusion, time zone, etc.).

5. **Full backfill** once pilot validates:
   ```
   PYTHONPATH=src python scripts/backfill_kalshi.py --verbose
   ```
   Runs across the default series list (KXBTC/ETH/DOGE family, NFL/NBA/sports, FED rate-threshold contracts). Expected wall time: several hours depending on trade density. Resumable via the watermark, so interruption is safe.

### 9.3 M2 scope (Hyperliquid funding + 1m candles)

M2 kicks off after M1 validation passes. Scope is smaller because `src/prospector/data/client.py` already has the Hyperliquid info-API wrapper — we extend rather than start fresh. Sketch:
- Add `funding_history(coin, start_ms, end_ms)` → parquet writer
- Add 1m granularity to the existing `download.py` candle pull
- Funding + 1m candles partitioned by UTC date under `data/hyperliquid/`
- Sanity monitors mirroring the Kalshi pattern

Rough sizing: 2-3 days.
