---
id: 12
name: Kalshi maker-side reflexivity trade
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 12: Kalshi Maker-Side Reflexivity

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 3 from fresh-eyes review
- **Next move:** No immediate action; flagged as a small-player-axiom-pure example for later attention.

## Ideation

**Origin:** When large flow compresses Kalshi orderbook depth toward
position limits, the maker side earns a liquidity premium (the resting
limit-order side widens on the squeeze, then mean-reverts). Detectable by
watching orderbook depth + position-limit proximity.

**Why this is small-player-pure:** Desks blow through Kalshi position
limits instantly (size into the limit, then have to cross the book to
keep going). They can't *be* the marker on the squeezed side. Solo
operators who are well below position limits can be.

**Axiomatic fit:**
- *Small-player axiom directly* (axiom 2) — explicit category of arb
  that exists only at small scales
- *Operational* — requires live orderbook capture (which we don't
  routinely do); cadence is event-driven; throughput depends on flow
- *Charter-conditional* — needs L2 orderbook capture going forward (no
  history available per [`platform/data-pipeline.md`](../../platform/data-pipeline.md))

## Deep dive

(Empty until promoted.)

## Statistical examination

(Empty.)

## Backtest

(Empty.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced as T10 in fresh-eyes review (Tier 3) | Pure small-player axiom; no obvious downside to logging it |
| 2026-04-25 | Tier 3 — needs L2 orderbook capture | Not built; would be a deliberate component investment |

## Open questions

- L2 orderbook capture cadence — 1s? 5s? Storage cost grows quickly
- Position-limit awareness — how to query Kalshi's per-user / per-market
  caps in real time?
- Stoikov MM model fit — see literature for mathematical framing

## Pointers

- L2 orderbook caveat: [`platform/data-pipeline.md`](../../platform/data-pipeline.md) §retention model
- Reference: HangukQuant "Digital Option Market Making on Prediction Markets"
- Reference: Stoikov market-making (general)
