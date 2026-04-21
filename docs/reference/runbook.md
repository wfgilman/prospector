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

## PM Underwriting Scripts

All scripts use the Kalshi HuggingFace dataset at `data/kalshi_hf/`. The dataset is 5.3 GB of parquet files and is gitignored. To download it, use `huggingface_hub.hf_hub_download()` for the `TrevorJS/kalshi-trades` dataset.

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
