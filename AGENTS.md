# Prospector — Agent Quick-Start

This file is the first thing a new agent session should read. It answers "where are we?" without requiring a full doc review.

---

## What This Project Is

**Prospector** is a locally-hosted system that autonomously discovers, evaluates, and refines price-action trading strategies for Hyperliquid crypto perpetual futures. A quantized 13B LLM runs continuously, selecting from human-authored strategy templates and proposing parameter configurations to backtest. The backtest harness evaluates each proposal and feeds structured results back to the model. A sliding window of recent results informs the next proposal; LoRA fine-tuning encodes long-term lessons.

The full design is in `docs/trading-strategy-discovery-synopsis.md`. The build plan is in `docs/implementation-plan.md`.

---

## Current Status (as of 2026-04-14) — project is pivoting

**This project is pausing the Elder-template parameter-search track and pivoting to strategy research.** See `docs/pivot-2026-04-14.md` for the full rationale. Summary:

- Oracle random search (n=2000) found an in-sample max score of 192.5.
- Walk-forward validation of the top-10 configs showed **100% of `false_breakout` configs die** (zero scored folds) and **`triple_screen` configs degrade 42–82%**. The in-sample ceiling is an overfitting artifact, not a discovered edge.
- The LLM inner loop added no value over random search in this problem shape (continuous parameter optimization).
- Root cause is signal density, not search efficiency — Elder templates produce 40–120 trades over the full ~5000-bar history, which cannot distribute across walk-forward folds.

**Current track:** Research phase — written prospectus on LLM-suitable denser-signal crypto strategies (funding-rate arb, event-driven, cross-exchange mispricing, calendar effects). No code until the prospectus is agreed. Do not resume the Elder-template track without a new directive.

| Unit | Description | Status |
|---|---|---|
| 1 | Data Layer: OHLCV download + orderbook poller | **Complete** (caveats below) |
| 2 | Strategy Templates | **Paused** — 2 built; 4 not being built |
| 3 | Backtest Harness | **Complete** |
| 4 | Orchestrator / Inner Loop | **Paused** |
| 5 | Ledger and Persistence | **Complete** |
| 6 | Dashboard | **Deferred** |
| 7 | Paper Trading | **Deferred** |
| 8 | Live Execution | **Deferred** |

**Reference docs for the pivot:**
- `docs/pivot-2026-04-14.md` — canonical pivot record; learnings, what survives, what's next
- `docs/walk-forward-findings.md` — full walk-forward analysis
- `scripts/walk_forward_top_configs.py` — reproduction script

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
│       ├── templates/
│       │   ├── base.py        ← Signal, Direction, MIN_REWARD_RISK, validate_ohlcv
│       │   ├── triple_screen.py
│       │   └── false_breakout.py
│       ├── harness/
│       │   ├── engine.py      ← run_backtest, BacktestConfig, BacktestResult, compute_score
│       │   └── walk_forward.py ← run_walk_forward, WalkForwardResult
│       ├── ledger.py          ← RunRecord, Ledger (SQLite append-only log)
│       └── orchestrator.py   ← run_loop, run_one_iteration, validate_config, assemble_prompt
├── tests/
│   ├── data/
│   │   └── test_download.py
│   ├── templates/
│   │   ├── test_base.py
│   │   └── test_false_breakout.py
│   ├── harness/
│   │   └── test_engine.py
│   ├── test_ledger.py
│   └── test_orchestrator.py
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

# Run the inner loop without Ollama (random schema-valid proposals)
PROSPECTOR_MOCK=1 python -m prospector.orchestrator
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

**Orchestrator prompt: only implemented templates.** The prompt registry shown to the LLM lists only `triple_screen` and `false_breakout` (the two implemented ones). Proposals for unimplemented templates are caught by `validate_config` and rejected as `invalid_schema`. Add templates to `_REGISTRY` in `orchestrator.py` as they are implemented.

**Orchestrator config via env vars.** `PROSPECTOR_MODEL` (default `qwen2.5-coder:14b`), `OLLAMA_HOST` (default `http://localhost:11434`), and `PROSPECTOR_MOCK` (set to `1`/`true`/`yes` to bypass Ollama and emit random schema-valid proposals — useful for shaking out the loop without a model server). No config file; override in the environment.

**Multi-security aggregation.** Per-security backtests run independently with separate $10k NAV. Aggregate: any catastrophic → catastrophic; all rejected → rejected; otherwise mean of scored results. Per-security breakdown stored as JSON blob in `securities_results_json` column.

**Diversity check (first version): exact match only.** A proposal is a duplicate if same template + same securities (order-independent) + identical params dict against any run in the recent sliding window. The normalized-distance approach from the spec is deferred.

---

## Known Gotchas

- **MacBook sleep interrupts the orderbook stream.** The reconnect loop in `orderbook.py` handles wake-up gracefully (5s delay, retry). Data will have gaps during sleep periods. "24/7" collection requires either preventing sleep (System Preferences → Energy Saver → "Prevent Mac from sleeping") or accepting gaps.
- **Train/test/holdout split not yet implemented.** The data layer downloads raw OHLCV but does not partition it into train/test/holdout windows. This is required before the backtest harness is complete.
- **`DATA_DIR` uses `parents[3]` in data modules, `parents[2]` in orchestrator.** `download.py` and `orderbook.py` are one level deeper (`src/prospector/data/`) so they use `parents[3]`. `orchestrator.py` is at `src/prospector/` and uses `parents[2]`. Both resolve to the repo root.
- **`pytest` must use `PYTHONPATH=src`** in the project root. Tests import `prospector.*` which requires the `src/` layout to be on the path.
- **Orchestrator needs Ollama running.** `python -m prospector.orchestrator` will fail with a connection error if Ollama is not running. Start it with `ollama serve` and pull the model: `ollama pull qwen2.5-coder:14b`. To exercise the loop without Ollama, set `PROSPECTOR_MOCK=1`.
- **OHLCV directory naming.** The download script writes to `data/ohlcv/<COIN>_PERP/<timeframe>.parquet` (full symbol with hyphens replaced by underscores), not `data/ohlcv/<COIN>/`. The orchestrator's `_coin_from_security` mirrors this convention via `replace("-", "_")`.
- **OHLCV data must be downloaded before running the orchestrator.** The orchestrator loads parquet files from `data/ohlcv/<COIN>/<timeframe>.parquet`. Run `python -m prospector.data.download` first.

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
