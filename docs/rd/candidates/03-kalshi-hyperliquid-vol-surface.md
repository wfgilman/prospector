---
id: 03
name: Kalshi × Hyperliquid implied-distribution arbitrage (vol surface)
status: absorbed
verdict: viable
last-update: 2026-04-23
related-components:
  - hedging-overlay-perp
---

# Candidate 03: Kalshi × Hyperliquid Vol Surface

## Status snapshot

- **Stage:** absorbed
- **Verdict:** viable (the underlying finding is real and durable — see D1 below); the convergence-trade *formulation* is dead.
- **Reason:** Phase 1 falsified the convergence thesis cleanly. Diagnostic D1 surfaced a real, durable longshot-bias wedge — but it's the same edge PM Underwriting already exploits. The new information (delta-hedgeability via Hyperliquid perps) is folded into the [hedging-overlay-perp component](../../components/hedging-overlay-perp.md) scoped for PM books.
- **Next move:** None as standalone. Component re-scoped for PM Phase 5 hedging overlay if/when triggered.

## Ideation

**Origin:** Kalshi's `KXBTC-*` and `KXETH-*` intraday range contracts
form a literal 40-strike implied probability distribution for BTC/ETH
terminal price. Hyperliquid perp encodes a different implied
distribution via funding rate, basis, and realized vol. When the two
disagree, someone is wrong. Buy underpriced tails of the Kalshi ladder,
sell overpriced tails, delta-hedge with BTC_PERP. Convergence at expiry
is the payoff.

**Axiomatic fit:**
- *Combinations* — vol arbitrage (40 years old) + prediction markets +
  perp-implied-distribution as reference (novel)
- *Small-player advantage* — cross-venue execution requires running code
  against two different exchange types; institutions don't usually
- *Cross-market* — fills the structural gap that every other strategy in
  the project trades within a single venue

## Deep dive

### Two distributions

**Kalshi-implied terminal CDF `F_K`** — at time `t`, event expiring at
`T`, for each strike bucket compute `p_i = yes_mid(ticker_i)`. Prices
sum to 1.0 (up to fee wedge). Result is a 40-point sampled CDF; integrate
or fit smooth density.

**Perp-implied terminal CDF `F_P`** — construct from:
- Spot (Hyperliquid BTC_PERP mid)
- Drift = annualized funding hour-by-hour (negligible over 25h horizon)
- Diffusion = EWMA(λ=0.94) σ from past 24-72h of 1m returns
- Assume lognormal terminal at `T`

Discretize at same strike midpoints to get `q_i`.

### Signal

Per (event, snapshot):
- Compute per-bucket gap `p_i - q_i` and max-gap statistic
- If max-gap > τ (300bp pre-registered): buy buckets where p < q,
  sell buckets where p > q
- Compute hedge delta; offset with BTC_PERP
- Re-hedge hourly; exit on convergence, expiry, or stop-loss

## Statistical examination

### Methodology — locked pre-registration (§5.0 of original deep-dive)

Twelve continuous/discretionary knobs locked in code before any test
ran. EWMA λ=0.94, 48h lookback, drift=0, snapshot cadence 15 min, ladder
completeness ≥ 0.75, threshold τ=300bp, divergence metric = max absolute
gap, mean-reversion horizon Δt=1h ahead.

Hard date split: train 2025-09-17 → 2026-01-09, test 2026-01-10 →
2026-04-22. Test fold seen exactly once. Null-shuffle benchmark.

**Pre-committed pass criteria (all required on test fold):**
- ≥ 30% of tuples have max-gap > 300bp
- Mean-reversion half-life < 30% of remaining event life
- Null-shuffle passing rate < 10% (real ≥ 3× noise)

### Phase 1 result (2026-04-22) — convergence thesis FAILS

| Fold | n | Median gap | p90 gap | Reversion β | Half-life |
|---|---|---|---|---|---|
| Train | 2,757 | 12.8% | 38.3% | −0.054 | 12.5h |
| **Test (real)** | **1,872** | **9.1%** | **32.8%** | **+0.013** | **NaN (no reversion)** |
| Test (null) | 1,872 | 24.9% | 76.1% | −0.86 | 0.35h |

**Pre-registered criteria:**

| Criterion | Threshold | Test fold | Decision |
|---|---|---|---|
| (a) Tuples with max-gap > 300bp | ≥ 0.30 | **0.955** | PASS (trivially — threshold too lax) |
| (b) Reversion half-life < 3.0h | < 3.0h | **NaN** | **FAIL** |
| (c) Null-shuffle passing fraction | < 0.10 | **0.953** | **FAIL** |

**Interpretation:**

1. **Kalshi↔perp alignment is real.** Real-pair median gap 9.1% vs.
   null-pair 24.9% — ratio 0.37. Scrambling pairings nearly triples
   divergence. Genuine cross-market information exists.
2. **Gaps don't converge — they're structural shape mismatch.** β ≈ 0
   in test; today's gap has no predictive power for tomorrow's. Lognormal
   reference is wider than Kalshi-implied (heavier tails, less peak near
   spot). Persistent per-bucket wedge, not short-term mispricing.

The convergence trade as specified doesn't work.

### Phase 1 diagnostic — 4 measurements

| # | Diagnostic | Outcome | Pass? |
|---|---|---|---|
| D1 | Per-bucket-position signed gap | Renorm: −10pp at rel_pos=0, t=−50, n=4,601. Raw: +16.78pp at rel_pos=+17, t=+17.5, n=901 | **PASS** |
| D2 | Terminal convergence (gap vs life decile) | slope = −0.0005/decile (flat) | FAIL |
| D3 | Empirical-bootstrap reference vs lognormal | emp/lognormal ratio = 1.016 (identical) | FAIL |
| D4 | Moderate-volume universe (100-500 trades) | gap ratio = 1.23, β = −0.087 | FAIL |

**D1 finding (the keeper):** Kalshi systematically prices far-OTM range
buckets at meaningful probabilities (~5-15¢) where the lognormal assigns
near-zero probability. Wedge peaks at rel_pos ±17 (~$8,500 OTM at $500
bucket width) with mean signed gap +16.78pp and t-stat 17.5.

**This is the favorite-longshot bias** documented in sports betting and
horse racing — already identified in PM Underwriting's Phase 1
calibration work (crypto longshots show favorite-longshot bias in 5/20
bins).

D3 closes the lognormal-as-reference question: lognormal and empirical-
bootstrap from BTC's own 25h returns give median gaps that agree to
within 2%. The reference family is not the problem.

### Phase 3 re-validation (2026-04-23, post-data-migration)

Re-run on unified in-house tree extending test fold to 2026-04-23 (~5×
more data). Same hyperparameters.

| Result | Phase 1 | Phase 3 | Replicates? |
|---|---|---|---|
| Convergence thesis | FAIL | FAIL (β=+0.024, half-life NaN) | Yes — conclusively dead |
| D1 renorm at rel_pos=0 | −10.08pp, t=−50 | −9.41pp, t=−52, n=5,277 | Yes |
| D1 raw at rel_pos=+17 | +16.78pp, t=+17.5 | +12.60pp, t=+17.2, n=1,222 | Yes (magnitude softens — rally vs. crash regime) |
| Real/null gap ratio | 0.37 | 0.22 | Cross-market alignment is *stronger* with more data |

All four diagnostic outcomes replicate.

## Backtest, paper, live

Not reached as standalone — absorbed.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Selected as second R&D track | Filled the cross-market gap; cleanest kill criterion in queue |
| 2026-04-22 | Phase 1 result: convergence thesis dead | Pre-registered criteria failed; β ≈ 0 with no reversion |
| 2026-04-22 | Phase 1 diagnostic — D1 passes (1/4 ≥ 1) | Real but is the same favorite-longshot bias PM already exploits |
| 2026-04-22 | Decision point: continue as delta-hedged longshot, fold into PM Phase 5, or pivot | Recommendation: fold into PM Phase 5 hedging overlay |
| 2026-04-23 | Phase 3 confirms (5× data, same conclusion) | Convergence is conclusively dead; D1 wedge replicates across windows |
| 2026-04-23 | Verdict: absorbed (viable finding, dead formulation) | The wedge is real and durable; the trade structure was wrong; the new info (delta-hedgeability) folded into PM Phase 5 |
| 2026-04-25 | Component split out: [`hedging-overlay-perp`](../../components/hedging-overlay-perp.md) | The mechanism is reusable across any Kalshi book whose payoff has a hedgeable underlying |

## What survives

- **D1 wedge replication** at t-stats of ±17 to ±52 across two non-
  overlapping windows. Real, durable, structural — favorite-longshot
  bias measured in Kalshi crypto contracts.
- **The cross-venue execution component** ([`hedging-overlay-perp`](../../components/hedging-overlay-perp.md)),
  scoped for PM Phase 5.
- **Pre-registration discipline.** The Phase 1 → Phase 3 replication is
  textbook; the divergence-thesis failure was caught cleanly without
  retro-fit and the D1 finding was acknowledged honestly even though it
  reframed the candidate.
- **Infrastructure.** In-house Kalshi data pipeline ([component](../../platform/data-pipeline.md))
  was elevated to "core competency" in response to this work.

## What it is NOT

The D1 finding is **not** a new edge — it's the favorite-longshot bias
already trading in PM Underwriting. The candidate's contribution is the
realization that **crypto positions are delta-hedgeable** in a way sports
parlays aren't, which suggests a perp-hedged variant of the existing PM
crypto slice. That's what got folded into PM Phase 5 / the hedging
component.

## Pointers

- Hedging mechanism: [`components/hedging-overlay-perp.md`](../../components/hedging-overlay-perp.md)
- Sister candidate using D1 edge directly: [`01-pm-underwriting-lottery.md`](01-pm-underwriting-lottery.md) (crypto slice)
- Data pipeline that was elevated in response: [`platform/data-pipeline.md`](../../platform/data-pipeline.md)
