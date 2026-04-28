# Terminology

> Glossary of trading concepts and project-specific terms.

For the formal definitions of pipeline stages and verdicts, see
[`stages-and-verdicts.md`](stages-and-verdicts.md). For component
mechanisms with full math, see [`../components/`](../components/).

Some entries below are **legacy / Elder-track** terms — preserved for
historical context (zero data loss). They're marked with `[legacy]` and
won't appear in current strategy work.

---

## Calibration & PM Underwriting

**Beat-line rate**
The fraction of resolved positions where CLV is positive (we beat the
closing line). Standard sports-sharp metric. See
[`../components/clv-instrumentation.md`](../components/clv-instrumentation.md).

**Bin (5¢ price bin)**
A 5-percentage-point slice of the implied-probability range used by the
calibration curve and σ-table. Bins: 0-5%, 5-10%, ..., 95-100%.

**Calibration curve**
Per-category mapping from implied-probability bin → empirical resolution
rate. Built from historical resolved markets via PIT pricing. Deviations
from 45° are tradeable edges. See
[`../components/calibration-curves.md`](../components/calibration-curves.md).

**Calibration store**
Versioned on-disk snapshots of calibration curves at
`data/calibration/store/calibration-<timestamp>.json`. The
`current.json` pointer file says which snapshot is active. See
[`../platform/calibration-store.md`](../platform/calibration-store.md).

**CLV (Closing-Line Value)**
Signed gap between entry price and the market's closing line.
Positive = we beat the line. Stabilizes ~10× faster than realized P&L
on low-WR / high-payoff books. See
[`../components/clv-instrumentation.md`](../components/clv-instrumentation.md).

**Edge (fee-adjusted)**
`|implied_mid − actual_rate| − fee_roundtrip`. The portion of
calibration deviation that survives Kalshi taker fees. The scanner
filters by this. See
[`../components/fee-modeling-kalshi.md`](../components/fee-modeling-kalshi.md).

**Equal-σ sizing (risk parity)**
Per-position sizing rule: `risk_budget = book_σ_target × NAV /
(σ_i × √N_target)`, clipped by `max_position_frac × NAV`. Each position
contributes uniformly to book-level σ. See
[`../components/equal-sigma-sizing.md`](../components/equal-sigma-sizing.md).

**Insurance book**
PM Underwriting variant scoped to 0.55-0.75 entry-price band — the slice
where the actuarial premium actually lives (high WR, small wins, low
variance). See [`../rd/candidates/04-pm-underwriting-insurance.md`](../rd/candidates/04-pm-underwriting-insurance.md).

**Kalshi binary contract**
A market that pays $1 if the named event happens ("yes") and $0
otherwise ("no"). Yes and no prices sum to 1.0 (up to fee wedge).

**Kalshi position limit**
Per-user cap on contract count per market. Affects the small-player
maker-side reflexivity candidate ([12](../rd/candidates/12-kalshi-maker-reflexivity.md)).

**Lottery book**
PM Underwriting default (full price range) — edge ranker pulls to
85-99¢ extremes naturally, producing a 9:1 lottery payoff. See
[`../rd/candidates/01-pm-underwriting-lottery.md`](../rd/candidates/01-pm-underwriting-lottery.md).

**Maker / Taker**
Maker = resting limit order (zero fees on Kalshi). Taker = crossing the
spread (`0.07 × P × (1-P)` per side). The paper book uses a
conservative round-trip-taker assumption.

**PIT (Point-In-Time) pricing**
Market price at 50% of contract duration (`open_time + (close_time -
open_time) / 2`), found via DuckDB ASOF join. Used to avoid the
terminal-price convergence bias. Imported from sibling project
`kalshi-autoagent` lesson.

**Sell-yes / Buy-yes**
Position sides on a Kalshi binary. Sell-yes wins if the event doesn't
happen; buy-yes wins if it does. The scanner determines side by
comparing `actual_rate` to `implied_mid`.

**Shadow rejection ledger**
Append-only parquet log of candidates rejected by the 28-day expiry
screen (and other structural screens). Enables counterfactual replay.
See [`../components/shadow-rejection-ledger.md`](../components/shadow-rejection-ledger.md).

**σ-table**
Pre-computed JSON at `data/calibration/sigma_table.json` with per-(category,
side, 5¢ bin) σ from the walk-forward test set. Used by equal-σ sizing.

**Subseries / Series**
Subseries = event_ticker minus its trailing segment (e.g., NFL game
sub-markets). Series = `series_ticker` (e.g., `KXNFL`). Both used as
diversity-cap dimensions in the portfolio.

---

## Trading concepts (cross-strategy)

**Drawdown (DD)**
Peak-to-trough decline in NAV. Expressed as % of peak.
`max_drawdown = (peak − trough) / peak`.

**HWM (High-Water Mark)**
Highest NAV reached. Used to compute drawdown.

**MVT (Marginal Value Theorem)**
Charnov 1976. Optimality model from foraging ecology: leave a patch
when in-patch capture rate drops to the long-run average across the
habitat. Adapted to scanner admission as a rolling-quality threshold.
See [`../components/mvt-rolling-threshold.md`](../components/mvt-rolling-threshold.md).

**NAV (Net Asset Value)**
Current book value: `nav = initial_nav + sum(realized_pnl over closed
positions)`. Open positions valued at committed capital (book value),
not mark-to-market. Default initial NAV is $10,000 per book.

**Sharpe ratio**
Risk-adjusted return: `mean(returns) / std(returns)`, annualized.

**Slippage**
Difference between expected and actual fill price. Modeled by using
executable prices (yes_bid for sell_yes, 1−no_bid for buy_yes) rather
than mids in the scanner.

**Spread**
`ask − bid`. Minimum round-trip transaction cost.

**Walk-forward validation**
Train/test split with multiple non-overlapping windows. Required before
any strategy promotes from stat-exam to backtest. See
[`methodology.md`](methodology.md).

**Win rate (WR)**
`winning_trades / total_trades`. Misleading in isolation — a 30% WR
strategy with 5:1 payoff is excellent. Always interpret alongside
payoff ratio and Sharpe.

---

## Crypto / venue-specific

**BTC-PERP, ETH-PERP, SOL-PERP**
Hyperliquid perpetual-futures tickers. API `candleSnapshot` requires
the base name without `-PERP` suffix; `HyperliquidClient._coin()`
strips it.

**Funding rate**
Periodic payment between longs and shorts on a perpetual future,
keeping perp price anchored to spot. Hyperliquid pays hourly. Positive
funding = longs pay shorts. Available as full-history time series.

**HIP-3**
Hyperliquid Improvement Proposal 3 — builder-deployed perpetuals via
Dutch auction. Anyone with ≥500K HYPE staked can launch. Live since
2025-10-13. See [`external-landscape.md`](external-landscape.md).

**HIP-4**
Hyperliquid event perpetuals. Co-developed with Kalshi. Testnet 2026-02-02;
mainnet TBD. See [`external-landscape.md`](external-landscape.md).

**L2 / Order book**
Full bid/ask depth at each price level. Hyperliquid exposes current
state via API but no historical L2. Kalshi orderbook is retention-gated
with no historical alternative — must capture forward in time.

**Mid price**
`(bid + ask) / 2`. Reference price for spread calculations.

**Perp / Perpetual future**
Derivative tracking an underlying price without expiry. Funding-rate
mechanism keeps it anchored to spot.

---

## Stages and verdicts

(See [`stages-and-verdicts.md`](stages-and-verdicts.md) for the full spec.)

**Stage** — where in the pipeline: `ideation`, `deep-dive`,
`statistical-examination`, `backtest`, `paper-portfolio`,
`live-trading`, `rejected`, `absorbed`.

**Verdict** — judgment at the current stage: `pending`,
`needs-iteration`, `viable`, `non-viable`.

**Non-viable** has a high bar: requires explicit reasoning that no
variant, overlay, or scale change could rescue the candidate.

**Absorbed** — the candidate's finding was folded into another strategy
(e.g., #10 vol surface absorbed into PM Phase 5 hedging overlay). Not
the same as `rejected`.

---

## OHLCV & data layer

**Candle / Bar**
One time-unit of OHLCV data (Open, High, Low, Close, Volume). "4h
bar" = four hours summarized.

**OHLCV**
Open, High, Low, Close, Volume — five standard columns of
candlestick data. Plus a UTC `timestamp` column.

**Parquet partition / tree**
Hive-style date-partitioned parquet at `data/kalshi/{trades,markets}/date=YYYY-MM-DD/part.parquet`.
Trivially pruneable for time-bounded queries; immutable once written.

**Watermark**
Per-ticker timestamp + trade-id state file at `data/kalshi/_state.json`
that the incremental Kalshi pull uses to know where to resume. Separate
from the data itself.

---

## System concepts (current)

**Append-only memory / decision log**
Every component, candidate, and charter doc has a decision log at the
bottom. Append-only — never edit prior entries; reversals are new
entries that reference the prior one.

**Append-only candidate catalog**
`docs/rd/candidates/` — every strategy idea ever logged stays. Verdict
changes; the file doesn't disappear.

**launchd**
macOS process management. Used for the daily data cron and the
paper-trade daemons (one plist per book). See
[`runbook.md`](runbook.md).

**Paper portfolio / Paper trading**
Forward-testing a strategy against live market data without placing
real orders. Three books currently in production, all paper: PM
Underwriting Lottery, PM Underwriting Insurance (both
`kalshi_binary` schema), and Elder Triple-Screen vol_q4 perps
(`crypto_perp` schema).

**Pre-registration**
Locking hyperparameters + pass criteria + null benchmark *in code*
before the test fold runs. Not allowed to retro-fit. See
[`methodology.md`](methodology.md).

---

## Legacy (Elder-track and original-design terms)

These are preserved for historical context. The Elder track was
[rejected as non-viable](../rd/candidates/00-elder-templates.md);
these terms appear in archived docs and the orchestrator/templates
modules but are not used in current PM Underwriting work.

**Bar index `[legacy]`**
Zero-based row index in an OHLCV DataFrame. Elder-track concept.

**DD penalty `[legacy]`**
Quadratic drawdown penalty applied to Elder template scoring. Formula:
`((max_dd − 0.20) / 0.10)² × 200`.

**Direction (LONG/SHORT) `[legacy]`**
Trade direction in Elder templates. Defined as `Direction(str, Enum)`
in `base.py`.

**Discovery loop / Inner loop / Outer loop `[legacy]`**
Two-loop architecture. Inner = LLM proposes configs, harness evaluates.
Outer = human review + new template authoring. Falsified for
continuous-parameter search; codified into [axiom 5](../charter/axioms.md)
that LLMs are categorical reasoners, not optimizers.

**EMA, Force Index, MACD, RSI, Stochastic `[legacy]`**
Technical indicators used in Elder triple-screen template. See archived
template code if relevant.

**Iron Triangle `[legacy]`**
Elder-track risk framework: entry + stop + target with ≥2:1 R:R, 2%
NAV risk per trade. Replaced by equal-σ sizing in PM Underwriting.

**Profit Factor (PF) `[legacy]`**
`gross_profit / gross_loss`. Hard gate PF > 1.3 in Elder track. Not used
in current work.

**R:R / Reward-Risk Ratio `[legacy]`**
`reward / risk`. Elder hard minimum 2:1.

**Resistance / Support `[legacy]`**
Price levels in Elder false-breakout template.

**Sample Penalty `[legacy]`**
Penalty in Elder scoring for backtest n_trades < 20.

**Signal `[legacy]`**
Elder-template trade instruction dataclass. Fields: bar_index,
direction, entry, stop, target.

**Sliding Window `[legacy]`**
The last N backtest results injected into the LLM prompt in the Elder
inner loop. Not used in current work.

**Stagnation `[legacy]`**
Elder-track inner-loop heuristic: N consecutive failures → perturb the
prompt.

**Template `[legacy]`**
Elder-track strategy module pattern. `triple_screen` and
`false_breakout` were the two implementations.

**TF (Timeframe) `[legacy]`**
Elder-track concept: bar duration. Multiple TFs used in triple_screen
(higher TF for trend, lower for entry).

**Vertical Slice `[legacy]`**
Elder-track implementation milestone (Units 1-3): download data →
template → backtest.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (initial) | Glossary created from Elder-track design docs | Canonical definitions for inner-loop concepts |
| 2026-04-25 | Restructured + added PM Underwriting, calibration, stages-and-verdicts sections | Reorg; legacy Elder-track terms preserved with `[legacy]` marker |
