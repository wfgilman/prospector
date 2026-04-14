# Implementation Plan

This document defines the implementation units for Prospector, their dependencies, and the order of work. The design specs are complete (see sibling docs); this plan covers the build.

---

## Current Status (as of 2026-04-13)

| Unit | Description | Status | Notes |
|---|---|---|---|
| 1 | Data Layer | **Complete** (partial) | OHLCV + orderbook done; train/test split pending |
| 2 | Strategy Templates | **In progress** | `triple_screen`, `false_breakout` done; 4 remaining |
| 3 | Backtest Harness | **Complete** | |
| 4 | Orchestrator | **Complete** (skeleton) | 2 templates active; expand as templates added |
| 5 | Ledger | **Complete** | SQLite append-only log |
| 6 | Dashboard | Not started | |
| 7 | Paper Trading | Not started | |
| 8 | Live Execution | Not started | |

**Immediate next task:** Run `python -m prospector.orchestrator` end-to-end to verify the skeleton works against real Ollama. Then complete the 4 remaining strategy templates (`impulse_system`, `channel_fade`, `kangaroo_tail`, `ema_divergence`) to widen the search space.

## Language

Python. The entire ecosystem aligns: pandas/numpy for data analysis, Hyperliquid Python SDK for API access, Ollama Python client for local LLM inference, and mature backtest tooling. No reason to introduce a second language.

---

## Implementation Units

Eight units, roughly in dependency order. Units 1–3 form a self-contained vertical slice that can be validated without any LLM involvement.

### 1. Project Scaffolding and Data Layer ✓ (Complete with caveats)

Set up the repo structure, virtual environment, and Hyperliquid historical OHLCV download pipeline.

**Deliverables:**
- Repo layout: `src/`, `tests/`, `data/`, `docs/`, `logs/` ✓
- Dependency management (pyproject.toml + pip/venv) ✓
- Hyperliquid API client for historical candle data (`src/prospector/data/client.py`) ✓
- Download script: fetch OHLCV for target pairs and timeframes, store as local parquet files (`src/prospector/data/download.py`) ✓
- Data schema: timestamp, open, high, low, close, volume per row ✓
- Orderbook/depth snapshots for slippage calibration (`src/prospector/data/orderbook.py`) ✓
- launchd background processes for persistent collection ✓ (added — not in original plan)
- Train/test/holdout split logic — **NOT YET IMPLEMENTED** (required before harness)

**Target pairs (POC):** BTC-PERP, ETH-PERP, SOL-PERP. Expand after vertical slice is validated.

**Data availability by timeframe:**
| Timeframe | Available History | Candle Count | Notes |
|---|---|---|---|
| 1h | ~208 days | 5000 (API max) | Insufficient for multi-year validation |
| 4h | ~833 days | 5000 (API max) | Good for strategy development |
| 1d | ~13 years | 5000 (API max) | Full history available |

The Hyperliquid API returns at most 5000 candles per request. For 1h data, this caps history at ~208 days. Templates that require long lookbacks should use 4h or 1d. The download script logs a WARNING when the window is capped.

**Slippage data:** OHLCV alone is not enough to model slippage realistically. Bars tell you what prices traded, but not the depth of the book at the time.

**API investigation result (confirmed):** The official Hyperliquid API provides no historical L2 orderbook snapshots — `l2Book` returns only the current book state. An unofficial S3 archive exists but updates only monthly and has missing data. Third-party providers (0xArchive, Tardis, SonarX) have historical depth from April 2023+ but require paid subscriptions.

**Decision:** Start polling live L2 orderbook data immediately via WebSocket (`wss://api.hyperliquid.xyz/ws`, `l2Book` subscription). Store top 10 levels per side per snapshot as parquet. This builds the calibration dataset in the background while the rest of the system is being built. After a few weeks of data, compute per-pair per-timeframe spread statistics and use those as the slippage model in the harness.

The orderbook poller runs as a separate long-running process under launchd (persistent, KeepAlive=true). The OHLCV refresh runs daily at 2am under launchd (scheduled). Logs go to `logs/orderbook.log` and `logs/ohlcv-refresh.log` respectively.

**Critical implementation note — WebSocket:** Hyperliquid's WebSocket does not respond to client ping frames. `ping_interval=None` is required in `websockets.connect()`; omitting it causes disconnect with code 1011 after 20 seconds.

**MacBook sleep:** The orderbook poller reconnects automatically on wake (5s delay). Data will have gaps during sleep periods. This is acceptable for a calibration dataset; use System Preferences → Energy Saver to prevent sleep if continuous collection is required.

**Storage:**
- Parquet for OHLCV (`data/ohlcv/<coin>/<interval>.parquet`) and depth data (`data/orderbook/<coin>/YYYY-MM-DD.parquet`)
- SQLite for the ledger and metadata (append-only, single-file, no infrastructure) — built in unit 5

**Unblocks:** Everything. No testing, no backtesting, no loop without data.

---

### 2. Strategy Templates (In progress — 2 of 6 complete)

Python implementations of the Elder-derived strategy templates, parameterized by the output contract schemas defined in `docs/strategy-output-contract.md`.

**Deliverables:**
- Template interface: each template is a pure function that takes OHLCV data + config dict, returns a list of signals ✓ (defined in `src/prospector/templates/base.py`)
- `triple_screen` ✓ (`src/prospector/templates/triple_screen.py`)
- `false_breakout` ✓ (`src/prospector/templates/false_breakout.py`, tests in `tests/templates/test_false_breakout.py`)
- `impulse_system` — not started
- `channel_fade` — not started
- `kangaroo_tail` — not started
- `ema_divergence` — not started
- Unit tests per template against hand-calculated expected signals ✓ (for completed templates)
- Parameter validation: Signal geometry validated at construction time via `Signal.__post_init__`; range validation deferred to the harness/orchestrator

**Design constraint:** Templates produce signals only. No position sizing, no NAV tracking, no transaction costs. That separation is the harness's job.

**Key implementation detail:** `Signal` is a frozen dataclass in `base.py` that validates geometry in `__post_init__`. Templates wrap `Signal(...)` construction in try/except and skip invalid signals. The `MIN_REWARD_RISK = 2.0` constant is imported from `base.py` and checked by templates before appending signals.

**Unblocks:** Backtest harness (needs signals to simulate).

---

### 3. Backtest Harness ✓ (Complete)

The most critical component. Accepts pre-generated `Signal` objects and an OHLCV DataFrame; simulates execution and returns a scored `BacktestResult`.

**Deliverables:**
- `BacktestConfig` — frozen dataclass with all execution parameters; all fields overridable in tests ✓
- `run_backtest(signals, df, config)` — main simulation function ✓
- `compute_score(pct_return, max_drawdown, n_trades)` — public scoring formula (independently testable) ✓
- `run_walk_forward(signals, df, n_folds, config)` — temporal consistency validation ✓
- 28 unit tests covering: exact P&L math, conservative stop-before-target rule, fill confirmation, hard gates, catastrophic floor, NAV ceiling, monthly circuit breaker, walk-forward fold isolation ✓

**Key implementation decisions:**
- Harness accepts pre-generated signals (not a template+config pair). Templates and harness are fully decoupled.
- Fill confirmation on entry bar: LONG fills only if `bar.high >= entry`; SHORT only if `bar.low <= entry`. Handles buy-stop (triple_screen) and close-entry (false_breakout) uniformly.
- Conservative exit: stop is always checked before target on the same bar. No cherry-picking.
- No overlapping positions: signals with `bar_index <= last_exit_bar` are skipped.
- NAV ceiling caps the effective nav used for sizing, not the actual nav. `pct_return` is computed on the capped final nav.
- Funding rate drag: not yet implemented. Listed in spec; deferred until historical funding data availability is confirmed.

**Files:** `src/prospector/harness/engine.py`, `walk_forward.py`, `__init__.py`
**Tests:** `tests/harness/test_engine.py`

**Unblocks:** Orchestrator (needs scoring), dashboard (needs metrics to display).

---

### 4. Orchestrator and Inner Loop ✓ (Skeleton complete)

The main loop that coordinates LLM proposal, validation, backtesting, and logging.

**Deliverables:**
- Prompt assembly: inject template registry, securities universe, and sliding window ✓ (`src/prospector/orchestrator.py:assemble_prompt`)
- Ollama integration: httpx POST to `/api/generate`, parse JSON response ✓ (`call_model`, `parse_response`)
- Config validation: template, param schema, cross-param constraints, securities universe, exact-match diversity ✓ (`validate_config`)
- Dispatch: per-security backtest with multi-security aggregation ✓ (`_dispatch`, `_aggregate`)
- Result logging: write RunRecord to ledger after every iteration ✓
- Sliding window query: via `Ledger.format_sliding_window()` ✓
- Error handling: malformed JSON, Ollama timeouts, and validation failures are caught, logged, and loop continues ✓
- Stagnation detection: if last N valid proposals all use same template → nudge injected ✓
- Cold start handling: `Ledger.format_sliding_window()` returns baseline message when empty ✓

**Key decisions:**
- Only `triple_screen` and `false_breakout` are shown in the prompt registry (unimplemented templates are excluded). Expand `_REGISTRY` in `orchestrator.py` as new templates are implemented.
- Diversity check is exact match only (first version). Normalized distance from the spec is deferred.
- Entry point: `python -m prospector.orchestrator`
- Mock model mode: set `PROSPECTOR_MOCK=1` to bypass Ollama and emit random schema-valid proposals. Useful for shaking out loop mechanics without a running model server.

**Files:** `src/prospector/orchestrator.py`
**Tests:** `tests/test_orchestrator.py`

**Unblocks:** The autonomous discovery loop. Once this works end-to-end, the system can run unsupervised.

---

### 5. Ledger and Persistence ✓ (Complete)

SQLite append-only log of every iteration.

**Deliverables:**
- Schema: run_id, timestamp, template, config_json, validation_status, backtest_status, score, all diagnostic metrics, rationale, thinking, per-security breakdown (JSON blob) ✓
- Query interface: `get_sliding_window(n)`, `last_n_templates(n)`, `count()`, `format_sliding_window(n)` ✓
- Append-only constraint: no updates or deletes on run records ✓ (INSERT only)
- Export: not yet implemented (deferred — query directly via SQLite CLI or pandas for now)

**Files:** `src/prospector/ledger.py`
**Tests:** `tests/test_ledger.py`
**DB path:** `data/prospector.db` (gitignored via `data/*.db`)

**Unblocks:** Sliding window for orchestrator ✓, dashboard data source.

---

### 6. Dashboard

Interactive UI for monitoring the discovery loop and reviewing results.

**Deliverables:**
- Framework: Streamlit (pragmatic for a Python project, minimal frontend work, iterates fast)
- Views:
  - Run history: sortable/filterable table of all iterations with scores and metrics
  - Score over time: line chart showing score progression, with template color-coding
  - Per-template breakdown: which templates perform best, parameter heatmaps
  - NAV equity curves: per-run simulated account trajectory
  - Paper portfolio tracker: forward performance of promoted configs
  - Live portfolio tracker (future): real positions, P&L, drawdown

**Build incrementally.** Start with run history and score-over-time once the harness is producing results. Add views as the system matures.

**Unblocks:** Human outer-loop review (need visibility into what the inner loop is doing).

---

### 7. Paper Trading

Forward-test winning configs against live Hyperliquid data without placing real orders.

**Deliverables:**
- Config promotion: manually (or by score threshold) select configs to paper trade
- Live data feed: stream or poll Hyperliquid candles at the template's timeframe
- Signal generation: run the template on live data, produce signals in real time
- Simulated execution: apply the same position sizing and cost model as the backtest harness
- Tracking: log paper trades, NAV, and metrics to a separate ledger table
- Dashboard integration: paper portfolio view in the Streamlit dashboard

**Runs on:** MacBook, alongside the discovery loop. No deployment infrastructure needed.

**Unblocks:** Confidence that backtest results hold on unseen data before risking capital.

---

### 8. Live Execution and Deployment

Place real orders on Hyperliquid with promoted, paper-validated configs.

**Deliverables:**
- Hyperliquid order client: place limit/market orders, cancel, query positions
- Position manager: track open positions, enforce max concurrent positions, apply monthly drawdown cap
- Risk controls: duplicate of harness-level rules, but enforced in real time (2% risk per trade, 6% monthly cap, reward:risk gate)
- Alerting: notifications on trade execution, drawdown warnings, circuit breaker activation
- Deployment target: small VPS or cloud instance with persistent uptime. The execution layer is lightweight — it places orders and tracks positions, it doesn't run backtests or LLM inference.
- Separation: the discovery loop (MacBook) and the execution layer (server) communicate through the ledger or a simple API. Promoted configs are pushed to the execution layer.

**Deployment note:** The MacBook handles backtesting and LLM inference (compute-heavy, tolerant of interruptions). The execution layer handles live trading (lightweight, needs persistent uptime and API connectivity). These are separate processes, possibly separate machines.

**Unblocks:** Real returns.

---

## Dependency Graph

```
1. Data Layer
   ├── 2. Strategy Templates
   │   └── 3. Backtest Harness ──┐
   │       └── 5. Ledger ────────┤
   │                             ├── 4. Orchestrator (inner loop)
   │                             ├── 6. Dashboard
   │                             └── 7. Paper Trading
   │                                    └── 8. Live Execution
```

## Starting Point

Units 1–3 form a vertical slice: download data, implement one template, run a backtest with hand-picked parameters, get a scored NAV simulation. This proves the core pipeline without any LLM involvement and surfaces data quality issues, template bugs, and harness correctness problems early — before they're buried under the complexity of the loop.

Start with unit 1: project scaffolding and Hyperliquid OHLCV data pipeline.
