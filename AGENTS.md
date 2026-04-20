# Prospector — Agent Quick-Start

This file is the first thing a new agent session should read. It answers "where are we?" without requiring a full doc review.

---

## What This Project Is

**Prospector** is a locally-hosted trading strategy discovery and deployment system. Originally designed for LLM-driven parameter search on crypto perpetual futures (paused — see R&D docs), the project pivoted to **Prediction Market Underwriting**: applying actuarial calibration curves to Kalshi prediction markets.

The full strategy prospectus is in `docs/rd/deep-dive-prediction-market-underwriting.md`. The build plan is in `docs/implementation/plan.md`.

---

## Current Status (as of 2026-04-19)

**Active track: PM Underwriting — Preparing for Phase 3 (Paper Trading)**

| Phase | Description | Status | Result |
|---|---|---|---|
| 1 | Calibration curve | **Complete** | GO — 6 qualifying bins aggregate, 16 in sports. |
| 2 | Walk-forward backtest | **Complete** | GO — Sharpe 7.44, 66.9% WR, calibration holds OOS. |
| 2b | Capital-constrained simulation | **Complete** | GO — Sharpe 9.19 at 20 trades/day, 303% return/41d. |
| 3 | Paper trading | **Next** | Validate execution quality on live Kalshi markets. |
| 4 | Live (small) | Pending | 5% of intended NAV after Phase 3. |

**Two confirmed edges:**
1. Sports parlay overpricing (large, ~6 months history, prospect theory)
2. Crypto longshot overpricing (moderate, more persistent, favorite-longshot bias)

**Elder-template track:** Paused as of 2026-04-14 — LLM inner loop falsified, walk-forward killed all top configs. See `docs/rd/elder-track-pivot.md`.

---

## Repository Layout

```
prospector/
├── AGENTS.md                  <- you are here
├── pyproject.toml
├── src/
│   └── prospector/
│       ├── data/              <- Hyperliquid API client, OHLCV download, orderbook poller
│       ├── templates/         <- Elder-track strategy templates (triple_screen, false_breakout)
│       ├── harness/           <- Backtest engine and walk-forward validation
│       ├── ledger.py          <- SQLite append-only log for orchestrator
│       └── orchestrator.py    <- LLM-driven inner loop (Elder track, paused)
├── scripts/
│   ├── build_calibration_curve.py     <- Phase 1: PIT calibration from Kalshi data
│   ├── walk_forward_backtest.py       <- Phase 2: train/test walk-forward simulation
│   ├── capital_constrained_sim.py     <- Phase 2b: realistic portfolio with capital constraints
│   └── walk_forward_top_configs.py    <- Elder track: validate top ledger configs
├── tests/
├── data/
│   ├── kalshi_hf/             <- HuggingFace dataset (5.3 GB parquet, gitignored)
│   ├── calibration/           <- Script outputs (plots, gitignored)
│   ├── ohlcv/                 <- Hyperliquid OHLCV parquet
│   └── orderbook/             <- Hyperliquid L2 snapshots
├── logs/
└── docs/
    ├── rd/                    <- Research & Development
    │   ├── deep-dive-prediction-market-underwriting.md  <- PM strategy prospectus
    │   ├── deep-dive-kalshi-crypto-narrative-spread.md  <- Future strategy candidate
    │   ├── literature-review.md
    │   ├── strategy-families.md         <- Strategy queue
    │   ├── sibling-project-insights.md
    │   ├── elder-track-pivot.md         <- Why Elder track was paused
    │   └── elder-track-walk-forward.md  <- Elder walk-forward validation results
    ├── implementation/
    │   ├── plan.md                      <- PM underwriting phases and progress
    │   └── archived/                    <- Elder track specs (paused)
    └── reference/
        ├── terminology.md               <- Glossary of trading concepts
        └── runbook.md                   <- How to run scripts and services
```

---

## Environment and Tooling

```bash
# Activate the project virtual environment
source /Users/wgilman/workspace/prospector/.venv/bin/activate

# Run tests
PYTHONPATH=src pytest -q tests

# Run linter
ruff check src tests scripts

# PM Underwriting scripts
python scripts/build_calibration_curve.py      # Phase 1: calibration curve
python scripts/walk_forward_backtest.py        # Phase 2: walk-forward backtest
python scripts/capital_constrained_sim.py      # Phase 2b: capital-constrained sim
```

See `docs/reference/runbook.md` for full operational details.

---

## Key Sibling Projects

| Project | Relationship |
|---|---|
| `kalshi-autoagent` | 5 structural arb strategies on Kalshi (mathematical violations). PM underwriting complements: statistical violations. |
| `kalshi-arb-trader` | Execution infrastructure for Kalshi. Likely reusable for Phase 3 API client. |
| `crypto-copy-bot` | Hyperliquid copy trading + funding arb. Separate from Kalshi work. |
| `options-autoagent` | Options constraint violation detection. |

---

## Docs Reference

| Directory | Purpose |
|---|---|
| `docs/rd/` | Research deep dives, literature review, strategy candidates, experiment post-mortems |
| `docs/implementation/` | Current build plan, phase status, validation methodology, archived Elder track specs |
| `docs/reference/` | Terminology glossary, operational runbook |
