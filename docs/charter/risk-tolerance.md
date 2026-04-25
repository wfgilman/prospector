# Risk Tolerance

> What the book can absorb. NAV, drawdown, sizing, concentration, and
> scale targets at the portfolio level.

These limits define how the book is sized, how much of NAV any single
position or category can claim, and what counts as "an unacceptable
drawdown" vs. an expected variance event. They are book-level statements,
not per-strategy.

---

## NAV — paper books

| Book | Initial NAV | Sizing model |
|---|---|---|
| PM Underwriting · Lottery | $10,000 | Equal-σ ([component](../components/equal-sigma-sizing.md)) |
| PM Underwriting · Insurance | $10,000 | Equal-σ ([component](../components/equal-sigma-sizing.md)) |

Each paper book has its own NAV; the books are independent at the
portfolio-DB level. Realized P&L on one book does not affect the other.

---

## Per-position cap

`max_position_frac = 0.01` — no single position risks more than 1% of
NAV. This is the safety net against pathologically small σ estimates that
could otherwise let equal-σ sizing scale a position to absurd size.

The actual sizing typically lands well below 1% — equal-σ at default
parameters (book_σ_target=0.02, N_target=150) puts most positions in the
$10-$50 range on a $10K book. The 1% cap is a backstop, not a target.

---

## Per-event cap

`max_event_frac = 0.05` — total risk committed to positions sharing the
same `event_ticker` can't exceed 5% of NAV. Prevents stacking multiple
contracts on the same Kalshi event (different strikes, different sub-
markets) into an effective single risk exposure.

---

## Per-bin cap

`max_bin_frac = 0.15` — total risk for the (side, 5¢ price bin) cell
can't exceed 15% of NAV. The bin cap addresses fat-tail concentration in
high-kurtosis bins (95-100¢ sell_yes is the canonical extreme-tail bin).

This replaced the earlier `max_category_frac = 0.20` cap on 2026-04-21 —
finer grain, matches the σ-table key, makes the category cap redundant.

---

## Per-event / per-subseries / per-series counts

Diversity guardrails on top of the dollar caps:

| Rule | Default | Purpose |
|---|---|---|
| `max_positions_per_event = 1` | Strict | No multiple positions on the same event |
| `max_positions_per_subseries = 1` | Strict | Subseries = event_ticker minus trailing segment (one position per game/round) |
| `max_positions_per_series = 3` | Loose | Series = series_ticker (e.g. KXNFL); cap concentrated weekly stacking |

Counts are derivative — they catch correlated stacking that the dollar
caps don't. They're calibrated to the empirical rate of correlated events
(NBA prop tickers fragment the same game into many sub-markets).

---

## Daily throughput cap

`max_trades_per_day = 20` (lottery book) — matches the capital-constrained
sim's best slot and the empirical rate at which the scanner produces
high-edge candidates. The lottery book pins at this cap most days.

The insurance book uses the same default but has more headroom because the
0.55-0.75 entry-price band produces fewer candidates.

---

## Book-level σ target

`book_σ_target = 0.02` — target daily σ of the book as a fraction of NAV.
Under equal-σ sizing with `N_target = 150` independent positions, the
expected daily σ is 2% of NAV.

Empirical σ may differ from target because:
- Per-bet σ is estimated from walk-forward (~80K trades) and may not
  generalize perfectly
- Independence assumption is approximate (correlated stacking caps help
  but don't fully solve)
- The book is not at steady state — typical paper book runs at ~30-50
  positions, not 150, so realized σ is below target

This is documented; it's not a defect. The system is designed to converge
to target σ as it fills toward N_target.

---

## Drawdown tolerance — implicit, not formalized

The project does not currently have an explicit max-drawdown circuit
breaker on the paper books. The implicit tolerance is "≤20% drawdown is
within expected variance for a 9:1 lottery-payoff book at our N." A
drawdown beyond 20% would prompt a pause-and-investigate response (is the
calibration broken? is the σ table stale? has a regime shift occurred?).

This is a known gap. A formal kill-switch belongs in the move from paper
to live (Phase 4), where actual capital is on the line. For paper, the
worst case is "the book ends up at $0" which is informative but not
financially destructive.

When Phase 4 begins, this section gets a real number with a kill mechanism.

---

## Live-capital scale targets — not yet applicable

The project has not deployed live capital. When it does (Phase 4), the
framework is:

- Initial deployment: 5% of intended NAV
- Scale up over weeks based on realized P&L tracking the paper-book
  prediction within ±X pp
- Position sizing scales linearly with live NAV
- Hard cap on initial deployment: TBD with user before Phase 4

The "intended NAV" itself is a question for the user — this is not an
agent decision.

---

## What's not in this doc (yet)

- **Cross-book correlation limits** — when multiple books trade the same
  underlying surface (PM Lottery + PM Insurance share calibration), correlated
  drawdowns are possible. Not currently modeled. Worth surfacing if both
  books deploy live.
- **Tail-event procedures** — what to do if the Kalshi platform pauses
  resolutions, or Hyperliquid de-pegs, or USDC depegs. Not currently
  documented. Worth a future section.
- **Capital-deployment authority** — clear delineation of which actions
  require user approval at which capital level. Implicit in
  [`constraints.md`](constraints.md) §4 ("no live trading without explicit
  approval") but not granular.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-21 | Equal-σ sizing replaces fractional Kelly | σ varies 30× across bins; Kelly under-sized the book by 4-14× relative to confidence target |
| 2026-04-21 | `max_bin_frac=0.15` replaces `max_category_frac=0.20` | Finer grain, matches σ-table key, captures tail concentration |
| 2026-04-25 | Risk-tolerance consolidated into charter | Previously distributed across portfolio.py docstring + sizing-reevaluation doc + plan.md |
