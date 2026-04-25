---
id: 04
name: PM Underwriting · Insurance
status: paper-portfolio
verdict: pending
last-update: 2026-04-25
related-components:
  - calibration-curves
  - equal-sigma-sizing
  - clv-instrumentation
  - shadow-rejection-ledger
  - fee-modeling-kalshi
---

# Candidate 04: PM Underwriting · Insurance

## Status snapshot

- **Stage:** paper-portfolio (daemon loaded 2026-04-25; first tick fires ~07:55 PT 2026-04-25)
- **Verdict:** pending — too new for empirical assessment
- **Next move:** Wait 30 days for paper signal; assess against pre-committed kill criteria around 2026-05-25.

## Ideation

**Origin:** The PM Underwriting deep-dive prospectus framed the strategy
as "writing many small policies for premium" — the insurance metaphor.
The lottery book's edge ranker (`edge / σ`) systematically pulls to 85-99¢
extreme-price bins because σ ramps up faster than edge in the wings, and
the per-position cap is binding. The realized payoff is **9:1 lottery
tickets**, not insurance policies.

The insurance thesis isn't wrong — it's just been measuring the wrong
slice. The actuarial premium (small edge × many favorites at moderate
prices) lives in the **0.55-0.75 implied** band where σ is low and WR is
high. Same calibration surface, different scope.

This candidate tests the original prospectus *for the right bins*.

**Surfaced in fresh-eyes review (2026-04-24)** as candidate T1.

**Axiomatic fit:**
- *Same scale, different framing* (axiom 3) — same calibration surface
  the lottery book trades; different slice produces opposite payoff
  shape (high WR, small wins, low variance)
- *Methodology discipline* (axiom 6) — separates the two payoff shapes
  empirically rather than mixing them in one book

## Deep dive

### Mechanism

Identical to [`01-pm-underwriting-lottery.md`](01-pm-underwriting-lottery.md):
calibration curves, equal-σ sizing, scanner that ranks by `edge / σ`,
constraint hierarchy. **Only difference:** entry-price band scoped to
0.55-0.75 via `RunnerConfig.entry_price_min/max`.

The filter is applied after σ-rank, before portfolio entry. Candidates
outside the band are dropped regardless of edge magnitude.

### Why this band

From Phase 1 calibration (per-category breakdown in [`01-pm-underwriting-lottery.md`](01-pm-underwriting-lottery.md) §statistical-examination):
- Sports has 16/20 signal bins concentrated at mid-to-high implied
- Mid-bin edges are smaller than tail edges but more numerous
- Win rates in this band are typically 60-75% (the "favorite" side of
  insurance bets)
- Per-bin σ in this band is significantly lower than at extremes

Raising `min_edge_pp` to 5pp on the lottery book already concentrated it
in the high-edge bins (which are extremes). The insurance variant uses
`min_edge_pp = 3` because mid-bin edges are smaller; the band filter is
the primary scope mechanism, not the edge floor.

### Live config

| Knob | Value |
|---|---|
| Initial NAV | $10,000 |
| Sizing | Equal-σ (shared σ-table with lottery) |
| `book_σ_target` | 0.02 |
| `N_target` | 150 |
| `max_position_frac` | 0.01 |
| `max_event_frac` | 0.05 |
| `max_bin_frac` | 0.15 |
| `max_trades_per_day` | 20 |
| `min_edge_pp` | 3.0 |
| `entry_price_min` | 0.55 |
| `entry_price_max` | 0.75 |
| `max_days_to_close` | 28 |
| Categories | sports, crypto |

Calibration store and σ-table are **shared with the lottery book**. Only
portfolio DB and launchd plist differ:

- DB: `data/paper/pm_underwriting_insurance/portfolio.db`
- Wrapper: `scripts/paper_trade_insurance_launchd.sh`
- Plist: `com.prospector.paper-trade-insurance`

Both books visible side-by-side on the dashboard's Compare tab; per-book
detail in their own tabs ([dashboard](../../platform/dashboard.md)).

## Statistical examination

(Empty until paper data accumulates. The pre-committed kill criteria
below act as the live equivalent of stat-exam pass criteria — but the
formal stat-exam is shipped via the existing PM walk-forward results
[`01-pm-underwriting-lottery.md` §backtest](01-pm-underwriting-lottery.md))
applied to the constrained slice.)

## Backtest

Walk-forward Sharpe-by-bin slice in [`01-pm-underwriting-lottery.md` §3.5
return distribution](01-pm-underwriting-lottery.md) shows the 0.55-0.75
band has aggregate Sharpe in the 0.05-0.10 range with WR > 60% — modest
but consistent. Throughput in this band is large enough (multiple
hundreds of qualifying candidates/day) that LLN convergence is feasible.

Formal walk-forward simulation **on the band-constrained universe** is a
TODO if/when this candidate's verdict turns ambiguous in paper.

## Paper portfolio

### Live state (2026-04-25)

Daemon loaded; first tick fires ~07:55 PT 2026-04-25 (15-min cadence,
`RunAtLoad: false`). DB doesn't exist yet — will be created by the first
tick. Dashboard renders an "awaiting first tick" placeholder card in the
Compare tab.

### Pre-committed kill criteria

Stop the insurance book if any of:

1. **30-day paper Sharpe < 0.5** after fees
2. **Beat-line rate (CLV-based) < 50%** over 30 days
3. **Realized hit rate diverges > 5pp** from calibration prediction on
   the entered bins

If killed: `launchctl unload ~/Library/LaunchAgents/com.prospector.paper-trade-insurance.plist`.
Lottery book continues unaffected.

If passed: candidate to Phase 4 (live small) gated on user authorization
per [`charter/constraints.md`](../../charter/constraints.md) §4.

## Live trading

Not reached. Phase 4 gated on:
- 30 days of paper meeting kill criteria
- User authorization
- Decision on whether the lottery + insurance books co-deploy at small
  scale or one is selected as the primary

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced in fresh-eyes review as T1 | Insurance framing was the prospectus intent; lottery book selects the wrong bins for that framing |
| 2026-04-25 | Implementation chosen as parametrize-existing-runner (Option A) | Minimum-impact: `RunnerConfig.entry_price_min/max` knob; shared calibration + σ-table; only DB and launchd plist differ |
| 2026-04-25 | `min_edge_pp = 3` (vs. lottery's 5) | Mid-bin edges are smaller per Phase 1 results; will tune from realized data |
| 2026-04-25 | Daemon loaded; first tick scheduled | Plist installed via launchctl bootstrap; awaiting 15-min interval |
| 2026-04-25 | Dashboard wired with Compare tab | Side-by-side stat cards + overlaid P&L chart + KPI delta table |

## What this validates

Whether the original prospectus thesis was right *for the right bins*.

- **If the insurance book outperforms its kill criteria** while the
  lottery book trades the same calibration surface at extreme prices,
  both books co-exist and the strategy family has two clean expressions.
- **If the insurance book fails its kill criteria,** the calibration
  edge is genuinely concentrated at extremes, and the lottery framing
  IS the strategy.

Either outcome is informative.

## Pointers

- Sister candidate (full prospectus content): [`01-pm-underwriting-lottery.md`](01-pm-underwriting-lottery.md)
- Calibration component: [`components/calibration-curves.md`](../../components/calibration-curves.md)
- Sizing component: [`components/equal-sigma-sizing.md`](../../components/equal-sigma-sizing.md)
- Daemon mechanics: [`platform/paper-trade-daemon.md`](../../platform/paper-trade-daemon.md)
- Dashboard with comparison view: [`platform/dashboard.md`](../../platform/dashboard.md)
