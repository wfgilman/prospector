# Prospector — Agent Quick-Start

This file is the first thing a new agent session should read. It answers "where are we?" without requiring a full doc review.

---

## What This Project Is

**Prospector** is a locally-hosted system that autonomously discovers, evaluates, and refines price-action trading strategies for Hyperliquid crypto perpetual futures. A quantized 13B LLM runs continuously, selecting from human-authored strategy templates and proposing parameter configurations to backtest. The backtest harness evaluates each proposal and feeds structured results back to the model. A sliding window of recent results informs the next proposal; LoRA fine-tuning encodes long-term lessons.

The full design is in `docs/trading-strategy-discovery-synopsis.md`. The build plan is in `docs/implementation-plan.md`.

---

## Current Build Status (as of 2026-04-13)

| Unit | Description | Status |
|---|---|---|
| 1 | Data Layer: OHLCV download + orderbook poller | **Complete** (caveats below) |
| 2 | Strategy Templates | **Partial** — `triple_screen`, `false_breakout` done; 4 remaining |
| 3 | Backtest Harness | **Complete** |
| 4 | Orchestrator / Inner Loop | Not started |
| 5 | Ledger and Persistence | Not started |
| 6 | Dashboard | Not started |
| 7 | Paper Trading | Not started |
| 8 | Live Execution | Not started |

**Immediate next task:** Complete the remaining 4 strategy templates (`impulse_system`, `channel_fade`, `kangaroo_tail`, `ema_divergence`), then build the ledger (unit 5) and orchestrator (unit 4).

---

## Repository Layout

```
prospector/
├── AGENTS.md                  ← you are here
├── pyproject.toml             ← build config, dependencies
├── src/
│   └── prospector/
│       ├── data/
│       │   ├── client.py      ← HyperliquidClient (sync httpx)
│       │   ├── download.py    ← OHLCV download script
│       │   └── orderbook.py   ← live L2 WebSocket poller
│       └── templates/
│           ├── base.py        ← Signal, Direction, MIN_REWARD_RISK, validate_ohlcv
│           ├── triple_screen.py
│           └── false_breakout.py
├── tests/
│   ├── data/
│   │   └── test_download.py
│   └── templates/
│       ├── test_base.py
│       └── test_false_breakout.py
├── data/
│   ├── ohlcv/                 ← parquet files, one per coin/timeframe
│   └── orderbook/             ← parquet files, one per coin per day
├── logs/
│   ├── orderbook.log          ← launchd-managed WebSocket poller output
│   └── ohlcv-refresh.log      ← launchd-managed daily OHLCV refresh output
└── docs/
    ├── trading-strategy-discovery-synopsis.md
    ├── implementation-plan.md
    ├── trading-strategies.md
    ├── strategy-output-contract.md
    ├── scoring-function.md
    ├── prompt-template.md
    └── terminology.md
```

---

## Environment and Tooling

```bash
# Activate the project virtual environment
source /Users/wgilman/workspace/prospector/.venv/bin/activate

# Run tests
PYTHONPATH=src pytest -q tests

# Run linter
ruff check src tests

# Download OHLCV data (all configured pairs)
python -m prospector.data.download

# Start orderbook poller manually (normally managed by launchd)
python -m prospector.data.orderbook
```

**Target pairs (POC):** BTC-PERP, ETH-PERP, SOL-PERP

---

## Background Processes (launchd)

Two processes run in the background under macOS launchd:

| Process | plist | Schedule | Log |
|---|---|---|---|
| Orderbook WebSocket poller | `~/Library/LaunchAgents/com.prospector.orderbook.plist` | Persistent (KeepAlive=true) | `logs/orderbook.log` |
| OHLCV daily refresh | `~/Library/LaunchAgents/com.prospector.ohlcv-refresh.plist` | Daily at 2am | `logs/ohlcv-refresh.log` |

Check/control them with:
```bash
launchctl list | grep prospector
launchctl stop com.prospector.orderbook
launchctl start com.prospector.orderbook
```

---

## Key Implementation Decisions

**Templates, not code generation.** The LLM outputs only a JSON config (`{template, params, securities, rationale}`). All strategy execution logic is human-authored Python. See `docs/trading-strategy-discovery-synopsis.md` for the full rationale.

**Hyperliquid 1h data cap.** The API returns max 5000 candles per request. At 1h resolution this is ~208 days. 4h gives ~833 days; 1d gives ~13 years. New templates should be tested primarily on 4h/1d data if long histories are needed.

**Orderbook polling, not historical L2.** Hyperliquid provides no historical L2 data via API. We poll live WebSocket data and store locally to build a slippage calibration dataset over time. The harness uses a conservative flat assumption (0.05% per side) until enough data accumulates.

**WebSocket ping must be disabled.** Hyperliquid doesn't respond to client pings. `ping_interval=None` is required in the `websockets.connect()` call; omitting it causes the connection to be closed with error 1011 after 20 seconds.

**Iron Triangle.** Every trade must have entry/stop/target with ≥ 2:1 reward:risk and 2% NAV risk sizing. Templates enforce geometry at construction time (`Signal.__post_init__`). The harness enforces sizing. Neither is a model-tunable parameter.

**Signal geometry validation.** `Signal` is a frozen dataclass. `__post_init__` raises `ValueError` for invalid geometry (stop ≥ entry for LONG, etc.). Templates catch this and skip the signal.

---

## Known Gotchas

- **MacBook sleep interrupts the orderbook stream.** The reconnect loop in `orderbook.py` handles wake-up gracefully (5s delay, retry). Data will have gaps during sleep periods. "24/7" collection requires either preventing sleep (System Preferences → Energy Saver → "Prevent Mac from sleeping") or accepting gaps.
- **Train/test/holdout split not yet implemented.** The data layer downloads raw OHLCV but does not partition it into train/test/holdout windows. This is required before the backtest harness is complete.
- **Backtrader not yet evaluated.** It's listed in the tech stack but the harness hasn't been built. Evaluate at unit 3 implementation time; migrate if it becomes a constraint.
- **`DATA_DIR` uses `parents[3]`.** Both `download.py` and `orderbook.py` resolve data paths with `Path(__file__).resolve().parents[3] / "data" / ...`. This resolves to the repo root. Using `parents[4]` was a bug (now fixed) that wrote data to the parent of the workspace.
- **`pytest` must use `PYTHONPATH=src`** in the project root. Tests import `prospector.*` which requires the `src/` layout to be on the path.

---

## Docs Reference

| Doc | Purpose |
|---|---|
| `docs/trading-strategy-discovery-synopsis.md` | Architecture, design rationale, tech stack, lessons from sibling projects |
| `docs/implementation-plan.md` | Build units, dependency order, status, deviations from plan |
| `docs/trading-strategies.md` | Six strategy templates: what they do, how they work |
| `docs/strategy-output-contract.md` | JSON schema the LLM must produce; per-template parameter tables |
| `docs/scoring-function.md` | NAV simulation formula, hard gates, diagnostic metrics, transaction cost model |
| `docs/prompt-template.md` | The actual prompt sent to the LLM each iteration |
| `docs/terminology.md` | Definitions for all jargon used in the codebase and docs |
