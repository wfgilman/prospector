# Prospector — Agent Quick-Start

This file is the first thing a new agent session should read. It answers "where are we?" without requiring a full doc review.

---

## Workflow mode — R&D (active 2026-04-25)

**Commit and push directly to `main`. No feature branches, no pull requests.**

The project is in R&D — the user is solo, paper-trading, has small kids and limited engagement bandwidth. PR review process is overhead that doesn't earn its weight at this stage. We deploy and fix if necessary; correctness is enforced by tests + ruff + the methodology discipline in `docs/implementation/methodology.md`, not by PR review.

This **overrides** the global `~/AGENTS.md` "feature branch + PR" mandate while in R&D mode.

**Revisit when:** the project transitions to Phase 4 (live, real capital) or the user explicitly asks. At that point, the feature-branch + PR workflow comes back automatically.

What stays the same regardless:
- Run ruff + the full test suite before pushing
- Conventional-commit subject lines (`feat:`, `fix:`, `chore:`, etc.)
- Never skip hooks, never force-push to main, never amend published commits
- Stage files explicitly (no `git add -A`)
- The other Git Safety Rules in `~/AGENTS.md` still apply

---

## What This Project Is

**Prospector** is a locally-hosted trading strategy discovery and deployment system. Originally designed for LLM-driven parameter search on crypto perpetual futures (paused — see R&D docs), the project pivoted to **Prediction Market Underwriting**: applying actuarial calibration curves to Kalshi prediction markets.

The full strategy prospectus is in `docs/rd/deep-dive-prediction-market-underwriting.md`. The build plan is in `docs/implementation/plan.md`.

---

## Current Status (as of 2026-04-21)

**Active track: PM Underwriting — Phase 3 live paper trading with sizing reevaluation**

| Phase | Description | Status | Result |
|---|---|---|---|
| 1 | Calibration curve | **Complete** | GO — 6 qualifying bins aggregate, 16 in sports. |
| 2 | Walk-forward backtest | **Complete** | GO — Sharpe 7.44, 66.9% WR, calibration holds OOS. |
| 2b | Capital-constrained simulation | **Complete** | GO — Sharpe 9.19 at 20 trades/day, 303% return/41d. |
| 3 | Paper trading | **In progress** | Live since 2026-04-20 via launchd. Diversity + fees wired. |
| 3.5 | Sizing-framework reevaluation | **In progress** | Kelly-per-bet under review; moving toward CI-based book-level sizing. See `docs/rd/sizing-reevaluation.md`. |
| 4 | Live (small) | Pending | Gated on Phase 3 results + sizing decision. |

**Two confirmed edges:**
1. Sports parlay overpricing (large, ~6 months history, prospect theory)
2. Crypto longshot overpricing (moderate, more persistent, favorite-longshot bias)

**Payoff profile note:** ranking candidates by edge systematically selects extreme-price bins (80-95¢), which are 9:1 *lottery-ticket* payoffs, not the win-often/lose-small insurance profile implied by the "underwriting" label. See `docs/implementation/methodology.md` §4.7. This reshapes the sizing problem (see sizing reevaluation doc).

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
│   ├── return_distribution.py         <- Phase 3.5: per-trade μ/σ by stratum; sample-size requirements
│   ├── paper_trade.py                 <- Phase 3: live paper-trading daemon (launchd)
│   ├── refresh_calibration_store.py   <- Phase 3: rebuild persisted calibration snapshot
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
    │   ├── elder-track-walk-forward.md  <- Elder walk-forward validation results
    │   └── sizing-reevaluation.md       <- Phase 3.5: Kelly-per-bet → CI-based book-level sizing
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
