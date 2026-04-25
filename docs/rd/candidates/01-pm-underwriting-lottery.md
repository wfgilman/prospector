---
id: 01
name: PM Underwriting · Lottery
status: paper-portfolio
verdict: pending
last-update: 2026-04-25
related-components:
  - calibration-curves
  - equal-sigma-sizing
  - clv-instrumentation
  - shadow-rejection-ledger
  - fee-modeling-kalshi
  - hedging-overlay-perp  # scoped, not active
---

# Candidate 01: PM Underwriting · Lottery

## Status snapshot

- **Stage:** paper-portfolio (live since 2026-04-20; relaunched on equal-σ 2026-04-21)
- **Verdict:** pending — 5 days of live data; first CLV reading shows
  open-book median CLV −2.5pp, beat-line 24%. Within expected variance
  for a 9:1 lottery payoff at N=80.
- **Next move:** Continue paper accrual; CLV delta check ~Monday (T+48h
  from 2026-04-25 baseline); 30-day Sharpe assessment around 2026-05-20.

## Ideation

**Origin:** Apply the actuarial calibration framework from insurance
underwriting to Kalshi prediction markets. Hypothesis: market prices
deviate from true resolution rates in measurable, persistent ways
(longshot bias, parlay overpricing, category-specific calibration error);
systematic exploitation of the gap is a positive-EV book.

**Why-now:** Kalshi launched 2021; only by 2024-2025 is there enough
historical resolution data (420K+ markets via TrevorJS HF, now in our
unified tree) to build credible calibration curves. Sports markets
launched mid-2024 and have the strongest signal to date.

**Axiomatic fit:**
- *Combinations* — actuarial calibration (decades-old) + prediction
  markets (years-old). Fits axiom 1.
- *Small-player advantage* — Kalshi's per-user position limits favor
  small operators; institutional desks size into limits and have to trade
  through the book. Fits axiom 2.
- *LLM categorical role* — segmenting events into categories for per-
  category calibration; assessing pairwise correlation between contracts.
  Fits axiom 5.

## Deep dive

### The actuarial parallel

An auto insurer prices a policy for a 25-year-old male in Houston by
historical claim rate (4.2%), charges premium covering expected loss + ops +
profit, writes 100K policies, lets LLN converge to expected value. Three
requirements: calibration (4.2% is accurate from claims data),
independence (one crash doesn't cause another), volume (enough policies).

Map to Kalshi: each contract priced at P implies probability P. If
contracts at P=20¢ resolve "yes" only 15% of the time, the market
overprices by 5pp. Underwriter who sells "no" across many such contracts
earns the gap × volume.

Three requirements map exactly: calibration (from 420K historical
resolutions), independence (LLM-assessable), volume (hundreds of active
contracts).

### Why this hasn't been done before

Prediction markets are young; historical resolution data at scale only
exists in the last 1-2 years. Most PM traders are single-domain
specialists (a weather trader, a politics trader). Nobody has approached
Kalshi as a cross-domain insurance book because that requires the
actuarial framing (from a different discipline) plus correlation
assessment across domains (which the LLM provides).

### Strategy mechanism

For each active Kalshi market:

1. Look up calibrated edge from per-category curve at the matched 5¢ bin
2. Determine side: `actual_rate < implied_mid` → sell_yes; otherwise buy_yes
3. If fee-adjusted edge clears the floor, surface as a candidate
4. Equal-σ size; rank by `edge_pp / σ_bin`
5. Enter top candidates respecting all caps

For the calibration math, see [`calibration-curves`](../../components/calibration-curves.md).
For sizing, [`equal-sigma-sizing`](../../components/equal-sigma-sizing.md).
For fee model, [`fee-modeling-kalshi`](../../components/fee-modeling-kalshi.md).

### Payoff profile note (the lottery framing)

The deep-dive prospectus described this as "writing many small policies
for premium" — the insurance metaphor. **Empirically, the edge ranker
systematically pulls to 85-99¢ extreme-price bins because σ ramps up
faster than edge in the wings**, and the per-position cap is binding. The
realized payoff profile is **9:1 lottery tickets**: ~29% win rate × large
wins vs. ~71% loss rate × small losses.

This is not a defect — it's a positive-EV book by the same calibration
math. But the "underwriting" name is aspirational; this book trades the
extremes. The companion [`Insurance candidate`](04-pm-underwriting-insurance.md)
runs the original-thesis insurance shape on the 0.55-0.75 band where the
metaphor actually applies.

## Statistical examination

### Phase 1 — Calibration curve (2026-04-16)

**Method:** PIT pricing at 50% market duration via DuckDB ASOF join over
140M trades. 453K resolved markets survived the ≤25% time-offset filter.
5% implied-probability bins, Wilson confidence intervals. See
[`calibration-curves`](../../components/calibration-curves.md) for full math.

**Aggregate result — GO (6 qualifying bins):**

The market systematically overprices events. Actual resolution rates fall
3-4pp below implied prices across the 25-70% range. Fee-adjusted edges
(maker pricing) are 0.1-0.5pp.

**Per-category breakdown:**

| Category | n | Signal bins | Key finding |
|---|---|---|---|
| Sports | 205K | 16/20 | Parlay overpricing; deviations 8-15pp at mid-to-high implied. Structural; ~6 months of history. |
| Crypto | 117K | 5/20 | Longshot overpricing (10-30% implied, 3-4.5pp deviation). Classic favorite-longshot bias. |
| Other | 91K | 12/20 | Broad overpricing similar to sports |
| Financial | 28.5K | 2/20 | Mostly well-calibrated; edge only at 35-40% and 95-100% |
| Weather | 9.6K | 4/20 | Noisy but promising; small samples at tails |
| Economics | 1.3K | 1/20 | Too small for conclusions |
| Politics | 385 | 0/20 | Insufficient sample |

**Sensitivity tests passed:** filter relaxation at 10/15/25/35/50% offset
thresholds; temporal stability — bias present from 2024 H2 onward.

**Key revision to thesis:** The bias is NOT the classic favorite-longshot
pattern predicted by the literature. It's dominated by (1) sports parlay
overpricing and (2) crypto longshot overpricing. Financial / weather are
near-efficient.

## Backtest

### Phase 2 — Walk-forward (2026-04-17)

**Method:** Train on first 70% of markets (pre-Jan 2026), test on last
30% (~136K markets). Equal-σ sizing on initial NAV ($10K), 1% max
position, 5pp minimum edge, maker pricing (zero fees).

**Results:**

| Metric | Value |
|---|---|
| Total trades | 83,578 |
| Win rate | 66.9% |
| Total P&L | $1,590,561 |
| Sharpe | 7.44 |
| Max drawdown | 0.0% (artifact of daily aggregation) |

| Category | Trades | P&L | Win rate |
|---|---|---|---|
| Sports | 58,601 | $815,887 | 66.2% |
| Other | 14,364 | $616,553 | 63.8% |
| Financial | 995 | $131,019 | 28.2% |
| Crypto | 9,550 | $27,319 | 79.5% |

Calibration accuracy: train predicts test within 0.3-2.0pp for most bins
(15-65% implied). Larger gaps at tails (85-100%: 5-8pp).

### Phase 2b — Capital-constrained simulation

Realistic portfolio with concurrent position tracking, daily capital
budget, per-event correlation cap, throughput limits.

**Throughput comparison ($10K NAV, 41-day test period):**

| Trades/day | Return | Sharpe | Max DD | Win Rate | Trades | Utilization |
|---|---|---|---|---|---|---|
| 20 | 303.6% | 9.19 | 3.4% | 29.0% | 639 | 37% |
| 50 | 575.8% | 8.83 | 6.1% | 29.6% | 1,382 | 46% |
| 100 | 747.1% | 7.31 | 4.3% | 33.2% | 2,625 | 52% |
| Unlimited | 2,365% | 9.46 | 4.3% | 50.6% | 16,108 | 92% |

**Key insights:**
- Throughput, not capital, is the binding constraint
- 29% win rate by design (high-edge bins are extreme-price; payoff is asymmetric)
- Sports parlays dominate (86% of trades, 104% of P&L at 20/day)
- Returns overstated by perfect-fill assumptions

## Paper portfolio

### Phase 3 launch (2026-04-20)

**Infrastructure:** See [`paper-trade-daemon`](../../platform/paper-trade-daemon.md)
and [`portfolio-accounting`](../../platform/portfolio-accounting.md).

**Live config:**

| Knob | Value |
|---|---|
| Initial NAV | $10,000 |
| Sizing | Equal-σ ([component](../../components/equal-sigma-sizing.md)) |
| `book_σ_target` | 0.02 |
| `N_target` | 150 |
| `max_position_frac` | 0.01 |
| `max_event_frac` | 0.05 |
| `max_bin_frac` | 0.15 |
| `max_trades_per_day` | 20 |
| `min_edge_pp` | 5.0 |
| `max_days_to_close` | 28 (with shadow ledger) |
| Categories | sports, crypto |
| Entry-price band | 0.0 - 1.0 (full) |

**Pre-committed kill criteria:**
- Negative P&L after 30 days
- Maker fill rate < 50% (validates zero-fee assumption)
- Observed win rate > 5pp from calibration prediction
- Single-day drawdown > 5% of NAV

### Live state (2026-04-25)

| Metric | Value |
|---|---|
| Days running | 5 |
| Total trades | ~80 |
| Open positions | 19 (NBA-dominated) |
| NAV | $9,883 (−1.2% from seed) |
| Realized P&L | −$117 |

### Phase 3.5 — Sizing reevaluation (2026-04-21)

Mid-Phase-3 surfaced a structural mismatch between sizing framework and
realized payoff profile. Empirical per-bin σ measurement showed per-bet
Sharpe 0.057 (all trades) / 0.110 (high-edge slice); for 90% book
confidence, N = 136-511 positions needed. Phase 3 was running ~36.

**Resolution shipped 2026-04-21:**
- Equal-σ replaces fractional Kelly ([component](../../components/equal-sigma-sizing.md))
- `max_bin_frac=0.15` replaces `max_category_frac=0.20`
- Runner ranks by `edge_pp / σ_bin`
- `min_edge_pp` raised 3 → 5
- Kelly book archived; fresh book launched on equal-σ

### Phase 3.5+ — CLV instrumentation (2026-04-24)

Added per-trade CLV measurement; see
[`clv-instrumentation`](../../components/clv-instrumentation.md).

**First-run reading (2026-04-24):**
- Open-book median CLV: −2.5pp
- Beat-line rate: 24%
- `corr(edge_pp, clv_pp)`: +0.144 (scanner edge is a noisy CLV proxy)
- 85-90¢ bin worst (18.8% beat); 95-100¢ best (57.1%)

The market is moving against most entries within the holding window. This
is what motivates the [MVT rolling-threshold](../../components/mvt-rolling-threshold.md)
component design (T2 from fresh-eyes review).

### Expiry screen + shadow ledger (2026-04-23)

Markets resolving > 28 days out get rejected and logged. See
[`shadow-rejection-ledger`](../../components/shadow-rejection-ledger.md).

## Live trading

Not reached. Phase 4 gated on:
- Phase 3 results across full 30-day window
- CLV delta showing scanner is selecting edges that survive the holding window
- Maker fill rate validation
- User authorization for live capital

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-14 | Strategy selected as the post-Elder pivot | Highest LLM categorical fit + cleanest kill criterion |
| 2026-04-16 | Phase 1 GO | 6 aggregate signal bins, 16/20 sports |
| 2026-04-17 | Phase 2 GO | Sharpe 7.44 walk-forward; calibration generalizes |
| 2026-04-19 | Phase 2b GO | Sharpe 9.19 at 20 trades/day; throughput-bound |
| 2026-04-20 | Phase 3 launch on Kelly | Standard fractional Kelly; calibration validation |
| 2026-04-21 | Switched to equal-σ; archived Kelly book | Per-bet σ varies 30×; Kelly under-sized 4-14× |
| 2026-04-23 | Expiry screen + shadow ledger added | Long-dated markets crowd out validation |
| 2026-04-24 | CLV instrumentation shipped | Faster edge-validation signal than realized P&L |
| 2026-04-25 | First CLV read shows median −2.5pp on open book | Within expected variance; not yet decisive |

## Pointers

- Calibration component: [`components/calibration-curves.md`](../../components/calibration-curves.md)
- Sizing component: [`components/equal-sigma-sizing.md`](../../components/equal-sigma-sizing.md)
- CLV component: [`components/clv-instrumentation.md`](../../components/clv-instrumentation.md)
- Daemon: [`platform/paper-trade-daemon.md`](../../platform/paper-trade-daemon.md)
- Portfolio model: [`platform/portfolio-accounting.md`](../../platform/portfolio-accounting.md)
- Sister candidate: [`04-pm-underwriting-insurance.md`](04-pm-underwriting-insurance.md)
