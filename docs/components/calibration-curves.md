# Calibration Curves

> The actuarial mechanism: empirically measure the resolution rate at each
> implied probability bin, treat deviations from the 45° line as edge.

**Status:** In production. Powers both PM Underwriting books (Lottery + Insurance).

---

## What it does

For every resolved historical Kalshi market, record the price-at-PIT and
the eventual yes/no outcome. Bin by 5¢ implied probability. Per bin,
measure: how often did markets at that price resolve "yes"? Where the
empirical rate deviates from the implied probability by more than fees,
that's a tradeable edge.

Edge example: contracts priced at 90¢ implied (90% probability) that
actually resolve "yes" only 80% of the time → 10pp gap. Selling yes
systematically captures that gap, less fees, in expectation.

---

## Math

### Point-in-Time (PIT) pricing

We can't use `last_price` because it converges to the outcome (markets
resolving yes have last trades near 99¢). Instead, take the price at 50%
of the market's life:

```
pit_time = open_time + (close_time - open_time) / 2
```

Find the latest trade at-or-before `pit_time` via DuckDB ASOF join. If no
pre-PIT trade exists, fall back to the first post-PIT trade.

### Time-offset filter

Reject markets where the matched trade is too far from `pit_time`:

```
offset_frac = |trade_time - pit_time| / (close_time - open_time)
```

`offset_frac > 0.25` → drop. The matched trade must be within the middle
50% of the market's life. This filters from ~3.5M resolved markets to
~454K usable ones.

### Binning

20 bins of 5pp width: 0-5%, 5-10%, ..., 95-100%. Per bin compute:

- `n` — number of markets
- `yes_count` — number resolving "yes"
- `actual_rate` = `yes_count / n`
- `implied_mid` — bin midpoint (e.g., 7.5% for 5-10%)
- `deviation` = `actual_rate - implied_mid`

A perfectly calibrated market has deviation ≈ 0 for all bins. Deviations
indicate where to trade.

### Wilson confidence intervals

Raw rates are noisy for small `n`. We use Wilson score intervals (not
naive normal approximation) because they're well-behaved at small samples
and extreme proportions:

```
center = (p̂ + z²/2n) / (1 + z²/n)
spread = z × √((p̂(1-p̂) + z²/4n) / n) / (1 + z²/n)
CI = [center - spread, center + spread]
```

with `p̂ = yes_count/n` and `z = 1.96` (95%).

### Fee-adjusted edge

Kalshi charges taker fees `0.07 × P × (1-P)` per side. Round-trip:

```
fee_roundtrip = 2 × 0.07 × P × (1-P)
fee_adj_edge  = |deviation| - fee_roundtrip
```

Fees are highest at P=0.5 (1.75¢ round-trip) and lowest at the extremes.
This means the wings naturally have more headroom for edge to survive
fees — which is why the edge ranker pulls toward extremes when allowed.

### Signal detection (Go/no-go)

A bin has tradeable signal if all three hold:
1. `n ≥ 100` (sample size)
2. `|deviation| > 3pp` (deviation exceeds noise threshold)
3. `fee_adj_edge > 0` (edge survives fees, taker-conservative)

**Project-level Go criterion:** ≥ 3 bins with signal in the aggregate
curve. If the curve is flat (within ±2pp everywhere), the market is
well-calibrated and there's no edge.

**Empirical result (2026-04-16):** GO. 6 qualifying bins aggregate, 16/20
in sports. See [PM Lottery candidate](../rd/candidates/01-pm-underwriting-lottery.md) for full per-category breakdown.

### Per-side classification

Per bin, the side is implied by deviation direction:
- `actual_rate < implied_mid` → market overprices yes → side is `sell_yes`
- `actual_rate > implied_mid` → market underprices yes → side is `buy_yes`

A bin has at most one side. The scanner only considers candidates where
the orderbook side matches the bin's calibrated side.

---

## Per-category segmentation

Built per category plus an aggregate fallback. Categories are assigned by
event-ticker prefix (one canonical taxonomy in
`src/prospector/strategies/pm_underwriting/categorize.py`):

| Category | Prefix patterns |
|---|---|
| sports | `KXMVESPORTS`, `KXNFL`, `KXNBA`, `KXNCAA`, `KXMVENFL`, `KXMVENBA` |
| crypto | `KXBTC`, `KXETH`, `KXSOL`, `KXDOGE`, `KXSHIBA`, `KXXRP` |
| financial | `KXNASDAQ`, `KXINX`, `NASDAQ`, `INX`, `USDJPY`, `EURUSD` |
| weather | `KXCITIES`, `HIGH`, `LOW` |
| economics | `CPI`, `FED`, `KXFED`, `GDP` |
| politics | `PRES`, `SENATE`, `HOUSE`, `KXGOV`, `KXMAYOR` |
| other | (everything else) |

The lookup falls back to the aggregate curve if a category bin has
insufficient data (`n < 50`).

---

## Entry-price band filter

Strategies can scope themselves to a slice of the calibration surface via
a runner-level entry-price band:

| Book | Band | What it tests |
|---|---|---|
| Lottery | 0.0-1.0 (no filter) | Edge ranker pulls to 85-99¢ extremes naturally |
| Insurance | 0.55-0.75 | The actuarial premium where σ is low and WR is high |

The filter is applied after σ-rank, before portfolio entry. Same
calibration surface, different slice — the bins themselves are unchanged.

---

## Implementation pointer

| File | Role |
|---|---|
| `scripts/build_calibration_curve.py` | Phase 1 build script, produces visualizations |
| `scripts/refresh_calibration_store.py` | Builds versioned snapshots for the daemon |
| `src/prospector/strategies/pm_underwriting/calibration.py` | `Calibration` + `CalibrationStore` + `fee_adjusted_edge()` |
| `src/prospector/strategies/pm_underwriting/scanner.py` | Live edge lookup (`evaluate_market`) |

For the storage model, see [`../platform/calibration-store.md`](../platform/calibration-store.md).

---

## Where it's applied

- **PM Underwriting · Lottery** — full price range, edge/σ ranker
- **PM Underwriting · Insurance** — 0.55-0.75 band, edge/σ ranker
- (Future) any new candidate that wants to apply calibration on a
  different category set, time window, or PIT methodology

---

## Trade-offs

**Why this works:** Edge is empirical, not assumed. The calibration curve
is the strategy's edge — if the curve is flat, there's no trade.
Categorical segmentation matters because biases are category-specific
(sports parlay overpricing ≠ crypto longshot bias).

**What it gives up:**
- **Stationarity assumption.** The curve is built on historical data and
  assumed to predict the future. If the market becomes more efficient
  over time, the edge decays. Mitigated by rolling recalibration.
- **PIT-as-entry assumption.** Backtests assume we can enter at PIT
  price. Real fills may be worse. CLV instrumentation is what measures
  this in production.
- **Category-classification fragility.** New event-ticker prefixes fall
  into "other" until added. Sports growth forced multiple updates.
- **Non-stationary at the tail.** 85-100¢ implied bins show 5-8pp
  train→test calibration gaps — less stable than mid-range bins.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-16 | Phase 1 build → GO | 6 aggregate bins + 16/20 sports bins exceed signal threshold |
| 2026-04-16 | PIT pricing methodology adopted from kalshi-autoagent | Avoids last-price terminal-convergence bias |
| 2026-04-16 | 25% offset filter | Drops markets where the matched trade is too far from PIT |
| 2026-04-21 | min_edge_pp raised from 3 → 5 (Lottery book) | Drops ~90% of low-Sharpe filler trades; concentrates capital in the high-Sharpe slice |
| 2026-04-25 | Insurance book uses min_edge_pp=3 | Mid-bin edges are smaller; 3pp is appropriate for the 0.55-0.75 band |
| 2026-04-25 | Doc consolidated into components/ | Was distributed across implementation/methodology.md, plan.md, deep-dive |
