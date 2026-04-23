# Implementation Plan — PM Underwriting

Prediction market underwriting strategy applied to Kalshi. Treats the Kalshi marketplace as an insurance book: build actuarial calibration curves from historical resolutions, identify systematically mispriced contracts, and trade the deviation.

For the full strategy prospectus and empirical derivation, see [`docs/rd/deep-dive-prediction-market-underwriting.md`](../rd/deep-dive-prediction-market-underwriting.md). For detailed methodology (data pipeline, math, assumptions), see [`docs/implementation/methodology.md`](methodology.md).

For the paused Elder-template parameter-search track, see [`docs/implementation/archived/`](archived/) and [`docs/rd/elder-track-pivot.md`](../rd/elder-track-pivot.md).

---

## Strategy Summary

**Edge:** Kalshi market prices deviate from true resolution rates. Two confirmed sources:
1. **Sports parlay overpricing** — Multi-leg sports bets systematically overpriced (prospect theory). Large edge (~4-7pp), but only ~6 months of history.
2. **Crypto longshot overpricing** — Classic favorite-longshot bias. Moderate edge (~3-4pp), more persistent.

**Mechanism:** Build per-category calibration curves (implied probability vs actual resolution rate) from historical data. When a live market's price deviates from the calibration curve by more than the fee-adjusted threshold, take the other side. Sizing is equal-σ (risk parity): `risk_budget_i = book_σ_target × NAV / (σ_i × √N_target)` where `σ_i` is looked up from a per-(category, side, 5¢ bin) σ table built from the walk-forward test set. History and decision log: [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md).

**Payoff profile (important):** the edge ranker systematically picks extreme-price bins (80-95¢ implied) where the label "underwriting" is misleading. At those prices, the actual per-trade distribution is a 9:1 lottery ticket: ~29% win rate × large wins vs. ~71% loss rate × small losses. The LLN requires ~100+ independent trials for the book to converge — equal-σ sizing with `N_target=150` is the framework that lets the book reach that count under a bounded aggregate σ.

**Data source:** TrevorJS/kalshi-trades HuggingFace dataset (154M trades, 17.5M markets, June 2021 – Jan 2026). Internally validated (99.71% consistency). Stored at `data/kalshi_hf/` (5.3 GB parquet, gitignored).

---

## Phases

| Phase | Description | Status | Result |
|---|---|---|---|
| 1 | Calibration curve | **Complete** | GO — 6 qualifying bins aggregate, 16 in sports parlays. Systematic overpricing confirmed. |
| 2 | Walk-forward backtest | **Complete** | GO — Sharpe 7.44, 66.9% WR, 83.6K trades. Calibration holds out-of-sample. |
| 2b | Capital-constrained simulation | **Complete** | GO at 20 trades/day: Sharpe 9.19, 303% return/41d, 3.4% max DD. Sports dominates (86% of trades). |
| 3 | Paper trading | **In progress** | Live via launchd since 2026-04-20; relaunched 2026-04-21 on equal-σ sizing (§3.5). |
| 3.5 | Sizing-framework reevaluation | **Complete (2026-04-21)** | Equal-σ + σ-table shipped. Kelly retired. Per-bin cap replaces category cap. Full log: [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md). |
| 4 | Live (small) | Pending | 5% of intended NAV after Phase 3 results + sizing decision. |
| 5 | **Hedging overlay (optional)** | **Scoped 2026-04-22** | Delta-hedge the crypto slice via Hyperliquid perps; preserves optionality without committing capital now. See §Phase 5 below. |

---

## Phase 1 — Calibration Curve (Complete)

Built PIT (point-in-time) calibration curves from 453K resolved markets.

**Method:** For each resolved market, compute the last trade price at 50% of market duration via ASOF join. Bin by 5% implied probability. Measure actual resolution rate per bin. Compare to perfect calibration (45-degree line).

**Key results:**
- 6 aggregate bins with >3pp deviation, n>=100, positive after Kalshi taker fees
- Sports: 16/20 bins show signal — parlay overpricing is pervasive
- Crypto: 5/20 bins — favorite-longshot bias in low-probability markets
- Financial/weather: near-efficient — no tradeable edge after fees
- Economics/politics: too few markets for statistical power

**Script:** `scripts/build_calibration_curve.py`
**Output:** `data/calibration/calibration_curves.png`

---

## Phase 2 — Walk-Forward Backtest (Complete)

70/30 temporal split (train: pre-2026-01-01, test: Jan 2026). Calibration curves built on train set only; portfolio simulated on test set with fractional Kelly sizing (since retired in Phase 3.5 — see below).

**Unconstrained results (all tradeable markets):**
| Metric | Value |
|---|---|
| Sharpe | 7.44 |
| Win rate | 66.9% |
| Total trades | 83,643 |
| Calibration accuracy | Train predicts test within 0.3-2.0pp for most bins |

**Caveats:** Test period is ~1 month. Win rate inflated by many small-edge trades. Concurrent exposure not modeled in unconstrained version.

**Script:** `scripts/walk_forward_backtest.py`
**Output:** `data/calibration/walk_forward_backtest.png`

---

## Phase 2b — Capital-Constrained Simulation (Complete)

Realistic portfolio simulation with concurrent position tracking, daily capital budget, per-event correlation cap, and throughput limits.

**Model:** Walk through time day-by-day. Positions entered at PIT time, resolved at close_time. Capital committed (risk budget) is locked until resolution. Priority: highest-edge candidates first.

**Constraints:**
- 1% of NAV max risk per position
- 5% of NAV max risk per event_ticker (correlated markets)
- Configurable trades-per-day cap
- Flat sizing (initial NAV) to isolate edge from compounding

**Throughput comparison ($10K NAV, 41-day test period):**

| Trades/day | Return | Sharpe | Max DD | Win Rate | Trades | Utilization |
|---|---|---|---|---|---|---|
| 20 | 303.6% | 9.19 | 3.4% | 29.0% | 639 | 37% |
| 50 | 575.8% | 8.83 | 6.1% | 29.6% | 1,382 | 46% |
| 100 | 747.1% | 7.31 | 4.3% | 33.2% | 2,625 | 52% |
| Unlimited | 2,365% | 9.46 | 4.3% | 50.6% | 16,108 | 92% |

**Key insights:**
- **Throughput, not capital, is the binding constraint.** Return % is NAV-independent (proportional sizing).
- **29% win rate is by design.** Selling overpriced yes contracts at 80-95 cents loses most individual trades but wins big (9:1+ payoff) on "no" resolutions.
- **Sports parlays dominate.** At 20/day: 86% of trades, 104% of P&L.
- **Returns are overstated.** 41-day test window, assumes perfect fills at PIT price, no market impact. Real-world execution friction will reduce returns significantly.

**Script:** `scripts/capital_constrained_sim.py`
**Output:** `data/calibration/capital_constrained_sim.png`

---

## Phase 3 — Paper Trading (In Progress)

Validates that the calibrated edge exists in live markets and that orders can be filled at edge prices. Runs under launchd every 15 min.

### Components Built

1. **Kalshi API client** (`src/prospector/kalshi/`) — REST for market data, orderbook, resolution status.
2. **Calibration store** (`src/prospector/strategies/pm_underwriting/calibration.py`, `scripts/refresh_calibration_store.py`) — Persist and update calibration curves; current-pointer file.
3. **Market scanner** (`src/prospector/strategies/pm_underwriting/scanner.py`) — Polls active markets, classifies category, computes edge vs calibration.
4. **Paper portfolio** (`src/prospector/strategies/pm_underwriting/portfolio.py`) — SQLite-backed position tracker with position/event/category % of NAV caps, count-based diversity guardrails, fees.
5. **Resolution monitor** (`src/prospector/strategies/pm_underwriting/monitor.py`) — Sweeps open positions, resolves against market results.
6. **Runner daemon** (`scripts/paper_trade.py`, `scripts/launchd/com.prospector.paper-trade.plist`) — Main loop; 15-min cadence; daily log rotation.

### Key Decisions

| Decision | Backtest Assumption | Paper Trading Approach |
|---|---|---|
| Entry timing | PIT (50% of market duration) | When scanner finds edge (any time) |
| Pricing | Maker (zero fees) | Paper assumes maker; fees modeled as round-trip taker to be conservative |
| Min edge | 2pp | 5pp (raised from 3pp on 2026-04-21 per sizing reeval) |
| Categories | All | Sports + crypto (best Sharpe × volume trade-off) |
| Throughput | 20/day cap | Same |
| Sizing | Quarter-Kelly + 1% position cap | Equal-σ with `book_σ_target=0.02`, `N_target=150`, clipped by 1% per-position cap |

### Success Criteria

- Positive P&L after 30 days
- Maker fill rate > 50% (validates zero-fee assumption)
- Observed win rate within 5pp of calibration prediction
- No single-day drawdown > 5% of NAV

---

## Phase 3.5 — Sizing Reevaluation (Complete, 2026-04-21)

Mid-Phase-3 we surfaced a structural mismatch between the sizing framework and the strategy's realized payoff profile. Edge ranking fills the extreme-price bins, which are 9:1 lottery tickets — not the win-often-lose-small insurance profile the deep-dive assumed. Kelly-per-bet + dollar caps + count caps weren't aligned with this distribution.

**Empirical measurement:** `scripts/return_distribution.py` on the walk-forward test set showed per-bet Sharpe of 0.057 (all trades) or 0.110 (high-edge slice). For book-level 90% confidence: 136 positions needed; the Phase 3 book was running ~36.

**Resolution — shipped 2026-04-21:**

1. **Equal-σ (risk-parity) sizing.** `risk_budget_i = book_σ_target × NAV / (σ_i × √N_target)` with `book_σ_target=0.02`, `N_target=150`, clipped by per-position, per-event, and per-bin caps. Sized from an empirical σ table (`data/calibration/sigma_table.json`) keyed by (category, side, 5¢ price bin) with pooled and aggregate fallbacks. Candidates with no σ at any level are rejected.
2. **Retired `max_category_frac`.** Replaced with `max_bin_frac=0.15` per (side, 5¢ bin). Finer grain, matches the σ-table key.
3. **Runner ranks by `edge_pp / σ_bin`.** Bin-level Sharpe proxy — concentrates fills in the best risk-adjusted slices.
4. **Raised `min_edge_pp` default 3 → 5.** Drops ~90% of low-Sharpe filler trades.
5. **Kelly book archived; fresh book launched on the new sizer.** No A/B run — Kelly had no academic justification under 30× σ dispersion across bins.

Full decision log and math: [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md).

---

## Phase 4 — Live (Small)

Deploy at 5% of intended NAV after Phase 3 results + sizing decision. Reuse paper trading infrastructure with real order submission. Details TBD.

---

## Phase 5 — Hedging Overlay (Optional, Scoped 2026-04-22)

Memorializes a finding from the #10 (Kalshi × Hyperliquid vol-surface) R&D track that bears directly on the PM book. Kept optional — documented so the optionality is available without committing engineering time until Phase 4 (Live) produces data that motivates the enhancement.

### 5.1 Trigger

From `docs/rd/deep-dive-kalshi-hyperliquid-vol-surface.md` §14 (Phase 1 diagnostic D1):

> Kalshi under-prices ATM BTC range buckets by ~10pp and over-prices far-OTM buckets by ~16.8pp vs. both the lognormal reference and an empirical-bootstrap from BTC's own 25h return distribution. The wedge is real (t-stat 17–50, n=4,601 and 901), persistent, and structural — the favorite-longshot bias documented in sports betting and horse racing, now measured in Kalshi crypto contracts.

This is the same edge PM already exploits (Phase 1 crypto-longshot calibration). The new information: because the underlying is BTC/ETH, positions are delta-hedgeable via Hyperliquid perps in a way sports parlays are not.

### 5.2 Scope

**Applies to:** The crypto slice of PM only — KXBTC / KXETH events. ~14% of current trade count and P&L (sports parlays dominate the rest). Not hedgeable for sports, weather, or any non-asset-referencing Kalshi contract.

**Does not apply to:** Sports parlay and weather trades — those stay directional as today. The hedging layer is an *additive* overlay, not a rewrite.

### 5.3 Thesis for why hedging adds value

Expected P&L per trade is unchanged; hedging modifies the *path*, not the outcome. The tangible wins:

1. **Smoother intra-event mark-to-market.** Most of a Kalshi crypto-range-bucket contract's 25h price swing is driven by BTC spot movement. Hedging strips that component out. Estimate: per-trade σ drops 30–50% on the crypto slice.
2. **Higher allowable leverage.** Lower mark-to-market σ under the same drawdown tolerance means ~1.5× position size (or 1.5× N_target). Paper book is currently at ~36 concurrent crypto positions vs. N_target=150 — hedging widens that envelope.
3. **Separable risk accounting.** "Calibration edge" and "spot directional exposure" become distinct P&L attributions. Matters for decay-vs-drift diagnostics post-live.
4. **Execution comfort.** Reduces the risk of operational panic-closes on directional drawdown during event life.

### 5.4 Costs and risks

| Cost / risk | Magnitude | Mitigation |
|---|---|---|
| Hedge-leg fees | 0.4–0.9% of hedge notional per event (hourly rebalance, Hyperliquid 0.015% maker / 0.035% taker) | Maker-prefer on calm days; adjust re-hedge cadence below hourly when σ low |
| Index tracking error | Kalshi settles on CME CF BTC Reference Rate; Hyperliquid tracks its own oracle. ~20–50bp typical divergence, wider in vol spikes | Monitor basis; suspend hedging when divergence exceeds threshold |
| Delta mis-specification | Computed deltas assume lognormal; if conditional shape differs, hedge is biased | D3 of the diagnostic showed lognormal and empirical-bootstrap BTC distributions agree — low risk, but re-check in walk-forward |
| Infrastructure complexity | New execution path, new monitor, new PnL attribution layer | Contain in a single module behind a feature flag; off by default |
| Tracking-error tail risk | Black-swan decoupling of the two references could turn the hedge into an uncorrelated loss | Hard cap on hedge position size; kill switch on basis > 1% |
| Stale `last_price` on illiquid OTM strikes (from sibling-project autopsy) | High | Medium | Reject any strike where `last_price` falls outside the live `[yes_bid, yes_ask]` when a valid book exists; fall back to `last_price` only when no two-sided book. The sibling `kalshi-arb-trader` ran 0-14 win-rate on illiquid ladders for three days before catching this. See their `tests/test_staleness_gates.py` for the template. |

### 5.5 Prerequisites

Hedging requires data and infrastructure that PM Underwriting doesn't currently use:

1. **Hyperliquid funding rate history.** Currently not local. Blocking dependency on [`data-pipeline.md`](data-pipeline.md) M2.
2. **1-minute BTC_PERP candles.** For realized-vol estimation and tighter re-hedge timing. Blocking on data-pipeline M2.
3. **Live Hyperliquid execution client in PM runner.** The sibling `kalshi-arb-trader` handles Kalshi execution; `crypto-copy-bot` has Hyperliquid execution for spot+futures. Neither covers the perp-only execution we'd need.
4. **Basis monitoring.** Cross-check Kalshi settlement index vs. Hyperliquid oracle at each re-hedge decision. New monitor.

### 5.6 Implementation sketch (when and if triggered)

Roughly 1–2 weeks after data pipeline is in place:

1. **Delta function.** Given (p_i_ladder, spot, σ, T): compute ∂(portfolio_payoff)/∂(spot) via finite difference on bucket prices (linearly-interpolated CDF). ~30 lines.
2. **Hedge position sizing.** Round to Hyperliquid's lot size; respect min-size constraints for thin alts. ~20 lines.
3. **Re-hedge loop.** Hourly cron during active events; skip if delta drift < tolerance band. Integrate with existing paper runner. ~100 lines.
4. **Hedge-adjusted sizing.** `book_σ_target` budget accounts for hedged-σ of crypto positions; sports positions sized as today against their own σ. Minor change to `portfolio.size_position()`.
5. **PnL attribution.** Per-event ledger row gets `hedge_pnl` + `tracking_error` columns separate from `calibration_pnl`. Minor change to `monitor.py`.

### 5.7 Pre-committed decision criteria

**Trigger to build (move Phase 5 from "Optional" to "In Progress"):**
- Phase 4 (Live Small) runs ≥ 30 days with crypto-slice observed-σ meeting or exceeding walk-forward prediction AND observable mark-to-market discomfort — OR —
- Data pipeline M2 ships and hedge-overlay ROI can be demonstrated on replayed paper-book positions with <0.5% fee drag per event.

**Trigger to kill (close Phase 5 as "Not Pursued"):**
- Live crypto slice shrinks to <5% of book P&L after scanner re-tuning (maybe the D1 far-OTM opportunity was narrower than it looked) — OR —
- Data pipeline reveals Kalshi-vs-Hyperliquid index tracking error is wide enough (>1% typical) that hedging adds more σ than it removes.

### 5.8 Cross-references

- Source of the finding: [`docs/rd/deep-dive-kalshi-hyperliquid-vol-surface.md`](../rd/deep-dive-kalshi-hyperliquid-vol-surface.md) §14
- Data prerequisites: [`docs/implementation/data-pipeline.md`](data-pipeline.md) M2
- Current sizing framework: [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md) — any hedging layer must preserve equal-σ at book level
