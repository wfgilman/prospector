---
id: 10
name: Slow book — replay shadow-ledger 28d+ rejections
status: ideation
verdict: pending
last-update: 2026-04-25
related-components:
  - shadow-rejection-ledger
  - calibration-curves
  - equal-sigma-sizing
---

# Candidate 10: Slow Book

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 2 from fresh-eyes review
- **Next move:** Build the shadow-ledger replay script (~150 LOC) to validate empirically before committing to a third paper book. Surfaces the counterfactual "what would the book look like if we hadn't applied the 28-day expiry screen?"

## Ideation

**Origin:** The PM Underwriting books reject candidates with `close_time -
now > 28 days` to keep paper validation focused on the near-term horizon.
These rejected candidates are logged to the [`shadow-rejection-ledger`](../../components/shadow-rejection-ledger.md)
component but never traded. Many are politics, season-long sports,
commodity, award markets — long-duration, thinner, more inefficient.

Long-duration markets have **different microstructure** — thinner books,
more retail mispricing, less attention from sharps. The current books
explicitly skip this universe (correct for paper validation, wasteful
long-term). A third paper book would replay the rejected candidates at
weekly cadence, with different sizing (higher per-position because
rebalance cadence is weekly, not event-driven).

**Axiomatic fit:**
- *Different scale, same calibration* (axiom 3) — same mechanism PM
  exploits, different time horizon
- *Small-player* — long-duration markets are too capital-locking for
  desks; family-income operation can hold months-long positions
- *Insurance float* (Buffett analogue) — capital committed to long-
  duration positions is "float" earning calibration premium for the
  duration; sizing the slow book is about float-opportunity-cost, not
  just per-trade variance

## Deep dive

(Empty until promoted. Sketch in fresh-eyes review T7.)

## Statistical examination

The shadow ledger is already collecting the universe. The replay script
is the empirical test:

1. Read the shadow parquet
2. Instantiate `ShadowPaperPortfolio` with same calibration + σ-table as live
3. Walk rejection rows in order
4. Simulate entries and resolutions (when each `close_time` fires)
5. Report shadow-book NAV trajectory next to live-book

If the counterfactual replay shows the long-dated rejections aggregate to
a positive book, that's empirical justification to build the actual slow
book.

## Backtest

The replay IS the backtest for this candidate (the universe is already
being recorded in shadow form).

## Paper portfolio

(Empty until promoted.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-23 | Shadow ledger added with 28-day expiry screen ([component](../../components/shadow-rejection-ledger.md)) | The screen was for paper validation; the ledger preserves the rejected universe for later use |
| 2026-04-25 | Surfaced as candidate T7 in fresh-eyes review | Long-duration microstructure is plausibly thinner / more inefficient |
| 2026-04-25 | Doc created in rd/candidates/ as ideation | Empirical justification (replay) needed before promotion |

## Open questions

- Replay script scope — full simulation with concurrent capital tracking,
  or simpler "flat per-trade" first pass?
- Sizing for the slow book — same equal-σ math? Adjust `N_target` for
  the lower expected throughput?
- Resolution timing — 6+ month positions resolve outside the typical
  paper validation horizon; how to evaluate intermediate progress?
- Three concurrent books would push API quota; verify Kalshi rate limits
  are still comfortable.

## Pointers

- Source component: [`shadow-rejection-ledger`](../../components/shadow-rejection-ledger.md)
- Sister candidates: [`01-pm-underwriting-lottery.md`](01-pm-underwriting-lottery.md), [`04-pm-underwriting-insurance.md`](04-pm-underwriting-insurance.md)
