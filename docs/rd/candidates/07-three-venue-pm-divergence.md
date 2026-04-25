---
id: 07
name: Three-venue prediction-market divergence
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 07: Three-Venue PM Divergence

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — gated on HIP-4 mainnet (testnet live since Feb 2026; mainnet TBD)
- **Next move:** Verify HIP-4 mainnet timeline; build Polymarket data layer (~2 weeks) so the third venue plugs in when ready.

## Ideation

**Origin:** Kalshi ↔ Polymarket cross-venue PM arb is publicly documented
(15-20% of events diverge >5pp; $40M+ extracted from Polymarket alone in
one year per IMDEA arxiv:2508.03474). When HIP-4 (Hyperliquid event
perpetuals, co-developed with Kalshi) goes mainnet, three venues will
list overlapping events with three non-overlapping participant pools:
US retail (Kalshi), global crypto (Polymarket), Hyperliquid-natives
(HIP-4).

**Three-axis audience mismatch is structurally larger than two-axis.**

**The small-player edge:** Reported HFT bots scalp persistent gaps in
seconds. **Multi-hour gaps on lower-volume events** are inaccessible to
desks (too thin to size into) but perfect at our cadence. Textbook
small-player axiom (axiom 2).

**Axiomatic fit:**
- *Combinations* — Hausch-Ziemba parimutuel cross-track arb (1980s) +
  three-venue PM substrate
- *Small-player* — gaps invisible to desks but tradeable for one operator
- *Operational* — 15-min cadence works for persistent gaps; thousands of
  events/year across the three venues

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
| 2026-04-25 | Surfaced in fresh-eyes review as T5 (Tier 2) | Audience-mismatch goes 3-axis when HIP-4 ships |
| 2026-04-25 | HIP-4 timeline noted in [`reference/external-landscape.md`](../../reference/external-landscape.md) | Testnet Feb 2026; mainnet TBD |
| 2026-04-25 | Recommendation: build Polymarket data layer now, HIP-4 plugs in later | ~2 weeks data work; pre-positions for the 3-venue trade |

## Open questions

- Polymarket access mechanics for US-resident operator
- HIP-4 event perpetuals microstructure (1× isolated margin, 0.001-0.999
  bands, 50-min tick-limited settlement) — how does that interact with
  Kalshi-style binary pricing?
- Event-mapping across venues — same event, different ticker schemas
- Settlement consistency across the three venues (oracle vs. exchange-defined)

## Pointers

- HIP-4 + landscape: [`reference/external-landscape.md`](../../reference/external-landscape.md)
- Operational limits: [`charter/operational-limits.md`](../../charter/operational-limits.md)
