# Trading Strategy Discovery System — Project Synopsis

## Executive Summary

Build a locally-hosted system that autonomously discovers, evaluates, and refines price-action-based trading strategies. A quantized 13B language model runs continuously in the background to propose candidate strategies as simple, executable Python rule sets. A rigorous backtest harness evaluates each proposal against historical price data and returns structured metrics. A sliding window of recent results feeds back into the model's context, and a periodic LoRA adapter encodes long-term lessons to prevent the system from cycling through previously-failed approaches.

**The core bet:** A machine can scan more securities across more timeframes with more discipline than a human. Even a 0.5% edge, compounded with rigid risk management, produces meaningful returns. Human emotion erodes edge; rigid rules preserve it.

**The organizing principle:** Each component plays to its strengths and stays within its core competency. The small model does one narrow thing well (propose simple strategy rule sets). The harness enforces all execution constraints. Claude/Opus handles system design, architecture, and code infrastructure — interactively and infrequently. Nothing is asked to do what it cannot reliably do.

---

## Hardware

| Resource | Specification |
|---|---|
| Machine | MacBook Pro, M3 base chip |
| Unified Memory | **16 GB** (shared CPU/GPU) |
| Model Budget | ~7–8 GB for a 4-bit quantized 13B model; fits comfortably |
| Runtime Profile | 24/7 background execution |
| Cloud Budget | Minimize; LoRA training passes may be offloaded to a spot GPU when iteration speed matters |

13B Q4_K_M quantization is the target model size. 7B was insufficient for complex code generation tasks in the kalshi-autoagent project; 13B is targeted here for better reliability, even though the output scope is simpler (short rule sets, not multi-file rewrites). Beyond ~20B brings marginal gains at disproportionate memory cost for this use case.

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
│ Proposes   │ │ Runs strat  │ │ Encodes lessons  │
│ simple     │ │ against     │ │ from successful  │
│ strategy   │ │ historical  │ │ vs failed strats │
│ rule sets  │ │ price data  │ │ to prevent       │
│ as code    │ │             │ │ cycling          │
└────────────┘ └─────────────┘ └──────────────────┘
```

**Human + Opus/Sonnet** — Design and implement the harness, data pipelines, orchestration loop, and prompt templates. Interactive, supervised, infrequent. Also serves as the outer loop: periodically reviews accumulated results, identifies structural gaps, and evolves the strategy template or search space when the inner loop saturates.

**Local LLM (13B quantized)** — Receives a prompt with system constraints and recent backtest results (sliding window). Outputs a candidate strategy as a short Python rule set. Scope is deliberately narrow: the model proposes *what to look for* in price data — entry/exit signal conditions. It does not implement position sizing, stops, data handling, or any execution logic.

**Backtest Harness** — The most critical component. If evaluation is wrong, the entire loop optimizes for the wrong thing (see kalshi PIT pricing lesson below). Accepts a strategy definition, executes it against historical price data, produces structured metrics. Enforces all execution constraints so the model doesn't need to.

**Persistence (LoRA Adapter)** — Not the primary memory mechanism. The sliding window is the primary feedback signal. LoRA's role is periodic: encode longer-term lessons that the context window cannot hold, to prevent cycling across hundreds of iterations.

---

## Core Loop

1. Orchestrator assembles prompt (constraints, sliding window of recent results, LoRA adapter loaded)
2. LLM generates a candidate strategy as a short Python rule set
3. Orchestrator validates: syntactically correct? conforms to harness API? materially different from recent proposals?
4. Backtest harness executes strategy against held-out historical data
5. Orchestrator evaluates results against objective function; logs to append-only ledger
6. If stagnation detected (N consecutive failures): perturb constraints or trigger LoRA pass
7. Every M iterations: LoRA fine-tuning on accumulated data, reload adapter
8. Loop back to step 1

---

## What the LLM Proposes vs. What the Harness Enforces

The LLM proposes *what to look for*. The harness enforces *how to act*.

**Model explores:** Entry/exit signal conditions based on price action and patterns. Timeframe selection. Which securities from the universe. Combination of technical signals.

**Harness enforces (never proposed by the model):** Position sizing and max allocation. Stop-loss and trailing stop mechanics. Max drawdown. Profit-taking rules. Liquidity and spread constraints. Transaction cost and slippage modeling.

This separation constrains the search space to what a 13B model can reliably produce, while making execution correct by construction.

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

**The scoring function defines what the system optimizes for.** In kalshi, composite scoring (PPT + win rate) and EV scoring (total profit at a bankroll) produced completely different optimal configs from the same strategy code. This isn't a parenthetical — it's a first-order design decision.

**Execution realism matters.** Kalshi strategies profitable at theoretical prices lost money at executable prices — spreads ate the edge. The `min_edge_threshold` had to be 3.5x higher to survive real execution. Slippage and spread modeling in the backtest harness is not optional.

**Append-only ledger; minimum iteration count before conclusions.** Never truncate results. Don't react to 3 iterations — let the model explore (20+ minimum before judging).

**The two-loop pattern.** Inner loop (small model) discovers what parameter regime works. Outer loop (Claude/human) discovers what new axes to add to the search. Neither does the other's job. This project's inner loop produces code rather than JSON configs — a larger search space, tractable because the output scope is narrow and the harness constrains what's valid.

---

## Technology Stack

| Component | Primary Choice | Notes |
|---|---|---|
| Local inference | Ollama | Simplest path; REST API; `ollama serve` |
| Model | Qwen2.5-Coder 14B or CodeLlama 13B (Q4_K_M) | Evaluate empirically on short Python output quality |
| Backtest | Backtrader | Mature, flexible; migrate only if it becomes a constraint |
| Data | Yahoo Finance → local parquet/SQLite | Free; S&P 500 daily, 10 years to start |
| Orchestration | Python main loop + SQLite ledger | No Airflow/Celery at this stage |
| LoRA | HuggingFace transformers + peft | Slow on M3; may offload to cloud spot GPU |

---

## Implementation Order

1. **Backtest harness** — rock solid first. Validate against known strategies with known results.
2. **Data pipeline** — OHLCV data, train/test/holdout splits established before any model work.
3. **Local model setup** — Ollama + quantized 13B. Empirically validate it can produce usable Python.
4. **Single iteration end-to-end** — prompt → generate → validate → backtest → log. One pass, working.
5. **Sliding window feedback** — show recent results in prompt; observe whether iteration is meaningful.
6. **Stagnation detection** — cycling detector, perturbation logic, kill switch. Before LoRA, not after.
7. **LoRA fine-tuning** — only after cycling is confirmed as a real problem (~200+ iterations of data).
8. **Paper portfolio** — deploy winners in simulation; track over weeks/months.

---

## Open Items for Implementation

These are unresolved design decisions that must be tackled before or during implementation. They are listed here as context, not as a spec — each will be worked through as the project progresses.

- **Strategy output contract.** What is the function signature the model must conform to? What data does it receive, what does it return? This is the interface between the LLM and the harness and the most important piece of the inner loop design.
- **Prompt template.** What instructions does the model receive? How are previous results formatted in the sliding window? How is the harness API communicated so the model knows what it can call?
- **Scoring function.** Sharpe ratio, profit factor, total EV, or a composite? The choice shapes everything the system optimizes for. Must be decided deliberately, not by default.
- **Outer loop cadence.** When and how does the human/Claude review accumulated results and make structural changes to the strategy template or search space?
- **Iteration throughput.** How long does one propose-backtest cycle take on M3? Every downstream threshold (stagnation detection, LoRA cadence, when to declare defeat) depends on this number.
- **What "price-action patterns" means concretely.** Breakouts? Moving average signals? Candlestick formations? Chart geometry? The answer determines the data representation the model needs and the strategy output shape.
- **Diversity measurement.** How to determine whether two proposed strategies are materially different — by code structure, by backtest behavior, or both.
