# Trading Strategy Discovery System — Project Synopsis

## Executive Summary

Build a locally-hosted, resource-constrained system that autonomously discovers, evaluates, and refines price-action-based trading strategies. The system uses a small quantized language model running 24/7 on a MacBook Pro M3 to propose candidate strategies, a rigorous backtest harness to evaluate them, and a lightweight persistence layer (LoRA adapter) to encode long-term lessons and prevent the system from cycling through previously-failed approaches.

The thesis: a machine can scan more securities across more timeframes with more discipline than a human, and even a small statistical edge (0.5%+) compounded with rigid risk management produces meaningful returns.

---

## Hardware & Resource Constraints

| Resource | Specification |
|---|---|
| Machine | MacBook Pro, M3 base chip |
| Unified Memory | 8 GB (shared between CPU/GPU) |
| Model Budget | ~6–7 GB for a 4-bit quantized 13B model |
| Runtime Profile | Potentially 24/7 background execution |
| Cloud Budget | Minimize or eliminate; usage patterns unknown |

**Implication:** All inference must run locally. Fine-tuning (LoRA) may need to be batched infrequently or offloaded to a cloud GPU for periodic training runs. The system must be designed to be frugal with memory and tolerate slower inference speeds.

---

## Architecture Overview

The system is organized around the principle that **each component plays to its strengths**:

```
┌─────────────────────────────────────────────────────────┐
│                   HUMAN + OPUS/SONNET                   │
│  Design, build, debug the harness and infrastructure.   │
│  One-time and infrequent work. Interactive, supervised.  │
└────────────────────────┬────────────────────────────────┘
                         │ builds
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ORCHESTRATION LAYER                     │
│  Python main loop. Coordinates the propose → backtest   │
│  → evaluate → feedback cycle. Tracks strategy history,  │
│  manages diversity, triggers LoRA fine-tuning.          │
└──────┬──────────────┬───────────────┬───────────────────┘
       │              │               │
       ▼              ▼               ▼
┌────────────┐ ┌─────────────┐ ┌──────────────────┐
│ LOCAL LLM  │ │  BACKTEST   │ │  PERSISTENCE     │
│ (13B q4)   │ │  HARNESS    │ │  (LoRA Adapter)  │
│            │ │             │ │                  │
│ Proposes   │ │ Runs strat  │ │ Encodes lessons  │
│ candidate  │ │ against     │ │ from successful  │
│ strategies │ │ historical  │ │ vs failed strats │
│ in code    │ │ price data  │ │ to prevent       │
│            │ │             │ │ cycling          │
└────────────┘ └─────────────┘ └──────────────────┘
```

### Component Responsibilities

**Human + Opus/Sonnet (build phase)**
- Design and implement the backtest harness
- Build data ingestion pipelines
- Write the orchestration loop
- Debug and refactor as needed
- This work is interactive, supervised, and infrequent

**Local LLM (13B quantized, runtime phase)**
- Receive a prompt containing: constraints, recent backtest results, sliding window of context
- Output: a candidate trading strategy expressed as executable Python code
- This is the workhorse that runs continuously

**Backtest Harness (runtime phase)**
- Accept a strategy definition in code
- Execute it against historical price data
- Produce structured metrics: P&L, Sharpe ratio, max drawdown, win rate, profit factor
- This is deterministic and must be trustworthy

**Persistence Layer — LoRA Adapter (periodic)**
- Periodically fine-tune a small adapter on accumulated successful vs. failed strategies
- Prevents the model from retreading old ground
- Provides a "steady march above baseline" without full model retraining

---

## Core Loop

```
1. Orchestrator assembles prompt:
   - System constraints (position sizing, risk limits, universe of securities)
   - Recent backtest results (sliding window, not full history)
   - Current LoRA adapter loaded

2. Local LLM generates candidate strategy as Python code

3. Orchestrator validates the strategy:
   - Syntactically correct?
   - Respects constraints (position limits, stop-loss rules, etc.)?
   - Materially different from recent N strategies? (diversity check)

4. Backtest harness executes strategy against held-out historical data

5. Orchestrator evaluates results against objective function

6. Results logged to strategy history database

7. Every N iterations: trigger LoRA fine-tuning pass on accumulated data

8. Loop back to step 1
```

---

## Strategy Constraints & Objective Function

### What the model is free to explore
- Entry and exit conditions based on price action and geometric patterns
- Timeframe selection (daily, weekly, monthly)
- Which securities to trade from a defined universe
- Combination and weighting of technical signals

### What is fixed by the harness (not negotiable)
- Position sizing rules and maximum allocation per position
- Stop-loss thresholds and trailing stop mechanics
- Maximum acceptable drawdown
- Profit-taking rules
- Liquidity constraints
- Transaction cost assumptions

### Objective function
- Primary: maximize risk-adjusted return (e.g., Sharpe ratio or profit factor)
- Penalize complexity (fewer parameters preferred)
- Must demonstrate performance across multiple out-of-sample periods (anti-overfitting)

---

## Overfitting Mitigation

This is the single biggest risk. Strategies that look great on historical data and fail in production are worse than useless. Defenses:

1. **Walk-forward validation:** Never test on the same data used to develop the strategy. Use rolling windows where the model trains on period A, tests on period B, then advances.

2. **Out-of-sample holdout:** Reserve a chunk of recent data that the model never sees during development. Final validation only.

3. **Complexity penalty:** Prefer strategies with fewer parameters. A strategy with 3 rules that works is better than one with 15 rules that works slightly better.

4. **Cross-security validation:** A strategy should work across multiple securities, not just one. If it only works on AAPL, it's probably overfit.

5. **Regime awareness:** Markets change. A strategy that worked 2015–2020 may not work 2020–2025. The system should detect when a strategy stops working and retire it gracefully rather than clinging to it.

6. **Fresh starts are a feature:** Coming into each iteration without heavy path dependence (via the sliding window approach) naturally reduces overfitting. The LoRA adapter should encode general lessons ("momentum strategies work better in trending markets") not specific parameters.

---

## Technology Stack

### Local Model Inference
- **Ollama** — simplest path; download a quantized model, run `ollama serve`, query via REST API
- **Alternative:** llama.cpp for more fine-grained control
- **Model candidates:** CodeLlama 13B (Q4_K_M quantization), Mistral 7B, or similar
- Quantization format: GGUF (4-bit) to fit within ~7 GB memory budget

### Backtest Framework
- **Backtrader** — mature, well-documented, flexible
- **Alternative:** Zipline (more institutional but heavier), or hand-rolled with pandas
- Recommendation: start with backtrader; migrate only if it becomes a bottleneck

### Data
- Historical OHLCV price data (daily, weekly, monthly)
- Sources: Yahoo Finance (free, good enough to start), Alpha Vantage, or Polygon.io
- Storage: local SQLite or parquet files on disk

### Orchestration
- Simple Python script with a main loop
- SQLite database for strategy history and backtest results
- Logging for auditability
- **Not recommended at this stage:** Airflow, Celery, or other heavy orchestration frameworks

### LoRA Fine-Tuning
- **Hugging Face transformers + peft** library
- Parameter-efficient: trains a small adapter, not the full model
- **Hardware concern:** LoRA training on M3 is slow but feasible for small adapters. If iteration speed becomes a problem, batch training runs and offload to a cloud GPU (e.g., a spot instance on Lambda Labs or vast.ai for a few dollars)

---

## Open Questions & Risks

### Does an LLM add value over traditional approaches?
For the pattern-matching and strategy search problem as described, a traditional approach (genetic algorithms, Bayesian optimization, or even a CNN trained on chart images) might be more computationally efficient than an LLM. The LLM's advantage is that it can express strategies in readable Python code and reason about *why* something might work, but if the search space is tightly constrained, a simpler optimizer might converge faster.

**Recommendation:** Start with the LLM approach because it's more flexible and the code output is directly usable. But keep traditional optimization in your back pocket as a fallback if the LLM approach proves too slow or circular.

### Memory and cycling
The sliding window + LoRA approach is the best available solution for preventing the model from retreading old ground, but it's not proven. The system needs a clear "stagnation detector" — if N consecutive strategies fail to beat the baseline, something needs to change (perturb the constraints, expand the security universe, change the timeframe).

### Strategy diversity tracking
How do you measure whether two strategies are "materially different"? This is non-trivial. Options:
- Hash the strategy's decision logic and compare
- Track the parameter space being explored and flag revisits
- Cluster strategies by their backtest behavior (similar return profiles = similar strategies)

### LoRA training cadence
How often do you fine-tune? Too frequently and you overfit the adapter. Too infrequently and the model cycles. This will need empirical tuning. Start with every 50–100 iterations and adjust.

### When to declare defeat
The system needs a kill switch. If after N hours/iterations it hasn't found a strategy that beats buy-and-hold on out-of-sample data, it should stop and report rather than burn compute indefinitely.

### Paper portfolio to live trading
This synopsis covers discovery and paper trading. The path from paper portfolio to live execution introduces a whole new set of concerns (broker API integration, real-time data feeds, order management, slippage, partial fills) that are explicitly out of scope for now.

---

## Suggested Implementation Order

1. **Backtest harness** — Get this rock solid first. If your evaluation framework is wrong, nothing downstream matters. Use backtrader with a clean API that accepts a strategy definition and returns structured metrics.

2. **Data pipeline** — Download and store historical OHLCV data for a universe of securities. Start small (S&P 500 components, daily data, 10 years). Parquet files or SQLite.

3. **Local model setup** — Install Ollama, download a quantized 13B model, verify you can query it and get Python code back. Test that it fits in memory and inference speed is acceptable.

4. **Orchestration loop** — Wire the pieces together. Prompt the model, capture the output, validate it, run the backtest, log results. Start with a single iteration end-to-end before worrying about the loop.

5. **Feedback mechanism** — Build the sliding window context: show the model its last N results and let it iterate. Run the loop for a few dozen iterations manually and observe behavior.

6. **Diversity tracking & stagnation detection** — Implement basic checks to detect cycling and stagnation.

7. **LoRA fine-tuning** — Once you have enough accumulated data (maybe 200+ iterations), attempt a LoRA training run and reload the adapter. Measure whether it improves convergence.

8. **Paper portfolio** — Deploy winning strategies in a simulated portfolio and track performance over time.

---

## Summary

The core bet: a small, cheap model running locally can discover simple, repeatable trading strategies by brute-force iteration against a rigorous backtest framework, with disciplined risk management providing the edge that a human trader's emotions would erode. The architecture deliberately separates concerns — Opus builds, small model searches, backtest harness evaluates, LoRA remembers — so each component operates within its capabilities. Start simple, measure everything, and let usage patterns guide decisions about scaling.
