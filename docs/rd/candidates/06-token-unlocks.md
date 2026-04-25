---
id: 06
name: Token unlock / vesting cliff calendar
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 06: Token Unlocks

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — borderline operational viability; queued as backup R&D track
- **Next move:** Promote to deep-dive only after weather ensemble (#05) ships or stalls.

## Ideation

**Origin:** Token supply schedules are public. Unlocks of 1-10% of
circulating supply typically depress price in a predictable window (−30
to +14 days around unlock date). LLM reads project communications,
investor commitments (lockup extensions, OTC deals) to classify whether
a given unlock will mark-to-market or be absorbed.

**Cross-domain origin:** Equity insider-lockup expiry post-IPO. Established
finance literature documents significant underperformance in the 30 days
after lockup expiry. Crypto should share this shape but has more surface
area (hundreds of tokens, weekly events).

**Axiomatic fit:**
- *Combinations* — equity post-lockup underperformance (well-documented) +
  crypto unlocks + LLM as classifier on project narrative
- *LLM categorical role* — reading Discord, Medium posts, team tweets to
  classify "routine dump" vs. "team has OTC'd" — natural language task
- *Operational* — weekly-to-daily cadence, ~120-360 events/year. Borderline
  on throughput per [`charter/operational-limits.md`](../../charter/operational-limits.md);
  needs meaningful edge per event.

**Why borderline:** Throughput ~120-360/yr puts it in the 50-500 band
(borderline structural-arb territory). Edge per event needs to be
meaningful (>1%) to compound. Hyperliquid lists ~130 perps which covers
most large-cap unlocks but not all mid/small-caps.

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
| 2026-04-15 | Logged in original `strategy-families.md` as #2 | Strong cross-domain analogue + LLM-fit |
| 2026-04-23 | Operational triage: borderline throughput | Edge-per-event must be meaningful |
| 2026-04-25 | Queued as backup R&D track behind #05 weather ensemble | Throughput borderline; weather has cleaner profile |
| 2026-04-25 | Doc consolidated into rd/candidates/ | Reorg |

## Open questions

- Unlock data source: Token Unlocks API, CryptoRank, on-chain decoders?
- Universe: top-200 tokens? Hyperliquid-perp-listed only? Both?
- Holding window: -30 to +14 days is the literature; tune to crypto?
- Event-clustering — multiple unlocks same week — how to size?

## Pointers

- Operational limits: [`charter/operational-limits.md`](../../charter/operational-limits.md)
