# Runbook

Operational guide for running Prospector scripts and services.

---

## Environment Setup

```bash
# Activate the project virtual environment
source /Users/wgilman/workspace/prospector/.venv/bin/activate

# Run tests
PYTHONPATH=src pytest -q tests

# Run linter
ruff check src tests scripts
```

---

## Data layer overview (as of 2026-04-23)

Canonical parquet tree at `data/kalshi/{markets,trades}/date=YYYY-MM-DD/part.parquet`. Built from two sources, merged and deduped by the writers:

- **TrevorJS HuggingFace** — migrated in once (see `scripts/migrate_trevorjs.py`) for historical coverage Jun 2021 → Jan 2026.
- **In-house `/historical/*` + live endpoints** — via `scripts/backfill_kalshi.py` and `scripts/pull_kalshi_incremental.py` for the Feb 2026 onwards window.

Cross-check 2026-04-23 verified byte-for-byte agreement on the overlap: 22 tickers / 12,862 trades, all count_delta=0 and trade_id_overlap=100%.

Hyperliquid funding + OHLCV at `data/hyperliquid/` and `data/ohlcv/`. Coinbase BTC-USD / ETH-USD 1m at `data/coinbase/<product>/1m.parquet` (used by the #4 FOMC event study — Hyperliquid's 1m retention is only ~3 days so historical 1m comes from Coinbase).

See [`../implementation/data-pipeline.md`](../implementation/data-pipeline.md) for the full map of which endpoints are retention-gated and which aren't.

## Daily data cron

`scripts/data_incremental_launchd.sh` runs three pulls sequentially:
1. Kalshi incremental (`scripts/pull_kalshi_incremental.py`) — appends trades since per-ticker watermark.
2. Hyperliquid incremental (`scripts/backfill_hyperliquid.py`) — funding + 1m/1h/4h/1d/1w candles.
3. Coinbase incremental (`python -m prospector.data.download_coinbase`) — 1m BTC-USD/ETH-USD; the only US-accessible deep-history source for 1m.

Installed via `scripts/launchd/com.prospector.data-incremental.plist`, daily at 03:00 local with catch-up-on-wake. Logs at `data/incremental/logs/incremental-YYYYMMDD.log`.

Consolidated on 2026-04-23 — the separate `com.prospector.ohlcv-refresh` job (02:00 daily, Hyperliquid 1w/4h/1d/1h only) was retired because the Hyperliquid step here now covers the full interval set. Retired plist archived at `~/Library/LaunchAgents/retired/com.prospector.ohlcv-refresh.plist`.

```bash
# Load
launchctl bootstrap gui/$UID scripts/launchd/com.prospector.data-incremental.plist

# Check
launchctl print gui/$UID/com.prospector.data-incremental | grep -E "state|last exit"

# Unload (e.g., for debugging)
launchctl bootout gui/$UID/com.prospector.data-incremental
```

---

## PM Underwriting Scripts

Currently still read from `data/kalshi_hf/` (the pre-migration HF parquets). A follow-up port would point them at `data/kalshi/{markets,trades}/date=*/part.parquet` and drop the cents-to-dollars `/100` scaling (unified tree already normalized to `[0, 1]`). Affected scripts: `build_calibration_curve.py`, `walk_forward_backtest.py`, `capital_constrained_sim.py`, `refresh_calibration_store.py`, `compute_sigma_table.py`, `return_distribution.py`. Until they're ported, keep `data/kalshi_hf/` on disk. Once ported, the HF directory can be deleted for 5.3 GB reclaim.

### Build Calibration Curve

Computes PIT prices at 50% of market duration via DuckDB ASOF join, bins by 5% implied probability, measures actual resolution rates. Outputs per-category curves with Wilson confidence intervals.

```bash
python scripts/build_calibration_curve.py [--data-dir DATA_DIR] [--min-volume 10]
```

**Outputs:**
- Console: per-category calibration tables, go/no-go decision
- `data/calibration/calibration_curves.png`: 8-panel plot (aggregate + 7 categories)

**Runtime:** ~3-4 minutes (loads 140M trades into DuckDB in-memory)

### Walk-Forward Backtest

70/30 temporal split. Builds calibration curves on train set, simulates portfolio on test set. (Phase 2 used fractional Kelly; the live paper trader uses equal-σ sizing — see §Paper-Trading Daemon.) Flat sizing (initial NAV) isolates edge from compounding.

```bash
python scripts/walk_forward_backtest.py [--data-dir DATA_DIR] [--min-volume 10]
```

**Outputs:**
- Console: portfolio metrics, per-category breakdown, calibration accuracy table, go/no-go
- `data/calibration/walk_forward_backtest.png`: NAV curve, cumulative P&L, P&L distribution, monthly P&L

**Runtime:** ~3-4 minutes

### Capital-Constrained Simulation

Extends the walk-forward backtest with concurrent position tracking, daily capital budget, per-event correlation caps, and throughput limits. Runs at configurable NAV with multiple trades-per-day caps (20, 50, 100, unlimited).

```bash
python scripts/capital_constrained_sim.py [--data-dir DATA_DIR] [--min-volume 10] [--nav 10000]
```

**Outputs:**
- Console: throughput comparison table, per-scenario detail, go/no-go
- `data/calibration/capital_constrained_sim.png`: return curves, utilization, open positions, daily P&L

**Runtime:** ~4-5 minutes (runs simulation 4 times for each throughput cap)

---

## Paper Trading (Phase 3)

Live paper-trading daemon for the PM underwriting strategy. Reads a persisted calibration snapshot, scans Kalshi every 15 min, enters paper positions in a local SQLite portfolio, and resolves positions as markets settle.

### Prerequisites

1. Kalshi API credentials. Set in the shell or a `.env` loaded before launch:

   ```bash
   export KALSHI_API_KEY_ID="<uuid from Kalshi dashboard>"
   export KALSHI_PRIVATE_KEY_PATH="/path/to/kalshi.pem"
   # or inline:
   # export KALSHI_PRIVATE_KEY_PEM="$(cat kalshi.pem)"
   ```

2. A calibration snapshot on disk. Build one from the HF dataset:

   ```bash
   python scripts/refresh_calibration_store.py [--min-volume 10]
   ```

   Writes `data/calibration/store/calibration-<timestamp>.json` and updates the `current.json` pointer.

### Run the Daemon

```bash
# Single tick (sweep resolutions, scan, enter, snapshot) — useful for smoke-testing
python scripts/paper_trade.py --once

# Long-running daemon at 15-min intervals
python scripts/paper_trade.py --interval 900

# Narrow to specific categories or raise the edge threshold
python scripts/paper_trade.py --categories sports crypto --min-edge-pp 4.0
```

**State:**
- Portfolio DB: `data/paper/pm_underwriting/portfolio.db` (positions + daily_snapshots)
- Calibration: `data/calibration/store/current.json`
- σ table: `data/calibration/sigma_table.json` (built by `scripts/compute_sigma_table.py`)
- Logs (under launchd): `data/paper/pm_underwriting/logs/paper_trade-YYYYMMDD.log` (daily, UTC)
- Strategy manifest: `data/paper/manifest.toml` — discovery index for the dashboard; daemons ignore it

Per-strategy directories under `data/paper/<strategy>/` keep each strategy's
DB + logs isolated so a second strategy (e.g. `crypto_perp`) can ship
without a restructure. The manifest file is the only check-in under
`data/paper/`; DBs and logs stay gitignored.

**Knobs** (see `scripts/paper_trade.py --help`):
- `--initial-nav` (default 10,000) — seeds the portfolio on first run only
- `--book-sigma-target` (0.02) — target σ of the book as a fraction of NAV
- `--n-target` (150) — expected steady-state count of concurrent positions
- `--sigma-table` (default `data/calibration/sigma_table.json`) — σ lookup by (category, side, 5¢ bin)
- `--max-position-frac` (0.01) — per-position risk cap vs NAV (defends against pathologically small σ)
- `--max-event-frac` (0.05) — per-event_ticker correlation cap
- `--max-bin-frac` (0.15) — per-(side, 5¢ bin) concentration cap (replaces the retired `--max-category-frac`)
- `--max-trades-per-day` (20) — daily throughput cap
- `--min-edge-pp` (5.0) — fee-adjusted edge floor (raised from 3.0 on 2026-04-21)

**Rebuilding the σ table.** Regenerate whenever the calibration snapshot is refreshed or the walk-forward window moves:

```bash
python scripts/compute_sigma_table.py
```

Output: `data/calibration/sigma_table.json` with per-bin σ (shrunk toward the pooled category/side σ with pseudo-count 200), pooled, and aggregate entries. The paper trader loads it at startup.

### Scheduled Ticks (launchd)

The plist in `scripts/launchd/com.prospector.paper-trade.plist` runs
`paper_trade.py --once` every 15 min via a shell wrapper that appends to a
UTC-dated log (so logs rotate naturally at midnight).

```bash
# Install / refresh
cp scripts/launchd/com.prospector.paper-trade.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.prospector.paper-trade.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.prospector.paper-trade.plist

# Check status / trigger a tick manually
launchctl list | grep paper-trade
launchctl start com.prospector.paper-trade

# Tail today's log
tail -f data/paper/pm_underwriting/logs/paper_trade-$(date -u +%Y%m%d).log
```

`StartInterval` counts from launch-time wall clock and queues a catch-up tick
when the Mac wakes from sleep. `RunAtLoad` is false — the first tick fires
after the 15 min interval elapses, so `launchctl load` doesn't duplicate a
manual run.

### Dashboard

Streamlit dashboard for paper-trading strategies. Reads `data/paper/manifest.toml`
and renders one panel per enabled strategy using the renderer for its position
schema. Today only `kalshi_binary` exists; adding a new schema is a new renderer
function in `src/prospector/dashboard.py`.

```bash
pip install -e .[dashboard]
streamlit run scripts/dashboard.py
```

Set `PROSPECTOR_MANIFEST=<path>` to point at an alternate manifest (useful for
smoke-testing against a copy of a DB before cutover).

Layout (kalshi_binary renderer): hero NAV card → KPI tiles (realized P&L,
locked risk, open, trades today) → NAV trajectory → **per-category sections**
(sports / crypto / politics / …) each showing a subtotal strip (open count,
locked risk, upside, avg edge, resolved W/L, realized P&L) above that
category's open positions → price-bin concentration chart → recent ticks
table. Theme (dark "quant terminal" — Fraunces display + JetBrains Mono
numbers + phosphor-green accent) lives in `.streamlit/config.toml` plus the
`inject_theme()` CSS block in `prospector.dashboard`.

---

## Elder-Track Scripts (Paused)

These scripts relate to the paused Elder-template parameter-search track.

### Walk-Forward Top Configs

Validates top-scoring configs from the orchestrator ledger with walk-forward analysis.

```bash
python scripts/walk_forward_top_configs.py
```

---

## Background Services (launchd)

| Service | plist | Schedule | Log |
|---|---|---|---|
| Paper trader | `~/Library/LaunchAgents/com.prospector.paper-trade.plist` | Every 15 min | `data/paper/pm_underwriting/logs/paper_trade-YYYYMMDD.log` |
| Orderbook poller | `~/Library/LaunchAgents/com.prospector.orderbook.plist` | Persistent (KeepAlive) | `logs/orderbook.log` |
| OHLCV refresh | `~/Library/LaunchAgents/com.prospector.ohlcv-refresh.plist` | Daily 2am | `logs/ohlcv-refresh.log` |

The orderbook and OHLCV services are from the paused Elder track and run
independently of the PM underwriting work.

```bash
# Check status
launchctl list | grep prospector

# Stop/start
launchctl stop com.prospector.orderbook
launchctl start com.prospector.orderbook
```

### Manual Hyperliquid Data Commands

```bash
# Download OHLCV data
python -m prospector.data.download

# Start orderbook poller manually
python -m prospector.data.orderbook

# Run orchestrator with mock model (no Ollama needed)
PROSPECTOR_MOCK=1 python -m prospector.orchestrator
```

---

## Data Locations

| Path | Contents | Gitignored |
|---|---|---|
| `data/kalshi_hf/` | Kalshi HuggingFace dataset (markets + trades parquet) | Yes |
| `data/calibration/` | Calibration curve outputs (plots, CSVs) | Yes |
| `data/calibration/store/` | Persisted calibration snapshots (live-trading lookups) | Yes |
| `data/paper/` | Paper-trading portfolio SQLite | Yes |
| `data/ohlcv/` | Hyperliquid OHLCV parquet files | Yes |
| `data/orderbook/` | Hyperliquid L2 snapshots | Yes |
| `data/*.db` | SQLite databases (orchestrator ledger) | Yes |
| `logs/` | Service logs | Yes |

---

## Known Gotchas

- **DuckDB memory:** The calibration scripts load ~140M trades into memory. Requires ~8 GB free RAM.
- **`pytest` path:** Must use `PYTHONPATH=src pytest` from project root.
- **WebSocket ping:** Hyperliquid doesn't respond to pings. `ping_interval=None` required in `websockets.connect()`.
- **MacBook sleep:** Orderbook poller reconnects on wake (5s delay) but data will have gaps.
