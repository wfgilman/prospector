---
id: 09
name: Kalshi × CME weather futures convergence
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 09: Kalshi × CME Weather Convergence

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 2 from fresh-eyes review; gated on employer-policy verification
- **Next move:** Verify CME commodity futures fall within employer's "no securities" policy (30-min conversation per [`charter/constraints.md`](../../charter/constraints.md) §1).

## Ideation

**Origin:** CME HDD/CDD (Heating/Cooling Degree Days) weather futures are
**CFTC-regulated commodity futures** — categorically not securities under
SEC rules. Same NOAA underlying as Kalshi weather contracts. Different
audience: CME participants are utilities, energy traders, airlines —
institutional, well-informed. Kalshi weather participants are retail.

Same underlying, totally different audience. Cleanest cross-market
convergence setup in the entire R&D queue *if employer policy permits
CFTC commodity futures*.

**Cross-domain origin:** Variance risk premium in weather (Bae/Jacobs/Jeon
AEA 2025) — weather implied variance exceeds realized; systematic sellers
of weather volatility earn premium.

**Axiomatic fit:**
- *Combinations* — weather derivatives (mature CME product) + Kalshi
  weather (retail) on identical NOAA underlying
- *Audience mismatch* — institutional CME vs. retail Kalshi; structurally
  durable
- *Operational* — daily cadence, persistent positions
- *Charter-conditional* — if commodity futures are out of scope per
  employer policy, this candidate is permanently `non-viable` regardless
  of edge mechanism

## Deep dive

(Empty until promoted.)

Constraint resolution required first.

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
| 2026-04-25 | Surfaced in fresh-eyes review as T8 (Tier 2) | CME = CFTC commodity; not a security; potential charter-expansion candidate |
| 2026-04-25 | Gated on employer-policy verification | Charter [`constraints.md`](../../charter/constraints.md) §1 doesn't explicitly authorize CFTC commodity futures; verification needed |

## Open questions

- Employer-policy scope — does "no securities" include CFTC commodities?
  (Strong prior: no, since these are categorically not securities, but
  policy may be broader.)
- CME contract specs — minimum contract size, margin requirements; can a
  $10K paper book size in?
- Settlement-date alignment — Kalshi weather contracts vs. CME monthly
  futures; basis-trade construction
- Liquidity: CME weather is real but thinner than crypto perps; sizing
  may be constrained

## Pointers

- Constraints (the gating doc): [`charter/constraints.md`](../../charter/constraints.md)
- Reference: CME Group "Weather Derivatives Overview"
