# Methodology — PM Underwriting Validation Pipeline

This document explains how the three validation phases work: calibration curve construction (Phase 1), walk-forward backtest (Phase 2), and capital-constrained simulation (Phase 2b). It covers the data, the math, the assumptions, and the known limitations.

For the strategic rationale and theoretical framework, see [`docs/rd/deep-dive-prediction-market-underwriting.md`](../rd/deep-dive-prediction-market-underwriting.md). For how to run the scripts, see [`docs/reference/runbook.md`](../reference/runbook.md).

---

## Table of Contents

1. [Data Source and Validation](#1-data-source-and-validation)
2. [Phase 1: Calibration Curve](#2-phase-1-calibration-curve)
3. [Phase 2: Walk-Forward Backtest](#3-phase-2-walk-forward-backtest)
4. [Phase 2b: Capital-Constrained Simulation](#4-phase-2b-capital-constrained-simulation)
5. [Phase 3: Paper Trading (Live)](#5-phase-3-paper-trading-live)
6. [Phase 3.5: Return-Distribution Analysis](#6-phase-35-return-distribution-analysis)
7. [Key Assumptions and Limitations](#7-key-assumptions-and-limitations)

---

## 1. Data Source and Validation

### The dataset

All analysis uses the TrevorJS/kalshi-trades HuggingFace dataset: 154M trades and 17.5M markets from June 2021 through January 2026. The data is stored locally as parquet files in `data/kalshi_hf/` (~5.3 GB, gitignored).

The dataset has two tables:
- **Markets** — One row per Kalshi contract: `ticker`, `event_ticker`, `result` (yes/no/null for unresolved), `volume`, `open_time`, `close_time`, and other metadata.
- **Trades** — One row per executed trade: `ticker`, `yes_price` (1-99 cents), `created_time`, `count`, `taker_side`.

### Validation

Direct cross-validation against Kalshi's API was limited because Kalshi purges old settled market data (API returns 404 for settled tickers). Validation was done through:

1. **Internal consistency checks:**
   - 99.71% exact match between sum-of-trade-counts and market-level volume fields
   - Zero duplicate trade IDs across the entire dataset
   - Monotonically correct last-price-to-result calibration (last trades near 99 cents for yes-resolving markets, near 1 cent for no-resolving markets)

2. **API overlap validation:**
   - Found 445 zero-volume markets present in both the HuggingFace dataset and Kalshi's live API
   - 100% field match on all overlapping records (result, open_time, close_time)

3. **Known-outcome verification:**
   - Spot-checked specific markets with known public outcomes (2024 election, NFL games, NYC mayoral race) — all matched

### Filtering

Before any analysis, markets are filtered:
- `result IN ('yes', 'no')` — only resolved markets (excludes ~14M unresolved/cancelled)
- `volume >= 10` — excludes illiquid markets with no meaningful price discovery
- `close_time > open_time` — excludes malformed records
- After filtering: ~3.5M resolved markets remain

---

## 2. Phase 1: Calibration Curve

**Script:** `scripts/build_calibration_curve.py`

The calibration curve answers: *when Kalshi prices a contract at X cents (implying X% probability), how often does the event actually happen?*

### 2.1 Point-in-Time (PIT) Pricing

We cannot use the market's `last_price` (the final trade before resolution) because it converges toward the outcome as resolution approaches. A market resolving "yes" will have its last trade near 99 cents; a market resolving "no" will have its last trade near 1 cent. Using `last_price` would make the calibration curve trivially perfect and useless.

Instead, we use **Point-in-Time (PIT) pricing**: the market price at 50% of the market's duration. For a market that opens on Monday and closes on Friday, PIT is Wednesday. This captures the market's mid-life assessment before terminal convergence.

**Computation:**

```
pit_time = open_time + (close_time - open_time) / 2
```

### 2.2 ASOF Join

Finding the trade price at an exact timestamp is impractical because trades arrive at irregular intervals. Instead, we use DuckDB's **ASOF join** to find the last trade at or before the PIT time:

```sql
SELECT m.ticker, t.yes_price AS pit_price, t.created_time AS trade_time
FROM markets m
ASOF JOIN trades t
    ON m.ticker = t.ticker
    AND m.pit_time >= t.created_time
```

This efficiently finds, for each market, the most recent trade before its midpoint. The trades table is pre-sorted by `(ticker, created_time)` for the ASOF join to work correctly.

**Fallback:** For markets where no trade occurred before the PIT time (the market opened but no one traded until after the midpoint), a post-PIT fallback finds the first trade after PIT. This is rare but handles thinly-traded markets.

### 2.3 Time-Offset Filter

Even with the ASOF fallback, the matched trade might be far from the PIT time — for example, a market that lasted 30 days but had no trades near its midpoint, with the closest trade being 10 days before. This would give a stale price.

To ensure data quality, we compute the fractional offset:

```
offset_frac = |trade_time - pit_time| / (close_time - open_time)
```

Markets with `offset_frac > 0.25` are excluded. This means the matched trade must be within the middle 50% of the market's duration (between 25% and 75% of market life). After this filter: ~454K markets remain from the original 3.5M.

### 2.4 Category Classification

Markets are classified into categories by `event_ticker` prefix using SQL pattern matching:

| Category | Prefix patterns | Example |
|---|---|---|
| Sports | `KXMVESPORTS%`, `KXNFL%`, `KXNBA%`, `KXNCAA%` | NFL game outcomes, NBA parlays |
| Crypto | `KXBTC%`, `KXETH%`, `KXSOL%`, `KXDOGE%` | "BTC above $100K by Friday" |
| Financial | `KXNASDAQ%`, `KXINX%`, `USDJPY%`, `EURUSD%` | "Nasdaq closes above 18000" |
| Weather | `KXCITIES%`, `HIGH%`, `LOW%` | "NYC high above 80°F tomorrow" |
| Economics | `CPI%`, `FED%`, `GDP%` | "Fed raises rates in March" |
| Politics | `PRES%`, `SENATE%`, `HOUSE%`, `KXGOV%` | Election outcomes |
| Other | Everything else | Misc markets |

This classification is done in SQL at data-loading time and carried through all subsequent analysis. The same SQL expression is used in all three scripts for consistency.

### 2.5 Binning and Calibration Measurement

PIT prices range from 1 to 99 cents. We group them into 20 bins of 5 percentage points each:

| Bin | Price range | Implied midpoint |
|---|---|---|
| 0-5 | 1-4 cents | 2.5% |
| 5-10 | 5-9 cents | 7.5% |
| ... | ... | ... |
| 95-100 | 95-99 cents | 97.5% |

For each bin, we compute:
- **n** — number of markets in the bin
- **yes_count** — how many resolved "yes"
- **actual_rate** = yes_count / n — the observed resolution frequency
- **implied_mid** — the bin's midpoint (e.g., 7.5% for the 5-10 bin)
- **deviation** = actual_rate - implied_mid — how far reality deviates from the market price

A perfectly calibrated market has deviation ≈ 0 for all bins.

### 2.6 Wilson Confidence Intervals

Raw actual rates are noisy for small samples. We use Wilson score intervals (not the naive normal approximation) because they handle small n and extreme proportions correctly:

```
centre = (p_hat + z²/2n) / (1 + z²/n)
spread = z × sqrt((p_hat(1-p_hat) + z²/4n) / n) / (1 + z²/n)
CI = [centre - spread, centre + spread]
```

where `p_hat = yes_count / n` and `z = 1.96` (95% confidence). Wilson intervals are bounded to [0, 1] and well-behaved even when p_hat is near 0 or 1.

### 2.7 Fee-Adjusted Edge

Kalshi charges taker fees of `0.07 × p × (1-p)` per contract per side. Round-trip taker cost:

```
fee_roundtrip = 2 × 0.07 × p × (1-p)
```

The fee-adjusted edge is:

```
fee_adj_edge = |deviation| - fee_roundtrip
```

A bin only has a tradeable signal if the deviation exceeds fees. Note that fees are highest at p = 0.5 (1.75 cents round-trip) and lowest at the extremes (near zero for p close to 0 or 1). This means edge in the wings (longshots and favorites) is more likely to survive fees.

**Maker pricing:** Kalshi charges zero fees for resting limit orders. If we can fill as a maker (which the paper trading phase will test), the fee-adjusted edge equals the raw deviation.

### 2.8 Signal Detection and Go/No-Go

A bin is classified as having "signal" if all three conditions hold:
1. **n ≥ 100** — sufficient sample size for statistical reliability
2. **|deviation| > 3pp** — deviation exceeds noise threshold
3. **fee_adj_edge > 0** — edge survives transaction costs (using taker fees as conservative assumption)

**Go criterion:** ≥ 3 bins with signal in the aggregate curve. If the calibration curve is flat (within ±2pp everywhere), the market is well-calibrated and there's no edge.

**Result:** 6 qualifying bins in aggregate. 16/20 in sports. GO.

---

## 3. Phase 2: Walk-Forward Backtest

**Script:** `scripts/walk_forward_backtest.py`

The calibration curve tells us where mispricing exists historically. The walk-forward backtest tests whether curves built on *past* data predict *future* resolution rates — and whether a portfolio trading those predictions is profitable.

### 3.1 Train/Test Split

All 454K PIT-priced markets are sorted by `close_time` (resolution date). The first 70% become the **train set** (~318K markets); the last 30% become the **test set** (~136K markets).

The split point falls at approximately January 1, 2026. This means:
- **Train:** June 2021 through December 2025
- **Test:** January 2026 (~1 month)

The train set is used *only* for building calibration curves. The test set is used *only* for portfolio simulation. No information leaks forward.

### 3.2 Per-Category Calibration on Train Set

Using the train set only, we build calibration curves identically to Phase 1 (same binning, same methodology). We build one curve per category plus one aggregate curve. The aggregate curve serves as a fallback when a category has insufficient data for a given bin.

Each calibration bin stores: bin boundaries, market count (n), yes count, and derived properties (actual_rate, implied_mid).

### 3.3 Edge Lookup

For each test-set market, we look up the calibrated edge:

1. Find the category-specific curve for this market's category
2. Find the bin matching this market's PIT price
3. If the bin has n ≥ 50, compute edge: `edge_pp = |implied_mid - actual_rate| × 100`
4. Determine side: if actual_rate < implied_mid (market overprices the event), `side = "sell_yes"`; otherwise `side = "buy_yes"`
5. If the category bin has insufficient data (n < 50), fall back to the aggregate curve

Markets with edge < 2pp or no matching bin are skipped (no trade).

### 3.4 Position Sizing — Fractional Kelly

> **Note (2026-04-21):** This section describes the sizing rule used for the Phase 2 backtest and inherited by Phase 3 paper trading. Phase 3.5 is actively reevaluating it — per-bet Sharpe measurement indicates Kelly + dollar caps is undersizing the book relative to what the payoff distribution requires. See [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md).

For each trade, we compute the optimal bet fraction using the Kelly criterion adapted for binary options:

**For sell_yes** (we believe the market overprices the event):
```
p_true = implied - edge_pp / 100        # our estimate of true probability
kelly  = (implied - p_true) / (1 - p_true)
```

**For buy_yes** (we believe the market underprices the event):
```
p_true = implied + edge_pp / 100
kelly  = (p_true - implied) / (1 - implied)
```

The raw Kelly fraction is then:
- Multiplied by `KELLY_FRACTION = 0.25` (quarter-Kelly for safety)
- Clamped to `p_true ∈ [0.01, 0.99]` to avoid degeneracy

The **risk budget** (maximum dollar amount at risk on this trade) is:

```
risk_budget = min(kelly × INITIAL_NAV, MAX_POSITION_FRAC × INITIAL_NAV)
```

where `MAX_POSITION_FRAC = 0.01` (1% of NAV cap per position).

**Why flat sizing:** We use `INITIAL_NAV` (not current NAV) for all position sizing. This isolates the edge measurement from compounding effects. If we sized based on current NAV, a lucky early streak would inflate subsequent positions, and the Sharpe/return metrics would reflect compounding math rather than edge quality. Flat sizing shows what the edge itself produces.

### 3.5 P&L Math for Binary Options

Kalshi contracts pay $1 if the event happens ("yes") and $0 if it doesn't ("no"). A contract priced at P cents means:

**Selling yes at P cents:**
- You receive P cents per contract upfront
- You post (100 - P) cents as collateral per contract
- Your **risk per contract** = (100 - P) / 100 dollars (what you lose if event happens)
- Your **reward per contract** = P / 100 dollars (what you keep if event doesn't happen)
- Contracts = risk_budget / risk_per_contract

**Buying yes at P cents:**
- You pay P cents per contract
- Your **risk per contract** = P / 100 dollars (what you lose if event doesn't happen)
- Your **reward per contract** = (100 - P) / 100 dollars (your profit if event happens)
- Contracts = risk_budget / risk_per_contract

**Resolution P&L:**

| Side | Result = "no" | Result = "yes" |
|---|---|---|
| sell_yes | +contracts × reward_per (WIN) | -contracts × risk_per (LOSS) |
| buy_yes | -contracts × risk_per (LOSS) | +contracts × reward_per (WIN) |

**Example — selling yes at 90 cents ($0.90):**
- risk_per_contract = $0.10
- reward_per_contract = $0.90
- On $100 risk_budget: contracts = $100 / $0.10 = 1,000
- If event happens (loss): P&L = -1,000 × $0.10 = -$100
- If event doesn't happen (win): P&L = +1,000 × $0.90 = +$900
- Payoff ratio: 9:1. You lose often but win big.

This asymmetry is why the walk-forward win rate (66.9%) and the capital-constrained win rate (29%) differ so dramatically — the capital-constrained simulation prioritizes the highest-edge bins (which tend to be at extreme prices with asymmetric payoffs).

### 3.6 Portfolio Simulation (Unconstrained)

The unconstrained simulation processes test-set markets sequentially by close_time:

1. For each market: look up edge, skip if below threshold
2. Compute Kelly sizing and risk budget
3. Compute P&L based on resolution outcome
4. Add P&L to running NAV
5. Record daily NAV snapshots (one per unique close_date)

This version does NOT track concurrent positions. Each trade is independent. The NAV simply accumulates P&L. This is why the unconstrained results (83K trades, Sharpe 7.44) are unrealistic — they assume infinite capital and ignore the fact that thousands of positions would be open simultaneously.

### 3.7 Calibration Accuracy Check

After simulation, we compare the train-set calibration (what we predicted) against the test-set actuals (what happened):

For each bin, compute:
- **Train calibration:** the actual_rate from the train set
- **Test actual:** the resolution rate of traded markets in the test set
- **Gap:** test_actual - train_calibration

If the gap is small (< 2-3pp), the calibration curve generalizes well. Large gaps at specific bins indicate overfitting or regime change.

**Result:** Most bins show gaps within 0.3-2.0pp. The 85-100% implied bins showed larger gaps (5-8pp), suggesting the calibration is less stable at the extremes.

### 3.8 Go/No-Go Criteria

| Criterion | Threshold | Result |
|---|---|---|
| Sharpe ratio | > 1.0 | 7.44 — PASS |
| Win rate | > 50% | 66.9% — PASS |
| Max drawdown | < 20% | 0.0% — PASS (artifact of daily aggregation) |
| Positive P&L | > $0 | $1.59M — PASS |
| Trade count | ≥ 100 | 83,578 — PASS |

All criteria passed. Note that the 0% max drawdown is an artifact: with thousands of trades per day, daily NAV changes are always net positive due to diversification. This does not mean the strategy is risk-free — it means the daily granularity masks intraday risk.

---

## 4. Phase 2b: Capital-Constrained Simulation

**Script:** `scripts/capital_constrained_sim.py`

The unconstrained backtest proved the edge exists but produced unrealistic returns (83K trades on $10K, infinite concurrent capital). The capital-constrained simulation models what actually happens when you have limited capital, limited throughput, and positions that tie up collateral until they resolve.

### 4.1 Position Lifecycle

Each position has three phases:

1. **Entry (at PIT time):** Capital is committed. Cash decreases by risk_budget.
2. **Open (between PIT and close):** Capital is locked. Cannot be used for other trades.
3. **Resolution (at close_time):** Position resolves. Cash increases by risk_budget + P&L (which can be negative — a total loss returns zero, i.e., cash += risk_budget + (-risk_budget) = 0).

The time between entry and resolution varies from hours (intraday crypto markets) to months (long-dated political markets). During this time, the committed capital is unavailable.

### 4.2 Day-by-Day Simulation

The simulation walks through every calendar date that has either an entry or a resolution event:

```
for each date in sorted(all_pit_dates ∪ all_close_dates):
    1. RESOLVE: close positions with close_date ≤ today
    2. COLLECT: gather today's candidate entries (pit_date = today)
    3. RANK: sort candidates by edge descending (best first)
    4. ENTER: fill positions top-down until constraints bind
    5. SNAPSHOT: record daily NAV, cash, positions, utilization
```

Resolving before entering means capital freed by morning resolutions is immediately available for afternoon entries on the same day. This is realistic for Kalshi, where settlement is same-day.

### 4.3 Capital Accounting

```
cash = initial_nav                    # starts fully liquid

On entry:    cash -= risk_budget      # lock collateral
On resolve:  cash += risk_budget + pnl  # free collateral ± profit

NAV = cash + Σ(risk_budget for open positions)    # book value
utilization = Σ(risk_budget for open positions) / NAV
```

NAV equals the total economic value of the portfolio. Open positions are valued at their committed capital (book value), not mark-to-market. This is standard for insurance-like books where positions are not actively traded — you hold to resolution. NAV only changes when positions resolve and P&L is realized.

### 4.4 Constraint Hierarchy

On each candidate entry, three checks are applied in order:

**1. Throughput cap** — Maximum new trades per day (20, 50, 100, or unlimited). Once the daily limit is reached, all remaining candidates for that day are skipped. This models the realistic execution pace: how many orders can you place and manage per day?

**2. Capital check** — `risk_budget ≤ cash`. If the position's risk budget exceeds available cash, it's skipped. This is the hard budget constraint — you cannot commit capital you don't have.

**3. Event-ticker cap** — `event_risk[event_ticker] + risk_budget ≤ MAX_EVENT_FRAC × initial_nav`. Total risk committed to positions sharing the same `event_ticker` cannot exceed 5% of NAV. This prevents correlated concentration — multiple contracts on the same event (e.g., several strike prices for "BTC above $X") are treated as a single risk exposure.

Candidates are ranked by edge descending before applying these checks, so the highest-edge opportunities are filled first when capital is limited.

### 4.5 Why Throughput Matters More Than Capital

A key finding: return percentage is identical across all NAV levels ($10K, $50K, $100K) because position sizing is proportional to NAV. At $10K, each position risks $100; at $100K, each position risks $1,000. The number of positions that fit in the portfolio is the same because both the position sizes and the total capital scale together.

What actually constrains returns is **throughput** — how many trades you can place per day. The throughput comparison shows:

| Trades/day | Trades entered | % of candidates | Return |
|---|---|---|---|
| 20 | 639 | 0.8% | 303.6% |
| 50 | 1,382 | 1.7% | 575.8% |
| 100 | 2,625 | 3.2% | 747.1% |
| Unlimited | 16,108 | 19.4% | 2,365% |

Even at unlimited throughput, only 19.4% of candidates are entered — the rest are blocked by the capital constraint. At 20/day, only 0.8% get through. This means there are far more tradeable opportunities than we can exploit.

### 4.6 The Reinvestment Dynamic

Even with flat sizing (each position risks 1% of initial_nav, not current_nav), the portfolio grows through reinvestment:

1. **Day 1:** $10K cash → enter 100 positions at $100 each → cash = $0
2. **Day 2:** 20 positions resolve (net positive P&L) → cash = ~$1,500 → enter 15 more positions
3. **Day 10:** Accumulated profits allow ~200 concurrent positions
4. **Day 41:** ~1,800 concurrent positions, NAV = $40K+

Each individual position is still sized at $100 (1% of initial $10K). But as profits accumulate, more cash is available, allowing more positions. The total risk deployed grows not because positions get larger, but because there are more of them. This is the source of the seemingly extreme returns — high throughput × small edge × rapid capital recycling.

### 4.7 Why Win Rate is 29% (Not 67%)

The unconstrained backtest had a 66.9% win rate. The capital-constrained sim at 20/day shows 29%. These are not contradictory.

The constrained simulation prioritizes the **highest-edge** candidates first. The highest edges are in the extreme bins (80-95 cents implied) where sports parlays are massively overpriced. Selling yes at 90 cents:
- **Wins** when the event doesn't happen (market resolves "no"): you earn $900 on $100 risk
- **Loses** when the event happens (market resolves "yes"): you lose $100

The event typically *does* happen (85%+ of the time for these high-implied markets). So you lose 85% of individual trades. But each win pays 9:1, so:

```
Expected P&L = 0.15 × $900 - 0.85 × $100 = $135 - $85 = +$50 per trade
```

The unconstrained simulation includes many trades at moderate prices (40-60 cents) where win rates are closer to 50:50. The constrained simulation preferentially fills the extreme bins because they have the largest edge.

Low win rate + high payoff ratio = positive expected value. This is *not* the insurance-underwriting payoff profile the strategy prospectus described (win-often-lose-small, many independent policies). The edge ranker systematically inverts that pattern — it selects the *buyer* of the lottery ticket, not the *writer* of the insurance. The sample-size implications (large N needed for the LLN to work) are what drive the Phase 3.5 sizing reevaluation in [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md).

### 4.8 Daily Snapshots

Each simulation day records:
- **date** — calendar date
- **nav** — portfolio book value (cash + committed capital)
- **cash** — available liquid capital
- **n_open** — number of open positions
- **n_entered** — new positions entered today
- **n_skipped_capital** — candidates skipped (insufficient cash or throughput cap)
- **n_skipped_event** — candidates skipped (event-ticker cap)
- **capital_utilization** — fraction of NAV committed to open positions
- **realized_pnl** — P&L from positions that resolved today

These snapshots drive the Sharpe ratio (computed from daily NAV returns), max drawdown (peak-to-trough NAV), and the utilization/position time series in the output plots.

---

## 5. Phase 3: Paper Trading (Live)

**Scripts:** `scripts/paper_trade.py` (runner), `scripts/refresh_calibration_store.py` (snapshot builder).
**Launched:** 2026-04-20 under launchd (15-min cadence, daily UTC log rotation).

### 5.1 Infrastructure

The paper-trading stack mirrors Phase 2b's simulation in live form:

- **Calibration store** — `data/calibration/store/calibration-<timestamp>.json` plus a `current.json` pointer. Built by `refresh_calibration_store.py` from the same HuggingFace dataset using Phase 1's methodology. The snapshot is immutable; swapping pointers is the recalibration primitive.
- **Kalshi REST client** (`src/prospector/kalshi/`) — Pagination-aware market/event/orderbook endpoints. Scans by event first to avoid scraping the full market universe every tick.
- **Paper portfolio** (`src/prospector/underwriting/portfolio.py`) — SQLite-backed. Tracks positions, NAV, cash, locked risk. Enforces all entry constraints (see §5.2). Models round-trip Kalshi taker fees as a conservative assumption.
- **Scanner** (`scanner.py`) — Walks active events, computes fee-adjusted edge vs the current calibration snapshot, emits Candidate objects.
- **Monitor** (`monitor.py`) — Sweeps open positions, resolves against settled markets. Handles `voided` markets as zero-P&L closures.
- **Runner** (`runner.py`, `paper_trade.py`) — Sweep → scan → rank → enter → snapshot. One tick per launchd invocation.

### 5.2 Constraint hierarchy (current live config)

Applied at entry time, in order. The first failing check rejects the candidate with a reason logged; remaining candidates in the tick get their turn.

1. **Per-position $ cap** — `max_position_frac = 0.01` (1% of NAV). Bounds worst-case single-trade loss.
2. **Available cash** — `risk_budget ≤ cash`. Hard budget constraint.
3. **Per-event $ cap** — `max_event_frac = 0.05` (5% of NAV). Prevents stacking multiple contracts on the same event.
4. **Per-category $ cap** — `max_category_frac = 0.20` (20% of NAV). Bounds correlated-category drawdown (all sports markets share league-level shocks).
5. **Per-event count** — `max_positions_per_event = 1`. Simple diversity guardrail.
6. **Per-subseries count** — `max_positions_per_subseries = 1`. Subseries = event_ticker minus trailing segment, typically a game/round grouping.
7. **Per-series count** — `max_positions_per_series = 3`. Series = series_ticker (e.g. KXNFL).
8. **Daily trade cap** — `max_trades_per_day = 20`. Matches the capital-constrained sim's best throughput slot.
9. **No duplicate open ticker** — at most one open position per market.

Dollar caps (1-4) are primary; count caps (5-7) are derivative guardrails against correlation stacking that the dollar caps don't catch.

### 5.3 Sizing

Currently quarter-Kelly (`f* = edge / P` for sell-yes, `edge / (1 - P)` for buy-yes), clamped to the per-position $ cap. This is the same rule as Phase 2 with one correction: the denominator was `P/(1-P)` in a pre-live revision of the code, which undersized high-price sell-yes bets by a factor of `(1-P)` — negligible at P=0.5 but 100× at P=0.99.

See §3.4 note — sizing is under Phase 3.5 reevaluation.

### 5.4 Operational notes

- **Fees.** Live book charges round-trip `0.14 × P × (1-P) × contracts` at entry and deducts at resolution. This models paper execution as conservatively taker-priced; a maker fill in production would refund these.
- **Voided markets.** Some Kalshi markets finalize without a binary outcome. Monitor treats these as zero-P&L closures and refunds risk + fees. Live book tolerates the edge case idempotently.
- **Logging.** `data/paper/logs/paper_trade-YYYYMMDD.log`, rotated daily at UTC midnight via a shell wrapper. Stdout/stderr from launchd itself land in `launchd.log` for bootstrap diagnostics.

---

## 6. Phase 3.5: Return-Distribution Analysis

**Script:** `scripts/return_distribution.py`.
**Purpose:** Measure per-trade μ, σ, Sharpe from the walk-forward test set so the sizing framework can be grounded in the empirical distribution instead of Kelly's known-edge assumption.

### 6.1 Per-trade return metric

Each trade's return is expressed as `pnl / risk_budget`, which collapses to:

- `+reward_per_risk` on win (dimensionless payoff multiple)
- `-1.0` on loss

This normalization lets us compare bins with wildly different absolute P&L magnitudes. A sell_yes at 90¢ has `reward_per_risk = 9` while a sell_yes at 10¢ has `reward_per_risk ≈ 0.11` — same strategy, very different distributions.

### 6.2 Top-line results (test set, n = 81,556)

| Stratum | n | Win rate | Sharpe | N for P≥90% |
|---|---|---|---|---|
| All trades (edge ≥ 2pp) | 81,556 | 66.2% | **0.057** | 511 |
| High-edge slice (edge ≥ 5pp) | 6,523 | 39.4% | **0.110** | 136 |

The formula `N ≥ (z_α / Sharpe)²` (with z₀.₉₀ = 1.28) assumes independent, Gaussian-aggregate bets.

### 6.3 Per-bin Sharpe dispersion

Per-bet Sharpe varies ~5× across price bins. The best slices for risk-adjusted return:

| Side | Price bin | Sharpe | Win rate | Avg payoff/$risk |
|---|---|---|---|---|
| sell_yes | 95-100¢ | 0.285 | 12.5% | 65.7 |
| sell_yes | 85-90¢ | 0.180 | 20.2% | 6.7 |
| sell_yes | 90-95¢ | 0.169 | 14.1% | 11.3 |
| buy_yes | 0-5¢ | 0.149 | 6.0% | 47.8 |

Aggregate Sharpe (0.057) is dragged down by ~70,000 low-Sharpe filler trades in the 5-50¢ sell_yes range. Raising the minimum-edge filter from 2pp to 5pp drops those bins without giving up the high-Sharpe slices.

### 6.4 Implication

The current live book (~36 positions, quarter-Kelly) is 4× to 14× undersized relative to the N needed for book-level 90% confidence. The framework is not wrong — it's sized for the wrong distribution. The full argument and proposed changes are in [`docs/rd/sizing-reevaluation.md`](../rd/sizing-reevaluation.md).

---

## 7. Key Assumptions and Limitations

### Assumptions built into all three phases

| Assumption | Impact if wrong | How paper trading tests it |
|---|---|---|
| **PIT price = entry price.** We assume we can enter at the price observed at 50% of market duration. | If actual fill prices are worse, edge shrinks. | Paper trading records actual fill prices vs PIT. |
| **Maker pricing (zero fees).** Backtest assumes we fill as a resting limit order. | If we must cross the spread (taker), fees eat 1-7% of edge depending on price. | Paper trading tracks maker vs taker fill rates. |
| **Category classification is correct.** SQL prefix matching assigns categories. | Misclassification applies the wrong calibration curve. | Spot-check classification accuracy. |
| **Markets are independent across events.** Same-event cap handles within-event correlation, but cross-event correlation is not modeled. | Correlated losses (e.g., a sports league cancellation) could blow through expected drawdown. | Monitor portfolio-level drawdown events. |
| **Calibration is stationary.** Train-period curves predict test-period outcomes. | If the market becomes more efficient over time, edge decays. | Rolling recalibration with circuit breaker. |
| **Unlimited liquidity at PIT price.** We assume we can fill any size at the PIT price. | Kalshi orderbooks may be thin; large orders move the market. | Paper trading reveals actual market depth. |

### Known limitations

1. **Short test period.** The test set covers ~1 month (January 2026). A single anomalous month could dominate results. A longer dataset or rolling walk-forward would be more robust, but the HuggingFace dataset only extends through January 2026.

2. **Sports history is short.** Kalshi sports markets launched mid-2024. The 16/20 signal bins in sports come from ~6 months of data. This is the strongest signal but also the least validated temporally.

3. **No intraday simulation.** The capital-constrained sim operates on calendar days, not timestamps. A market that opens and resolves within the same day ties up capital for one full day in the simulation. This is slightly conservative for short-duration markets.

4. **Book-value NAV.** Open positions are valued at committed capital, not mark-to-market. If the underlying event probability shifts dramatically mid-position, the book NAV doesn't reflect this until resolution. This is standard for hold-to-maturity positions but obscures interim risk.

5. **No slippage or market impact model.** The simulation assumes fills at PIT price. In reality, placing 20 orders per day on Kalshi may move prices, especially in thin markets.

6. **Aggregate "other" category.** The "other" category (12/20 signal bins) is a catch-all that likely contains heterogeneous market types. Decomposing it could reveal sub-categories with stronger or weaker signal.
