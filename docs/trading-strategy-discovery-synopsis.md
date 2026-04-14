# Trading Strategy Discovery System — Project Synopsis

## Executive Summary

Build a locally-hosted system that autonomously discovers, evaluates, and refines price-action-based trading strategies for crypto perpetual futures on Hyperliquid. A quantized 13B language model runs continuously in the background, selecting from a library of human-authored strategy templates and proposing parameter configurations to backtest. A rigorous backtest harness evaluates each proposal against historical price data and returns structured metrics. A sliding window of recent results feeds back into the model's context, and a periodic LoRA adapter encodes long-term lessons to prevent the system from cycling through previously-failed approaches.

**The core bet:** A machine can scan more securities across more timeframes with more discipline than a human. Even a 0.5% edge, compounded with rigid risk management, produces meaningful returns. Human emotion erodes edge; rigid rules preserve it.

**The organizing principle:** Each component plays to its strengths and stays within its core competency. The small model does one narrow thing well (reason over accumulated results and propose the next configuration to try). Human-authored strategy templates contain all execution logic. The harness enforces all risk constraints. Claude/Opus handles system design, architecture, and code infrastructure — interactively and infrequently. Nothing is asked to do what it cannot reliably do.

**Why templates, not code generation.** The kalshi-autoagent project proved that a small model searching over JSON configs (the two-loop pattern) works, while open-ended Python code generation by the same class of model failed. Templates redirect model intelligence from "write correct Python" to "reason about which region of strategy space is unexplored and promising" — a better use of 13B parameters. Template execution code is human-authored and audited once; the only variable is the config. A bad config produces a bad Sharpe ratio (a clean signal). Bad generated code that passes validation produces phantom edge (a silent poison).

---

## Hardware

| Resource | Specification |
|---|---|
| Machine | MacBook Pro, M3 base chip |
| Unified Memory | **16 GB** (shared CPU/GPU) |
| Model Budget | ~7–8 GB for a 4-bit quantized 13B model; fits comfortably |
| Runtime Profile | Background execution; gaps during MacBook sleep (reconnect handles wake-up) |
| Cloud Budget | Minimize; LoRA training passes may be offloaded to a spot GPU when iteration speed matters |

13B Q4_K_M quantization is the target model size. 7B was insufficient for reasoning over structured results in kalshi-autoagent; 13B is targeted here because the inner loop's value comes from reasoning over accumulated backtest outcomes — reading a sliding window of results, identifying which template/parameter regions are exhausted vs. unexplored, and proposing informed next configurations. This is a harder cognitive task than random parameter selection, and where 13B meaningfully outperforms 7B. Beyond ~20B brings marginal gains at disproportionate memory cost for this use case.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   HUMAN + OPUS/SONNET                   │
│  Design, build, debug the harness and infrastructure.   │
│  One-time and infrequent. Interactive, supervised.      │
└────────────────────────┬────────────────────────────────┘
                         │ builds
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ORCHESTRATION LAYER                     │
│  Python main loop. Assembles prompts, runs validation,  │
│  coordinates propose → backtest → evaluate → feedback.  │
│  Tracks strategy history, manages diversity,            │
│  triggers LoRA fine-tuning.                             │
└──────┬──────────────┬───────────────┬───────────────────┘
       │              │               │
       ▼              ▼               ▼
┌────────────┐ ┌─────────────┐ ┌──────────────────┐
│ LOCAL LLM  │ │  BACKTEST   │ │  PERSISTENCE     │
│ (13B q4)   │ │  HARNESS    │ │  (LoRA Adapter)  │
│            │ │             │ │                  │
│ Selects    │ │ Runs strat  │ │ Encodes lessons  │
│ template + │ │ against     │ │ from successful  │
│ proposes   │ │ historical  │ │ vs failed strats │
│ params as  │ │ price data  │ │ to prevent       │
│ JSON config│ │             │ │ cycling          │
└────────────┘ └─────────────┘ └──────────────────┘
```

**Human + Opus/Sonnet** — Design and implement the harness, strategy templates, data pipelines, orchestration loop, and prompt templates. Interactive, supervised, infrequent. Also serves as the outer loop: periodically reviews accumulated results, identifies structural gaps, and adds new strategy templates or widens parameter ranges when the inner loop saturates.

**Local LLM (13B quantized)** — Receives a prompt with the template library, parameter ranges, and a sliding window of recent backtest results. Outputs a JSON configuration: which template to use, what parameters to set, and which securities/timeframes to target. Scope is deliberately narrow: the model reasons about *what to try next* given what has already been tried. It does not implement strategy logic, position sizing, stops, data handling, or any execution code.

**Backtest Harness** — The most critical component. If evaluation is wrong, the entire loop optimizes for the wrong thing (see kalshi PIT pricing lesson below). Accepts a (template, config) pair, executes the human-authored template code with the proposed parameters against historical price data, produces structured metrics. Enforces all execution constraints so the model doesn't need to.

**Persistence (LoRA Adapter)** — Not the primary memory mechanism. The sliding window is the primary feedback signal. LoRA's role is periodic: encode longer-term lessons that the context window cannot hold, to prevent cycling across hundreds of iterations.

---

## Core Loop

1. Orchestrator assembles prompt (template library, parameter ranges, sliding window of recent results, LoRA adapter loaded)
2. LLM proposes a configuration: `{template, params, securities, timeframes}` with rationale
3. Orchestrator validates: valid JSON? recognized template? params within ranges? materially different from recent proposals?
4. Backtest harness executes the template with proposed params against held-out historical data
5. Orchestrator evaluates results against objective function; logs to append-only ledger
6. If stagnation detected (N consecutive failures): perturb constraints or trigger LoRA pass
7. Every M iterations: LoRA fine-tuning on accumulated data, reload adapter
8. Loop back to step 1

---

## What the LLM Proposes vs. What the Harness Enforces

The LLM proposes *what to look for*. The harness enforces *how to act*.

**Model explores:** Which template to use. Parameter values within defined ranges. Timeframe selection. Which securities from the universe. Rationale for why this configuration is worth trying given recent results.

**Harness enforces (never proposed by the model):** All strategy execution logic (human-authored templates). Position sizing and max allocation. Stop-loss and trailing stop mechanics. Max drawdown. Profit-taking rules. Liquidity and spread constraints. Transaction cost and slippage modeling.

This separation constrains the model to a task it can reliably perform (informed config selection), while making execution correct by construction. The strategy code is audited once; the only variable per iteration is the config.

---

## Overfitting

The single biggest risk. Defenses:

1. **Walk-forward validation** — rolling train/test windows; never test on development data
2. **Out-of-sample holdout** — recent data the model never sees; final validation only
3. **Complexity penalty** — fewer parameters preferred; explicitly part of the objective function
4. **Cross-security validation** — must work across multiple tickers; single-ticker success signals overfitting
5. **Regime awareness** — detect when a strategy stops working and retire it
6. **Sliding window as natural regularizer** — limited context reduces path dependence (but must be balanced against cycling risk)

**Important caveat:** The sibling projects (options-autoagent, kalshi-autoagent) exploit mathematical pricing constraints with guaranteed payoffs. Price-action strategies have no such guarantee. The edge, if found, is statistical and regime-dependent. This is a harder problem with a lower base rate of success.

---

## Lessons from Sibling Projects

This system extends a pattern proven in `kalshi-autoagent` and `options-autoagent` (see `~/workspace/other-trading-projects/`).

**The evaluator is sacred.** Kalshi's PIT pricing bug inflated scores from 45 to 140 — phantom profits from stale terminal prices. Weeks of optimization were invalidated. If the backtest harness is wrong, everything downstream is wrong. Get it right first, validate it against known outcomes, and never modify it mid-run.

**The scoring function defines what the system optimizes for.** In kalshi, composite scoring (PPT + win rate) and EV scoring (total profit at a given NAV) produced completely different optimal configs from the same strategy code. This isn't a parenthetical — it's a first-order design decision.

**Execution realism matters.** Kalshi strategies profitable at theoretical prices lost money at executable prices — spreads ate the edge. The `min_edge_threshold` had to be 3.5x higher to survive real execution. Slippage and spread modeling in the backtest harness is not optional.

**Append-only ledger; minimum iteration count before conclusions.** Never truncate results. Don't react to 3 iterations — let the model explore (20+ minimum before judging).

**The two-loop pattern.** Inner loop (small model) discovers what parameter regime works. Outer loop (Claude/human) discovers what new axes to add to the search. Neither does the other's job. This project follows the same proven pattern: the inner loop selects templates and proposes parameter configurations as JSON; the outer loop authors new templates, widens parameter ranges, or restructures the search space when the inner loop saturates.

---

## Technology Stack

| Component | Primary Choice | Notes |
|---|---|---|
| Local inference | Ollama | Simplest path; REST API; `ollama serve` |
| Model | Qwen2.5-Coder 14B or CodeLlama 13B (Q4_K_M) | Evaluate empirically on structured JSON output and reasoning quality |
| Backtest | Backtrader (not yet evaluated) | Tentative choice; harness not yet built — confirm at unit 3 implementation |
| Data | Hyperliquid API → local parquet/SQLite | Perpetual futures OHLCV; top liquid pairs to start |
| Orchestration | Python main loop + SQLite ledger | No Airflow/Celery at this stage |
| LoRA | HuggingFace transformers + peft | Slow on M3; may offload to cloud spot GPU |

---

## Implementation Order

The authoritative build order is in `docs/implementation-plan.md`. Summary:

1. **Data pipeline** ✓ — Hyperliquid OHLCV download + live orderbook poller. Both run under launchd. **Note:** 1h resolution is capped at ~208 days (5000 candle API limit); 4h gives ~833 days. Train/test/holdout partition not yet implemented.
2. **Strategy templates** (in progress) — `triple_screen` and `false_breakout` complete. Four remaining: `impulse_system`, `channel_fade`, `kangaroo_tail`, `ema_divergence`.
3. **Backtest harness** — most critical; validate against known outcomes before connecting to the loop.
4. **Ledger** — SQLite append-only log; build alongside harness.
5. **Orchestrator / inner loop** — prompt assembly, Ollama integration, validation, dispatch, stagnation detection.
6. **Dashboard** — Streamlit; add incrementally once harness produces results.
7. **Stagnation detection + LoRA** — only after cycling is confirmed as a real problem (~200+ iterations).
8. **Paper portfolio → live execution** — paper trade first; live only after paper validates.

**Deviation from original synopsis order:** The original listed templates before data pipeline. In practice, data pipeline (unit 1) was built first because it unblocks everything else. The implementation plan is now the authoritative sequence.

---

## Open Items for Implementation

These are unresolved design decisions that must be tackled before or during implementation. They are listed here as context, not as a spec — each will be worked through as the project progresses.

- **~~What "price-action patterns" means concretely.~~** Resolved. See `docs/trading-strategies.md` — six Elder-derived strategy templates covering trend-following, momentum, mean-reversion, false breakouts, bar patterns, and divergences.
- **~~Strategy output contract.~~** Resolved. See `docs/strategy-output-contract.md` — JSON envelope with per-template parameter schemas, validation rules, and diversity measurement.
- **~~Scoring function.~~** Resolved. See `docs/scoring-function.md` — sequential NAV simulation with quadratic drawdown penalty, sample-size penalty, and hard gates. Based on the final scoring approach from the sibling projects.
- **~~Prompt template.~~** Resolved. See `docs/prompt-template.md` — directive prompt with compact template registry, sliding window injection, structured thinking field, few-shot examples, and orchestrator edge-case handling.
- **Outer loop cadence.** When and how does the human/Claude review accumulated results and add new templates or widen parameter ranges?
- **Iteration throughput.** How long does one propose-backtest cycle take on M3? Every downstream threshold (stagnation detection, LoRA cadence, when to declare defeat) depends on this number.
- **Diversity measurement.** How to determine whether two proposed configs are materially different. With named templates, the natural measure is: different template = categorically different; same template = parameter-vector distance above a threshold.
