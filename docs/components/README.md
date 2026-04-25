# Components

> Reusable mechanisms that strategies apply as variants, overlays, or
> enhancements. One file per component; one canonical source of truth.

A component is a mechanism that's not itself a strategy but can be applied
to one. Equal-σ sizing isn't a strategy; it's the sizing rule the PM
underwriting books use. CLV instrumentation isn't a strategy; it's a
measurement layer applied to any paper book. MVT-rolling-threshold isn't a
strategy; it's a scanner-admission rule that any strategy with a candidate
queue could use.

## Why components are atomic

When a new candidate proposes "PM book + MVT overlay + CLV instrumentation
+ delta-hedging," you should be able to read three component docs and know
exactly what each piece does, what its math is, where it's already in use,
and what the trade-offs are. Without atomic component docs, that knowledge
ends up duplicated and inconsistent across strategy deep-dives.

## Documents

| File | What it covers | Status |
|---|---|---|
| [`calibration-curves.md`](calibration-curves.md) | PIT-pricing methodology, per-category bins, Wilson CIs, fee-adjusted edge, Go/no-go thresholds. | In production (PM books) |
| [`equal-sigma-sizing.md`](equal-sigma-sizing.md) | Risk-parity per-position sizing: `risk_budget = book_σ_target × NAV / (σ_i × √N_target)`. The σ-table model. | In production (PM books) |
| [`kelly-sizing.md`](kelly-sizing.md) | Fractional Kelly. Retired 2026-04-21 in favor of equal-σ. Kept as historical reference. | Retired |
| [`mvt-rolling-threshold.md`](mvt-rolling-threshold.md) | Marginal Value Theorem applied to scanner admission: don't take a slot below rolling-window average quality. | Designed (T2) |
| [`clv-instrumentation.md`](clv-instrumentation.md) | Closing-line-value measurement; faster edge signal than realized P&L for low-WR / high-payoff books. | In production (PM books) |
| [`hedging-overlay-perp.md`](hedging-overlay-perp.md) | Delta-hedge the crypto slice of a Kalshi book via Hyperliquid perps. | Scoped (PM Phase 5) |
| [`shadow-rejection-ledger.md`](shadow-rejection-ledger.md) | Append-only log of candidates rejected by structural screens; enables counterfactual replay. | In production (PM books) |
| [`fee-modeling-kalshi.md`](fee-modeling-kalshi.md) | Kalshi maker/taker fee math, the round-trip cost factor, and why it shapes which bins are tradeable. | In production |
| [`llm-altdata-extraction.md`](llm-altdata-extraction.md) | Pattern for using a local LLM as a feature generator over unstructured text (NWS AFDs, SEC filings). | Designed (T6) |

## Anatomy of a component doc

Every component doc has the same structure:

1. **Status** — In production / Designed / Retired, with date.
2. **What it does** — One-paragraph functional description.
3. **Math** — The exact formula, with all knobs named and defaults given.
4. **Implementation pointer** — The module(s) in `src/` that own it.
5. **Where it's applied** — Pointers to candidates that use it.
6. **Trade-offs** — Why it's the choice; what it gives up.
7. **Decision log** — When it shipped, when it was retired, why.

## When to create a new component doc

When a mechanism becomes applicable to two or more strategies (or one
strategy plus one ideation candidate), extract it into a component. Until
then, it can live inline in the strategy file — premature componentization
is a tax you pay forever.
