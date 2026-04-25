# Kelly Sizing (Retired)

> Fractional-Kelly per-position sizing. Used in Phase 3 paper book launch
> 2026-04-20; retired 2026-04-21 in favor of [equal-σ sizing](equal-sigma-sizing.md).

**Status:** Retired. Kept for reference and historical context.

---

## What it did

Per Kelly (1956), for a binary outcome with known true probability `p`
and market price `p_m`:

```
f*_sell_yes = (p_m - p_true) / (1 - p_m)    if p_true < p_m (sell yes)
f*_buy_yes  = (p_true - p_m) / (p_m)        if p_true > p_m (buy yes)
```

We applied **quarter-Kelly** (`f*/4`) to account for calibration uncertainty,
clipped by `max_position_frac × NAV`, plus separate per-event and
per-category caps.

The "true probability" was the calibration-curve actual_rate for the
matched bin.

---

## Why we retired it

The empirical per-bet σ measurement (`scripts/return_distribution.py`,
2026-04-21) showed:

- **Per-bet σ varies 30× across bins.** Crypto sell_yes 10-15¢ has σ=0.36.
  Sports sell_yes 95-100¢ has σ=22.4.
- **Kelly ignores this.** It sizes from `edge` and implied `P` alone, so a
  high-σ tail bin gets the same budget as a low-σ compressed bin with the
  same edge.
- **Phase 3 was 4-14× under-sized.** Per-bet Sharpe of 0.057 (all trades)
  to 0.110 (high-edge slice) implies N = 136-511 positions for 90%
  book-level confidence. Phase 3 was running ~36.

Equal-σ sizing is the natural generalization of Kelly when per-position σ
varies: each position contributes the same marginal risk, scaled by its
σ. See [`equal-sigma-sizing.md`](equal-sigma-sizing.md) for the math.

---

## What's preserved from the Kelly era

- **Fractional sizing principle.** Both Kelly and equal-σ are
  fractional-of-NAV sizers; the daily NAV anchoring + per-position cap
  pattern carried over.
- **Per-event and per-bin caps.** These existed in the Kelly era as
  correlation guardrails; they're load-bearing under equal-σ too.
- **Bin-level signal lookup.** Calibration store + per-bin lookup → edge
  → side, identical between Kelly and equal-σ.

---

## When Kelly might be reconsidered

In principle, Kelly is optimal for **single-bet geometric growth** when σ
is known and bets are independent. If a future strategy:

- Has a single concentrated bet at a time (no N-position aggregate)
- Has a well-measured σ at the per-bet level
- Cares about long-run growth rate rather than book-level σ control

…then Kelly (or fractional Kelly) might be the right sizer for that
strategy. PM Underwriting doesn't fit any of these criteria — many
positions, σ varies 30×, we want book-σ control.

---

## Implementation pointer (historical)

The Kelly sizer was previously in `src/prospector/strategies/pm_underwriting/portfolio.py`
as `size_position(edge_pp, kelly_fraction=0.25)`. Replaced by
`size_position(sigma_i)` on 2026-04-21. The Phase 3 Kelly book is
archived at `data/paper/portfolio-kelly-archive.db`.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-20 | Phase 3 launches on quarter-Kelly | Standard fractional Kelly with calibration-derived edge |
| 2026-04-21 | Retired in favor of equal-σ | Per-bet σ dispersion makes Kelly the wrong rule; A/B would only delay correction |
| 2026-04-21 | Phase 3 Kelly book archived; fresh book launched on equal-σ | Clean slate; no mixed-sizing in the realized-return record |
| 2026-04-25 | Doc moved to components/ as historical reference | Sprawl reorg |
