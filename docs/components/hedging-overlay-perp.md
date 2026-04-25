# Perpetual-Futures Hedging Overlay

> Delta-hedge the crypto slice of a Kalshi position via Hyperliquid
> perpetual futures. Strips spot-direction P&L; isolates calibration edge.

**Status:** Scoped (2026-04-22). Not yet implemented. Triggered by the
absorbed [#10 vol surface](../rd/candidates/03-kalshi-hyperliquid-vol-surface.md)
finding D1.

---

## What it does

For a Kalshi position whose payoff depends on a crypto reference price
(BTC/ETH range contracts in `KXBTC-*` / `KXETH-*` events), compute the
position's delta with respect to spot and short/long an offsetting amount
of `BTC_PERP` / `ETH_PERP` on Hyperliquid. Re-hedge as the position's
delta drifts.

Result: the spot-directional component of the Kalshi P&L is stripped;
what's left is the calibration-edge component the strategy actually wants
to capture, plus hedging cost.

---

## Math

For a Kalshi range-bucket position priced at `p_i` for bucket `[x_i, x_{i+1})`,
the position's payoff at expiry is:

```
payoff(S_T) = contracts × 1[S_T ∈ [x_i, x_{i+1})] × (1 - p_i)    (sell_yes)
            = contracts × 1[S_T ∈ [x_i, x_{i+1})] × (p_i - 1)    (buy_yes loss path)
```

(roughly — the binary nature simplifies but the position-level Greeks
need the discrete-density treatment.)

**Delta** is the derivative of mark-to-market w.r.t. spot:

```
Δ = ∂(portfolio_payoff) / ∂S
```

Computed via finite difference on bucket prices using the Kalshi-implied
distribution + linearly-interpolated CDF.

**Hedge size** is then `−Δ` units of `BTC_PERP` (or `ETH_PERP`),
rounded to Hyperliquid lot size.

---

## Re-hedge cadence

Hourly during active events, aligned with Hyperliquid funding ticks.
Skip if delta drift is below a tolerance band (don't pay fees on every
small wiggle).

Estimated cost: 0.4-0.9% of hedge notional per event at hourly rebalance,
Hyperliquid 0.015% maker / 0.035% taker. Maker-prefer on calm days.

---

## Why apply it

From the [absorbed #10 finding](../rd/candidates/03-kalshi-hyperliquid-vol-surface.md):

> Kalshi under-prices ATM BTC range buckets by ~10pp and over-prices
> far-OTM buckets by ~16.8pp vs. both the lognormal reference and an
> empirical-bootstrap from BTC's own 25h return distribution. The wedge
> is real (t-stat 17-50, n=4,601 and 901), persistent, and structural —
> the favorite-longshot bias documented in sports betting and horse
> racing, now measured in Kalshi crypto contracts.

This is the same edge the lottery PM book exploits. The hedging overlay
modifies the *path*, not the outcome:

1. **Smoother intra-event mark-to-market.** Most of a Kalshi BTC-range
   contract's 25h price swing is driven by BTC spot. Hedging strips that
   component out. Estimated: per-trade σ drops 30-50% on the crypto slice.
2. **Higher allowable leverage.** Lower mark-to-market σ under the same
   drawdown tolerance means ~1.5× position size (or 1.5× N_target).
3. **Separable risk accounting.** "Calibration edge" and "spot
   directional exposure" become distinct P&L attributions.
4. **Execution comfort.** Reduces panic-close risk on directional
   drawdown during event life.

---

## Costs and risks

| Risk | Magnitude | Mitigation |
|---|---|---|
| Hedge-leg fees | 0.4-0.9% of hedge notional per event | Maker-prefer on calm days; widen rebalance threshold below σ |
| Index tracking error | Kalshi settles on CME CF BTC Reference Rate; Hyperliquid tracks its own oracle. ~20-50bp typical, wider in vol spikes | Monitor basis; suspend hedging when divergence > threshold |
| Delta mis-specification | Computed deltas assume lognormal/empirical reference; if conditional shape differs, hedge is biased | D3 of #10 diagnostic showed lognormal ≈ empirical for BTC — low risk, but re-check in walk-forward |
| Tracking-error tail risk | Black-swan decoupling could turn the hedge into uncorrelated loss | Hard cap on hedge position size; kill switch on basis > 1% |
| Infrastructure complexity | New execution path, new monitor, new PnL attribution layer | Contain in a single module behind a feature flag; off by default |
| Stale `last_price` on illiquid OTM strikes | High | Reject any strike where `last_price` falls outside live `[yes_bid, yes_ask]` when a valid book exists. Sibling `kalshi-arb-trader` ran 0-14 win-rate on illiquid ladders for three days before catching this. |

---

## Prerequisites

When triggered, requires:

1. **Hyperliquid funding rate history** — ✓ (M2 data pipeline shipped)
2. **1-minute BTC_PERP candles** — ✓ (M2 shipped; Coinbase 1m as deeper backstop)
3. **Live Hyperliquid execution client in PM runner** — ✗ Not built. The
   sibling `kalshi-arb-trader` handles Kalshi execution; `crypto-copy-bot`
   has Hyperliquid spot+futures execution. Neither covers the perp-only
   execution we'd need.
4. **Basis monitoring** — ✗ Not built. Cross-check Kalshi settlement
   index vs. Hyperliquid oracle at each re-hedge decision.

---

## Implementation sketch

When and if triggered (~1-2 weeks after data prerequisites):

1. **Delta function.** Given `(p_i_ladder, spot, σ, T)`: compute
   `∂(portfolio_payoff)/∂(spot)` via finite difference on bucket prices
   (linearly-interpolated CDF). ~30 lines.
2. **Hedge position sizing.** Round to Hyperliquid lot size; respect
   min-size constraints. ~20 lines.
3. **Re-hedge loop.** Hourly cron during active events; skip if delta
   drift < tolerance band. Integrate with existing paper runner. ~100 lines.
4. **Hedge-adjusted sizing.** `book_σ_target` budget accounts for
   hedged-σ of crypto positions. Minor change to `portfolio.size_position()`.
5. **PnL attribution.** Per-event ledger row gets `hedge_pnl` +
   `tracking_error` columns separate from `calibration_pnl`. Minor change
   to monitor.

Total: 1-2 weeks once execution client + basis monitor exist.

---

## Pre-committed trigger criteria

**Trigger to build:**
- Phase 4 (live small) runs ≥ 30 days with crypto-slice observed σ
  meeting/exceeding walk-forward prediction AND observable mark-to-market
  discomfort, OR
- Replayed paper-book positions show the hedge would clear <0.5% fee drag
  per event.

**Trigger to kill (close as not-pursued):**
- Live crypto slice shrinks to <5% of book P&L after scanner re-tuning, OR
- Index tracking error is wider than 1% typical (hedge adds more σ than it
  removes).

---

## Where it would apply

**Scoped to:** crypto slice of PM Underwriting books (`KXBTC` /
`KXETH`). About 14% of current trade count and P&L.

**Does not apply to:** sports parlay and weather trades — those have no
hedgeable underlying.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Scoped as PM Phase 5 hedging overlay | The #10 D1 longshot wedge replicates the same edge PM exploits; the new info is that crypto positions are delta-hedgeable in a way sports parlays aren't |
| 2026-04-23 | Phase 3 vol-surface re-validation confirmed D1 wedge across two windows | Independent evidence the underlying edge is durable; supports building the overlay when data + execution prerequisites are met |
| 2026-04-25 | Doc moved to components/ as a reusable mechanism | Originally inline as PM Phase 5 in plan.md; it's a mechanism applicable to any Kalshi book whose payoff has a hedgeable underlying |
