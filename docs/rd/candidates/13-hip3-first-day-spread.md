---
id: 13
name: HIP-3 first-day-after-auction spread
status: ideation
verdict: pending
last-update: 2026-04-27
related-components: []
---

# Candidate 13: HIP-3 First-Day-After-Auction Spread

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 3 from fresh-eyes review
- **Next move:** Monitor HIP-3 auction outcomes; revisit if a clearly-tradeable spread pattern emerges.

## Ideation

**Origin:** Hyperliquid HIP-3 enables anyone with ≥500K HYPE staked to
launch their own perps markets via Dutch auction. Auction price declines
over time; the first bid sets the floor. Post-launch first-day trading
typically shows wide bid-ask spreads that narrow as price discovery
completes.

**Small-scale arb:** Bid the auction floor; exit during first-day
liquidity. Pre-competitive territory because few solo operators stake
500K HYPE just to hunt these spreads.

**Why-now:** HIP-3 launched 2025-10-13. By January 2026, builder-deployed
markets generated > $790M in open interest; by 2026-03-24, **$1.43B OI
and >35% of all Hyperliquid volume**. Throughput is real and growing —
the spread thesis has live volume backing it.

**Axiomatic fit:**
- *Combinations* — IPO-pop equity arb (mature) + crypto perp launch
  mechanics (novel)
- *Small-player* — solo operator may be able to participate without
  staking 500K HYPE (just trade the post-launch market, not deploy it)
- *Operational* — lumpy throughput (auctions are event-driven, not
  continuous); each event is fast (first day = 24h of trading)

## Deep dive

(Empty until promoted.)

## Statistical examination

(Empty.)

## Backtest

(Empty — short history limits historical analysis.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced as T11 in fresh-eyes review (Tier 3) | Pre-competitive timing; throughput growing |
| 2026-04-25 | Tier 3 — not urgent, novel | Worth monitoring but not blocking other work |
| 2026-04-27 | HIP-3 OI/volume-share fact added ($1.43B / >35% by 2026-03-24) | Throughput backing strengthens the trade; still Tier 3 priority |

## Open questions

- Participation mechanics — can a non-deployer trade auction-launched
  markets, or is it deployer-only initially?
- Auction-floor-vs-first-day-spread historical distribution — needs
  measurement before any sizing
- Settlement asymmetries — see HIP-3 docs §50-min tick-limited settlement

## Pointers

- External landscape on HIP-3/HIP-4: [`reference/external-landscape.md`](../../reference/external-landscape.md)
