# Fee Modeling — Kalshi

> The fee math behind the round-trip cost factor and why fees shape which
> bins are tradeable.

**Status:** In production. Used by every PM Underwriting calibration
calculation and entry.

---

## Kalshi fee structure (as of 2026)

| Side | Fee per contract per side |
|---|---|
| Maker (resting limit) | **Zero** |
| Taker (crossing the spread) | `0.07 × P × (1 − P)` |

Round-trip taker (paying it on entry and at exit/resolution):

```
fee_roundtrip = 2 × 0.07 × P × (1 − P) = 0.14 × P × (1 − P)
```

In code: `KALSHI_ROUND_TRIP_FEE_FACTOR = 0.14`.

---

## Where fees are applied

### In the calibration curve

```
fee_adj_edge = |implied_mid - actual_rate| - 2 × 0.07 × P × (1 − P)
             = |deviation| - fee_roundtrip
```

A bin is tradeable only if `fee_adj_edge > 0`.

### In the paper portfolio

Each entered position is debited `fees_paid = 0.14 × P × (1−P) × contracts`
at entry. On resolution, `realized_pnl = gross - fees_paid`. Voids refund
fees so realized_pnl stays 0.

---

## What the fee curve looks like

| Price `P` | Per-side fee (¢) | Round-trip (¢) | % of $1 contract |
|---|---|---|---|
| 0.05 | 0.33 | 0.67 | 13.3% (of the 5¢ contract) / 0.7% (of $1 face) |
| 0.10 | 0.63 | 1.26 | 12.6% / 1.3% |
| 0.20 | 1.12 | 2.24 | 11.2% / 2.2% |
| 0.30 | 1.47 | 2.94 | 9.8% / 2.9% |
| 0.50 | 1.75 | 3.50 | 7.0% (of $0.50 risk per side) |
| 0.70 | 1.47 | 2.94 | 9.8% / 2.9% |
| 0.80 | 1.12 | 2.24 | 11.2% / 2.2% |
| 0.90 | 0.63 | 1.26 | 12.6% / 1.3% |
| 0.95 | 0.33 | 0.67 | 0.7% |

**Two key observations:**

1. **Fees peak at P = 0.5** (by construction — it's a parabola maximum
   at the midpoint).
2. **Fees are lowest at the extremes.** A 5¢ or 95¢ contract round-trips
   for less than 1% of $1 face value. This is *why* the calibration
   ranker pulls toward the wings — the fee headroom is biggest there, so
   small calibration biases survive fees.

The literature documents the favorite-longshot bias as largest in the
wings (highest implied probabilities for longshots, lowest for favorites).
The combination is favorable: biggest measurable bias × lowest fee cost.

---

## Why we model conservatively (taker on both sides)

Real execution may land as **maker** (resting limit at the calibration-
implied fair value), in which case fees are zero. The paper book assumes
taker on both sides as a conservative ceiling — if the strategy is
profitable assuming taker, it's strictly more profitable as maker.

When we transition to live, we'll measure actual maker fill rate. If it's
> 50%, we update the model.

---

## What this implies for strategy design

- **Mid-range bins (P = 0.4-0.6) are nearly untradeable.** Fees of 6-7%
  round-trip swallow most calibration-bias signals (which max out at
  ~3-5pp deviation). The Insurance book at 0.55-0.75 is at the upper edge
  of viability and uses `min_edge_pp = 3` (vs. lottery's 5).
- **Extreme bins (P = 0.85+ or P = 0.15-) are highly tradeable.** Low
  fees + large biases. The Lottery book lives here.
- **Cross-comparison rule:** when ranking candidates across price bins,
  always use `fee_adj_edge`, not raw deviation. The raw deviation favors
  the middle (where biases are statistically larger from lots of trades);
  fee adjustment correctly favors the wings.

---

## Implementation pointer

| File | Role |
|---|---|
| `src/prospector/strategies/pm_underwriting/calibration.py` | `KALSHI_ROUND_TRIP_FEE_FACTOR = 0.14`; `fee_adjusted_edge(price, actual_rate)` |
| `src/prospector/strategies/pm_underwriting/portfolio.py` | `fees_paid` calculation in `enter()`; deduction in `resolve()` |
| `src/prospector/strategies/pm_underwriting/scanner.py` | Calls `fee_adjusted_edge()` to filter candidates |

---

## Where it's applied

Every calibration calculation and entry on every PM Underwriting book.
Any future Kalshi-binary book inherits the same model.

---

## Trade-offs

**Why this works:** Fee math is deterministic; modeling it correctly is
free. Conservative-taker assumption is right for paper validation.

**What it gives up:**
- **Maker reality not modeled.** Once live, we'll likely beat the
  conservative cost model. That's good news, not a flaw.
- **No multi-tier fee modeling.** Kalshi may have volume tiers; we don't
  currently model those. Not material at our scale.
- **Doesn't cover spread.** The fee model is the fee; the spread
  (difference between bid and ask) is a separate execution cost. The
  scanner uses executable prices (yes_bid for sell_yes, 1 - no_bid for
  buy_yes) so spread is captured at the price level, not as a separate
  fee component.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-16 | Use round-trip taker as conservative model | Prefer to under-promise on backtest; maker fills are upside |
| 2026-04-25 | Doc consolidated into components/ | Was inline in calibration.py + methodology.md §2.7 |
