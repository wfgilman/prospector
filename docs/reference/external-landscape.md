# External Landscape

> What's happening in the world that affects this project's assumption set.
> Updated when material external developments are observed; consulted at
> the start of every fresh-eyes review.

This doc is the project's external-context memory. It captures
developments at venues (Kalshi, Hyperliquid, Polymarket), regulators
(CFTC, SEC), and adjacent product launches that materially change the
strategy surface or threat model.

---

## Active developments — verify before relying on

### HIP-4: Hyperliquid event perpetuals (Kalshi partnership)

| Field | Value |
|---|---|
| Submitted | 2025-09-16 |
| Co-author | John Wang (Kalshi head of crypto) |
| Testnet | 2026-02-02 (live) |
| Mainnet | TBD as of 2026-04-25 — verify before planning against |
| Partnership announced | March 2026 |
| Kalshi "Timeless" product launch | 2026-04-27 (~2 days after this doc was written) |

**Mechanics:** Event Perpetuals operate with 1× isolated margin only,
buyers deposit collateral equal to maximum potential loss. Trading
within price bands of 0.001 to 0.999. Resolution oracles post final
values during specified challenge windows.

**Documented arbitrage windows:** Settling a market from neutral (0.5)
to zero probability requires 50 minutes due to tick limitations. Creates
arb opportunities for informed traders.

**Why this matters for the project:**
1. The two platforms most central to prospector are merging their PM
   capabilities. The decision to close [#10](../rd/candidates/03-kalshi-hyperliquid-vol-surface.md)
   as standalone was based on 2-venue thinking; the 3-venue picture
   (Kalshi ↔ Polymarket ↔ HIP-4) is structurally different.
2. **3-axis audience mismatch** is bigger than the 2-axis story. See
   [candidate 07](../rd/candidates/07-three-venue-pm-divergence.md).
3. HIP-4 launches will be the smallest of the three venues at first —
   plenty of room for solo-operator multi-hour-divergence trades that
   are uneconomic for HFT desks.

**Sources:**
- https://cryptoslate.com (Kalshi exec submits HIP-4)
- https://hyperliquid.gitbook.io (HIP-3 / HIP-4 specs)
- Clear Street volume estimates (2026): Kalshi $96B, Polymarket $84B

### Polymarket (US-restricted)

Polymarket is a global crypto-native PM venue. Geofenced from US
residents but VPN workarounds are documented. Same event surface as
Kalshi for politics/sports/macro; pricing diverges 15-20% of events at
>5pp ([IMDEA arxiv:2508.03474]).

**Why this matters:** the Kalshi ↔ Polymarket cross-platform divergence
is publicly documented; HFT bots scalp the seconds-windows. Multi-hour
persistent gaps on lower-volume events fit our cadence and are largely
ignored. See [candidate 07](../rd/candidates/07-three-venue-pm-divergence.md).

### CFTC posture on prediction markets

Kalshi is CFTC-designated; the CFTC has approved an expanding range of
event contracts (sports, weather, elections after a court battle).
Posture for 2026 is permissive. Worth tracking if it shifts.

### Securities-vs-commodities scope

[`charter/constraints.md`](../charter/constraints.md) §1 flags this.
CME HDD/CDD weather futures and CME ag/energy futures are CFTC-regulated
**commodities**, not securities. Most likely the employer's "no
securities" policy permits CFTC commodity futures but the verification
hasn't happened — listed in [candidate 09](../rd/candidates/09-kalshi-cme-weather-convergence.md)
as a gating question.

---

## Recent product launches worth noting

| Date | Venue | Launch | Impact on project |
|---|---|---|---|
| 2025-10-13 | Hyperliquid | HIP-3 (builder-deployed perps) | Auction launches — see [candidate 13](../rd/candidates/13-hip3-first-day-spread.md). $1.43B OI by March 2026. |
| 2026-02-02 | Hyperliquid | HIP-4 testnet | See above |
| 2026-03 | Kalshi | Margin trading license secured | Enables larger position sizes; not yet a binding constraint |
| 2026-04-27 | Kalshi | "Timeless" product (specifics TBD) | Verify scope; may activate or deactivate candidates |

---

## Things to monitor

These aren't acted on now but should be checked at fresh-eyes reviews:

- **Kalshi position-limit changes.** The maker-side reflexivity
  candidate ([12](../rd/candidates/12-kalshi-maker-reflexivity.md)) is
  sensitive to per-user / per-market limits.
- **Kalshi fee-structure changes.** Maker is currently zero, taker
  `0.07 × P × (1-P)` per side. A change to maker fees would
  materially affect the calibration math.
- **Hyperliquid funding-rate methodology changes.** The hedging-overlay
  component ([`hedging-overlay-perp`](../components/hedging-overlay-perp.md))
  depends on the funding model.
- **Coinbase US-accessibility.** If a CFTC-regulated US perp venue
  emerges, our Hyperliquid dependency could be reconsidered.
- **TrevorJS Kalshi HF dataset updates.** We migrated their data once
  in April 2026; if they release a newer snapshot we could cross-check
  again.
- **Sibling-project shipments.** Notable additions to `kalshi-autoagent`,
  `crypto-copy-bot`, etc. that might overlap with our work — see
  [`sibling-projects.md`](sibling-projects.md).

---

## How to update this doc

When a material external development is observed:

1. Add it to the **Active developments** section if it's load-bearing
   for any candidate.
2. Add it to **Recent product launches** if it's interesting context
   but not actionable.
3. Update any candidate doc that's affected (frontmatter `last-update`
   + decision-log entry).
4. If the development invalidates a charter constraint or operational
   limit, surface to the user — charter changes need explicit pull-up.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Doc created in fresh-eyes-review reorg | HIP-4 / Kalshi-HL partnership was entirely missing from project docs; needed a single home for external context |
| 2026-04-25 | HIP-4 added with verify-before-rely caveat | Mainnet TBD; treat dates as approximate until verified |
