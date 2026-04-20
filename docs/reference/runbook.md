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

70/30 temporal split. Builds calibration curves on train set, simulates portfolio on test set with fractional Kelly sizing. Flat sizing (initial NAV) isolates edge from compounding.

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

## Elder-Track Scripts (Paused)

These scripts relate to the paused Elder-template parameter-search track.

### Walk-Forward Top Configs

Validates top-scoring configs from the orchestrator ledger with walk-forward analysis.

```bash
python scripts/walk_forward_top_configs.py
```

---

## Hyperliquid Data Services (launchd)

Two background services run under macOS launchd for Hyperliquid data collection. These are from the original Elder track and are independent of the PM underwriting work.

| Service | plist | Schedule | Log |
|---|---|---|---|
| Orderbook poller | `~/Library/LaunchAgents/com.prospector.orderbook.plist` | Persistent (KeepAlive) | `logs/orderbook.log` |
| OHLCV refresh | `~/Library/LaunchAgents/com.prospector.ohlcv-refresh.plist` | Daily 2am | `logs/ohlcv-refresh.log` |

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
