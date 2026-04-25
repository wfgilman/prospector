---
id: 00
name: Elder templates parameter search
status: rejected
verdict: non-viable
last-update: 2026-04-14
related-components: []
---

# Candidate 00: Elder Templates Parameter Search

## Status snapshot

- **Stage:** rejected
- **Verdict:** non-viable
- **Reason:** LLM inner-loop is structurally mis-fit for continuous-parameter search; trade density in Elder templates is structurally insufficient for walk-forward validation. No variant, overlay, or scale change rescues this.
- **Next move:** None. Closed.

## Ideation

**Origin:** Original project conception. Apply LLM-driven parameter search
to Elder-derived strategy templates (`triple_screen`, `false_breakout`)
on Hyperliquid crypto perpetual futures.

**Mechanism:** An inner loop using a 7-13B Ollama model proposes JSON
configs (parameter values for the templates), evaluates against backtest
tasks, keeps/discards by score. An outer loop on Claude reviews patterns
and adds knobs.

**Why it seemed plausible:** The two-loop architecture had been proven
twice in sibling projects (`kalshi-autoagent`, `options-autoagent`) for
strategies with discrete categorical search spaces. The hypothesis was
that the same architecture would work on continuous parameter spaces.

## Deep dive

Built over ~2 weeks (early April 2026):

- **Data layer:** OHLCV download for BTC/ETH/SOL perp (1h, 4h, 1d, 1w);
  live L2 orderbook poller via launchd
- **Two strategy templates:** `triple_screen`, `false_breakout`
- **Backtest harness:** NAV simulation, Iron Triangle sizing, hard gates
  (≥20 trades, profit factor >1.3), catastrophic floor, monthly circuit
  breaker, walk-forward fold isolation
- **Ledger:** SQLite append-only log with sliding-window + coverage-cell
  prompt injection
- **Orchestrator:** Ollama-backed inner loop with `qwen2.5-coder:14b`,
  stagnation detection, duplicate filtering, mock mode

## Statistical examination

Pre-registered comparison: LLM inner-loop vs. random search at equal
harness, equal search space.

| Configuration | n | Scored rate | Max score |
|---|---|---|---|
| v1 LLM (temp 0.7, sliding window only) | 200 | 5.5% | 120 |
| v2 LLM (temp 1.0, + coverage prompt) | 200 | 11.5% | 156 |
| Random at N=300 | 300 | 18.3% | 200 |
| Oracle random (N=2000) | 2000 | 19.7% | 192.5 |

**Pre-registered pass criterion:** LLM beats random at matched N or
within 30% wall-clock.

**Result:** Random at N=100 beats LLM at N=200 on both hit rate and peak
score, at ~30× lower wall-clock cost.

## Backtest

Walk-forward validation of the top-10 oracle configs:

- **100% of `false_breakout` configs die** — zero scored folds at 3 or 5
  folds. Trade density (~40-50 trades over 5000 bars) falls below the
  20-trade per-fold gate.
- **`triple_screen` configs degrade 42-82%** on best-security holdout
  mean. At most one config (run #303) comes close to temporal consistency
  (4/5 scored folds).

The ~192 in-sample ceiling is not a discovered edge; it's what you get
when you sample 2000 random configs against 5000 bars and keep the one
that landed on a favorable slice.

## Paper portfolio

Not reached.

## Live trading

Not reached.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| Early Apr 2026 | Track launched | Two-loop architecture proven in siblings |
| 2026-04-14 | Track paused | LLM inner loop falsified for continuous parameter search; walk-forward killed all top configs |
| 2026-04-14 | Verdict: non-viable | The failure modes are structural (problem-shape mismatch + trade-sparsity), not tactical. No variant of the same approach rescues it: continuous optimization remains continuous, trade density is bounded by the templates themselves, and the book author treats the templates as arbitrary anyway (the value is in consistent application + risk management, not template choice). |
| 2026-04-14 | Pivot to research mode | Sibling projects exploit categorical structures; this project shifted to strategies where LLM categorical reasoning earns its keep |
| 2026-04-25 | Codified into [`charter/axioms.md`](../../charter/axioms.md) §5 as the LLM-comparative-advantage axiom | Generalizes the lesson |

## Cause-of-death summary

Two structural failures:

1. **Problem-shape mismatch.** LLMs are categorical reasoners over text;
   continuous 6-D noisy optimization is what bayesian optimizers and
   random search are for. No prompt engineering closes this gap because
   it's not a prompt problem.
2. **Trade-sparsity.** Elder templates produce 40-120 trades across the
   full ~5000-bar 4h history. Walk-forward requires ≥20 trades per fold
   to score. At 3 folds that's no margin; at 5 folds none at all.
   Widening ranges or adding more Elder templates doesn't fix this — they
   are shaped the same way.

## What survives

- **Infrastructure is reusable.** Data layer, ledger, harness (minus the
  "inner loop" framing), walk-forward, orchestrator scaffolding all
  carried over to the PM Underwriting work that followed.
- **Walk-forward as a first-class harness gate.** Any future config gets
  a `status="overfit"` outcome rather than a clean in-sample score.
- **Oracle DB** (`data/prospector_oracle.db`) — authoritative baseline
  for "what random search can do in this space." Kept as reference.
- **The lesson** — codified in [`charter/axioms.md`](../../charter/axioms.md)
  as the load-bearing axiom on LLM comparative advantage.

## Pointers

- Original synopsis: `docs/implementation/archived/elder-track-synopsis.md`
- Walk-forward analysis: `docs/implementation/archived/elder-track-walk-forward.md`
- Oracle baseline: `data/prospector_oracle.db`
