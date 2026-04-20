# Pivot — 2026-04-14

This project is pausing the Elder-template parameter-search track and pivoting to strategy research. This document captures the learnings that drove the pivot, so future work doesn't repeat the same path.

## What we built and tested

Over ~2 weeks:
- Data layer: OHLCV download for BTC/ETH/SOL perp (1h, 4h, 1d, 1w); live L2 orderbook poller via launchd.
- Two strategy templates: `triple_screen`, `false_breakout` (Elder-derived).
- Backtest harness: NAV simulation, Iron Triangle sizing, hard gates (≥20 trades, profit factor >1.3), catastrophic floor, monthly circuit breaker, walk-forward fold isolation.
- Ledger: SQLite append-only log with sliding-window + coverage-cell prompt injection.
- Orchestrator: Ollama-backed inner loop with `qwen2.5-coder:14b`, stagnation detection, duplicate filtering, mock mode.

## What we learned

### 1. The LLM inner-loop thesis is falsified for continuous parameter search

Four distributions compared at equal harness, equal search space:

| Configuration | n | Scored rate | Max score |
|---|---|---|---|
| v1 LLM (temp 0.7, sliding window only) | 200 | 5.5% | 120 |
| v2 LLM (temp 1.0, + coverage prompt) | 200 | 11.5% | 156 |
| Random at N=300 | 300 | 18.3% | 200 |
| Oracle random (N=2000) | 2000 | 19.7% | 192.5 |

Random at N=100 beats LLM at N=200 on both hit rate and peak score, at ~30× lower wall-clock cost. The LLM adds no value when the problem is *"find the best point in a 6-dimensional noisy parameter landscape."* LLMs are good at categorical narrative reasoning over structured outcomes; they are not bayesian optimizers.

This is not a prompt-tuning problem. It's a problem-shape mismatch.

### 2. The in-sample winning configs are overfitting artifacts

Walk-forward validation of the top-10 oracle configs (see `docs/walk-forward-findings.md`):
- **100% of `false_breakout` configs die** — zero scored folds at 3 or 5 folds. Trade density (~40–50 trades over 5000 bars) falls below the 20-trade per-fold gate.
- **`triple_screen` configs degrade 42–82%** on best-security holdout mean. At most one config (run #303) comes close to temporal consistency (4/5 scored folds).

The ~192 in-sample ceiling is not a discovered edge; it's what you get when you sample 2000 random configs against 5000 bars and keep the one that landed on a favorable slice.

### 3. The real bottleneck is signal density, not search

Elder templates produce 40–120 trades across the full ~5000-bar 4h history. Walk-forward requires ≥20 trades per fold to score. At 3 folds that leaves no margin, at 5 folds none at all. Widening ranges or adding more Elder templates (`impulse_system`, `channel_fade`, `kangaroo_tail`, `ema_divergence`) does not fix this — they are shaped the same way.

The book author explicitly treats these templates as arbitrary. The value is in consistent application and risk management, not in which template you pick. That framing plus the walk-forward result says: there is no LLM-shaped problem inside this search space.

## Why we are pivoting, not iterating

The failure modes are structural, not tactical:
- Problem-shape mismatch (continuous optimization, not reasoning) cannot be fixed with prompt engineering.
- Trade-sparsity can't be fixed by adding templates of the same family.
- Walk-forward has already characterized the ceiling — more search won't find a higher one that holds up.

Continuing to iterate on this track would burn time without changing the outcome.

## What survives

- **Infrastructure is reusable.** Data layer, ledger, harness (minus the "inner loop" framing), walk-forward, orchestrator scaffolding all carry over to whatever comes next.
- **Walk-forward as a first-class harness gate.** Before moving on, fold walk-forward into the harness so any future config gets a `status = "overfit"` outcome rather than a clean in-sample score. Cheap and reusable.
- **Oracle DB (`data/prospector_oracle.db`).** Authoritative baseline for "what random search can do in this space." Keep it as a reference.

## What we're pivoting to

Research: LLM-suitable denser-signal crypto strategies where categorical reasoning actually earns its keep. Candidate families to evaluate:

- **Funding-rate arbitrage** — cross-venue or delta-neutral. Signal density is high (every funding window); the reasoning task is "does this regime persist." This matches the kalshi pattern.
- **Event-driven / narrative-driven trading** — mispricings around specific catalysts (listings, unlocks, forks, governance votes). LLM reads the narrative, sizes the trade.
- **Cross-exchange mispricing** — including Hyperliquid vs CEX spot, vs Binance perps. Lower LLM involvement but a good use of the existing data pipeline.
- **Calendar / seasonality effects** — if any exist in crypto (weekend effects, Asia/EU/US session handoffs, monthly options expiries).

The practical constraints are the market (what edges exist on Hyperliquid at our size) and the hardware (16GB MacBook, local inference). Creativity is not the constraint.

The research phase deliverable is a written prospectus: which strategy families are worth building, what data and infrastructure they require, what the LLM's specific role is in each, and which one to build first. No code until the prospectus is agreed.

## Paused work

- Remaining 4 Elder templates (`impulse_system`, `channel_fade`, `kangaroo_tail`, `ema_divergence`) — not abandoned, but not worth building until/unless the research phase revalidates the template-parameter-search approach.
- Dashboard (unit 6) — deferred until there's something worth monitoring.
- Paper trading (unit 7) and live execution (unit 8) — deferred for the same reason.

LoRA fine-tuning (mentioned in the original synopsis) is also off the table until a strategy family with the right reasoning shape is identified.

## Pointers

- Full walk-forward analysis: `docs/walk-forward-findings.md`
- Original design (now superseded for the inner-loop thesis): `docs/trading-strategy-discovery-synopsis.md`
- Updated build status: `docs/implementation-plan.md`
- Oracle baseline: `data/prospector_oracle.db`
- Walk-forward reproduction: `scripts/walk_forward_top_configs.py`
