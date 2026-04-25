# Equal-σ Sizing (Risk Parity)

> Per-position risk budget set so every position contributes equally to
> book-level σ. Replaced fractional Kelly on 2026-04-21.

**Status:** In production. Both PM books use this sizer.

---

## What it does

Given a candidate trade in stratum `i` (defined by category, side, 5¢
price bin), compute the dollar risk to commit such that:

- Per-position σ contribution to the book is uniform across positions
- Aggregate book σ converges to a target as N positions accumulate
- A pathologically small σ estimate doesn't blow through a per-position cap

---

## Math

```
risk_budget_i = book_σ_target × NAV / (σ_i × √N_target)
              clipped by max_position_frac × NAV
```

where:
- `book_σ_target = 0.02` — target daily book σ as fraction of NAV (default)
- `N_target = 150` — target steady-state count of independent positions
- `σ_i` — empirical per-bet σ (`pnl / risk_budget`) for stratum `i`
- `max_position_frac = 0.01` — per-position safety net

### Why this gives uniform σ contribution

Under independent bets with risk budget `r_i` and per-bet σ `σ_i`, the
position's σ contribution is `r_i × σ_i`. Setting:

```
r_i = K / σ_i    (where K is a constant for all positions)
```

makes each position contribute `K` to total σ. Aggregate book σ for N
independent positions is `K × √N`. Setting that to `book_σ_target × NAV`:

```
K = book_σ_target × NAV / √N_target
r_i = K / σ_i = book_σ_target × NAV / (σ_i × √N_target)
```

QED. The position cap clip is a safety net for σ estimates so small they'd
blow through any reasonable risk budget.

### Why N_target = 150

From the walk-forward test set (`scripts/return_distribution.py`):

| Stratum | Per-bet Sharpe | N for P(book positive) ≥ 90% |
|---|---|---|
| All trades (edge ≥ 2pp) | 0.057 | 511 |
| High-edge slice (edge ≥ 5pp) | 0.110 | 136 |

The formula is `N ≥ (z_α / Sharpe)²` with z₀.₉₀ = 1.28. At the high-edge
Sharpe of 0.110, N=136 gives 90% confidence. We round up to 150 for
margin.

The Phase 3 book pre-equal-σ was running ~36 concurrent positions —
between 4× and 14× under-sized relative to the LLN-required count.

---

## The σ-table

`σ_i` is looked up from `data/calibration/sigma_table.json`, built offline
by `scripts/compute_sigma_table.py` from the walk-forward test set.

Lookup priority (3 levels):
1. Exact `(category, side, 5¢ bin)` — most accurate
2. Pooled `(category, side)` — fallback for thin bins
3. Aggregate (single global σ) — last-resort fallback

A candidate with no σ at any level is **rejected at entry** — a signal we
can't size is a signal we don't trust.

### Shrinkage

Narrow bins (n < 200) are shrunk toward the pooled (category, side) σ
using James-Stein-style shrinkage with pseudo-count `n0 = 200`:

```
σ²_shrunk = (n × σ²_raw + n0 × σ²_pool) / (n + n0)
```

This handles the small-bin instability without throwing away the bin's
specific signal entirely.

### Per-bin Sharpe dispersion

σ varies ~30× across bins. Examples:

| Side / bin | σ | Sharpe |
|---|---|---|
| sports sell_yes 95-100¢ | 22.4 | 0.285 |
| sports sell_yes 85-90¢ | (~6.7) | 0.180 |
| crypto sell_yes 10-15¢ | 0.36 | 0.128 |

Equal-σ correctly sizes a low-σ bin (crypto sell_yes 10-15¢) ~3× larger
than the default and a high-σ bin (sports sell_yes 95-100¢) ~20× smaller.
Kelly ignored this dispersion — it sized from `edge / P` alone.

---

## Implementation pointer

| File | Role |
|---|---|
| `src/prospector/strategies/pm_underwriting/sizing.py` | `SigmaTable`, `SigmaEntry`, `load_sigma_table()`, `MissingSigma` |
| `src/prospector/strategies/pm_underwriting/portfolio.py` | `PaperPortfolio.size_position(sigma_i)` |
| `scripts/compute_sigma_table.py` | Offline σ-table builder |

The sizer is a single function: `size_position(sigma_i) → risk_budget`.
The runner ranks candidates by `edge_pp / σ_bin` (bin-level Sharpe proxy)
before applying the sizer.

---

## Where it's applied

- **PM Underwriting · Lottery** — full price range
- **PM Underwriting · Insurance** — 0.55-0.75 band

Both use the same default knobs (`book_σ_target=0.02`, `N_target=150`)
and share the σ-table.

---

## Trade-offs

**Why equal-σ over Kelly:**
- Kelly's `f* = edge / P` assumes a known two-point distribution. Real
  per-bet σ varies 30× across bins; Kelly ignores this.
- Risk parity is the natural sizing rule when you have a σ estimate per
  position and you care about aggregate-level risk rather than single-bet
  geometric growth.
- The book's Sharpe-optimal position count is the N that satisfies
  `√N × Sharpe ≥ z_α`. Equal-σ sizing is what lets "N positions" be a
  meaningful target.

**What equal-σ gives up:**
- **σ estimates have CIs.** The shrinkage helps narrow bins but doesn't
  fix the fundamental issue that we're forecasting σ. A robust
  implementation might use the lower CI bound rather than the point
  estimate.
- **Gaussian tail assumption is wrong.** The 95-100¢ sell_yes bin has
  Sharpe 0.285 but pathological kurtosis — one bad cluster of losses
  blows through the Gaussian 95% CI. A VaR/CVaR-based sizing rule would
  be sharper. The per-bin cap (`max_bin_frac=0.15`) bounds total
  allocation to that bin as a workaround.
- **Independence is fiction.** Same-event parlay legs are correlated;
  the count caps (`max_positions_per_event = 1`, etc.) are the main tool
  against this.

**What it does NOT solve:**
- Calibration accuracy. If the calibration curve is wrong, equal-σ
  sizing loses money efficiently.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-21 | Equal-σ replaces fractional Kelly outright (no A/B) | Kelly has no academic justification under observed σ-dispersion; A/B would only delay correction. See `sizing-reevaluation.md` (now archived). |
| 2026-04-21 | `book_σ_target=0.02`, `N_target=150` | Walk-forward Sharpe 0.110 high-edge slice ⇒ N=136 for 90% confidence; rounded to 150 for margin |
| 2026-04-21 | Reject candidates with no σ at any fallback level | A signal we can't size is a signal we don't trust |
| 2026-04-21 | Bin-level Sharpe proxy `edge_pp / σ_bin` as ranker | Concentrates fills in the best risk-adjusted slices |
| 2026-04-21 | Shrinkage `n0=200` for narrow bins | Handles thin-bin instability without losing per-bin signal |
| 2026-04-25 | Doc consolidated into components/ | Was inline in implementation/methodology.md §3.4 + sizing-reevaluation.md |
