# Implementation Plan — PM Underwriting

Prediction market underwriting strategy applied to Kalshi. Treats the Kalshi marketplace as an insurance book: build actuarial calibration curves from historical resolutions, identify systematically mispriced contracts, and trade the deviation.

For the full strategy prospectus and empirical derivation, see [`docs/rd/deep-dive-prediction-market-underwriting.md`](../rd/deep-dive-prediction-market-underwriting.md). For detailed methodology (data pipeline, math, assumptions), see [`docs/implementation/methodology.md`](methodology.md).

For the paused Elder-template parameter-search track, see [`docs/implementation/archived/`](archived/) and [`docs/rd/elder-track-pivot.md`](../rd/elder-track-pivot.md).

---

## Strategy Summary

**Edge:** Kalshi market prices deviate from true resolution rates. Two confirmed sources:
1. **Sports parlay overpricing** — Multi-leg sports bets systematically overpriced (prospect theory). Large edge (~4-7pp), but only ~6 months of history.
2. **Crypto longshot overpricing** — Classic favorite-longshot bias. Moderate edge (~3-4pp), more persistent.

**Mechanism:** Build per-category calibration curves (implied probability vs actual resolution rate) from historical data. When a live market's price deviates from the calibration curve by more than the fee-adjusted threshold, take the other side. Size with fractional Kelly (0.25x).

**Data source:** TrevorJS/kalshi-trades HuggingFace dataset (154M trades, 17.5M markets, June 2021 – Jan 2026). Internally validated (99.71% consistency). Stored at `data/kalshi_hf/` (5.3 GB parquet, gitignored).

---

## Phases

| Phase | Description | Status | Result |
|---|---|---|---|
| 1 | Calibration curve | **Complete** | GO — 6 qualifying bins aggregate, 16 in sports parlays. Systematic overpricing confirmed. |
| 2 | Walk-forward backtest | **Complete** | GO — Sharpe 7.44, 66.9% WR, 83.6K trades. Calibration holds out-of-sample. |
| 2b | Capital-constrained simulation | **Complete** | GO at 20 trades/day: Sharpe 9.19, 303% return/41d, 3.4% max DD. Sports dominates (86% of trades). |
| 3 | Paper trading | **Next** | Validate execution quality and calibration on truly live data. |
| 4 | Live (small) | Pending | 5% of intended NAV after Phase 3 validation. |

---

## Phase 1 — Calibration Curve (Complete)

Built PIT (point-in-time) calibration curves from 453K resolved markets.

**Method:** For each resolved market, compute the last trade price at 50% of market duration via ASOF join. Bin by 5% implied probability. Measure actual resolution rate per bin. Compare to perfect calibration (45-degree line).

**Key results:**
- 6 aggregate bins with >3pp deviation, n>=100, positive after Kalshi taker fees
- Sports: 16/20 bins show signal — parlay overpricing is pervasive
- Crypto: 5/20 bins — favorite-longshot bias in low-probability markets
- Financial/weather: near-efficient — no tradeable edge after fees
- Economics/politics: too few markets for statistical power

**Script:** `scripts/build_calibration_curve.py`
**Output:** `data/calibration/calibration_curves.png`

---

## Phase 2 — Walk-Forward Backtest (Complete)

70/30 temporal split (train: pre-2026-01-01, test: Jan 2026). Calibration curves built on train set only; portfolio simulated on test set with fractional Kelly sizing.

**Unconstrained results (all tradeable markets):**
| Metric | Value |
|---|---|
| Sharpe | 7.44 |
| Win rate | 66.9% |
| Total trades | 83,643 |
| Calibration accuracy | Train predicts test within 0.3-2.0pp for most bins |

**Caveats:** Test period is ~1 month. Win rate inflated by many small-edge trades. Concurrent exposure not modeled in unconstrained version.

**Script:** `scripts/walk_forward_backtest.py`
**Output:** `data/calibration/walk_forward_backtest.png`

---

## Phase 2b — Capital-Constrained Simulation (Complete)

Realistic portfolio simulation with concurrent position tracking, daily capital budget, per-event correlation cap, and throughput limits.

**Model:** Walk through time day-by-day. Positions entered at PIT time, resolved at close_time. Capital committed (risk budget) is locked until resolution. Priority: highest-edge candidates first.

**Constraints:**
- 1% of NAV max risk per position
- 5% of NAV max risk per event_ticker (correlated markets)
- Configurable trades-per-day cap
- Flat sizing (initial NAV) to isolate edge from compounding

**Throughput comparison ($10K NAV, 41-day test period):**

| Trades/day | Return | Sharpe | Max DD | Win Rate | Trades | Utilization |
|---|---|---|---|---|---|---|
| 20 | 303.6% | 9.19 | 3.4% | 29.0% | 639 | 37% |
| 50 | 575.8% | 8.83 | 6.1% | 29.6% | 1,382 | 46% |
| 100 | 747.1% | 7.31 | 4.3% | 33.2% | 2,625 | 52% |
| Unlimited | 2,365% | 9.46 | 4.3% | 50.6% | 16,108 | 92% |

**Key insights:**
- **Throughput, not capital, is the binding constraint.** Return % is NAV-independent (proportional sizing).
- **29% win rate is by design.** Selling overpriced yes contracts at 80-95 cents loses most individual trades but wins big (9:1+ payoff) on "no" resolutions.
- **Sports parlays dominate.** At 20/day: 86% of trades, 104% of P&L.
- **Returns are overstated.** 41-day test window, assumes perfect fills at PIT price, no market impact. Real-world execution friction will reduce returns significantly.

**Script:** `scripts/capital_constrained_sim.py`
**Output:** `data/calibration/capital_constrained_sim.png`

---

## Phase 3 — Paper Trading (Next)

Validate that the calibrated edge exists in live markets and that orders can be filled at edge prices.

### Components to Build

1. **Kalshi API client** — REST for market data, orderbook, resolution status. Reference: `kalshi-arb-trader` sibling project.
2. **Calibration store** — Persist and periodically update calibration curves.
3. **Market scanner** — Poll active markets, classify category, compute edge vs calibration.
4. **Paper portfolio** — SQLite-backed position tracker with capital constraints (same as Phase 2b).
5. **Resolution monitor** — Poll for resolved markets, record P&L.
6. **Runner daemon** — Main loop under launchd. Scan interval ~15 min, 20 trades/day cap.

### Key Decisions

| Decision | Backtest Assumption | Paper Trading Approach |
|---|---|---|
| Entry timing | PIT (50% of market duration) | When scanner finds edge (any time) |
| Pricing | Maker (zero fees) | Test both maker and taker |
| Min edge | 2pp | Start at 3pp (conservative) |
| Categories | All | Start with crypto + sports only |
| Throughput | 20/day cap | Same |

### Success Criteria

- Positive P&L after 30 days
- Maker fill rate > 50% (validates zero-fee assumption)
- Observed win rate within 5pp of calibration prediction
- No single-day drawdown > 5% of NAV

---

## Phase 4 — Live (Small)

Deploy at 5% of intended NAV after Phase 3 validation. Reuse paper trading infrastructure with real order submission. Details TBD pending Phase 3 results.
