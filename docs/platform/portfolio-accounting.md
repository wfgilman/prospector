# Portfolio Accounting

> `src/prospector/strategies/pm_underwriting/portfolio.py` — the SQLite-
> backed paper book. NAV, cash, locked risk, fees, sizing math, and the
> entry-time constraint hierarchy.

---

## State model

```
nav         = initial_nav + sum(realized_pnl over closed positions)
cash        = nav - locked_risk
locked_risk = sum(risk_budget over open positions)
```

`nav` only changes when positions resolve. Open positions are valued at
their committed capital (book value), not mark-to-market. This is standard
for hold-to-maturity binary contracts and matches how the
capital-constrained simulator (Phase 2b) accounted.

---

## Per-position economics

For a Kalshi binary contract priced at `P` (in [0, 1]):

| Side | Risk per contract | Reward per contract |
|---|---|---|
| `sell_yes` | `1 - P` | `P` |
| `buy_yes` | `P` | `1 - P` |

Resolution P&L (before fees):

| Side | Result = "no" | Result = "yes" |
|---|---|---|
| `sell_yes` | +contracts × reward (WIN) | −contracts × risk (LOSS) |
| `buy_yes` | −contracts × risk (LOSS) | +contracts × reward (WIN) |

The contracts count is `max(1, int(risk_budget / risk_per_contract))`. The
actual risk recorded on the position is `contracts × risk_per_contract`,
which may be slightly below the requested `risk_budget` due to integer
rounding — preserved in the ledger for accounting accuracy.

---

## Fees

Modeled as a round-trip Kalshi taker fee charged at entry:

```
fees_paid = KALSHI_ROUND_TRIP_FEE_FACTOR × P × (1 - P) × contracts
```

where `KALSHI_ROUND_TRIP_FEE_FACTOR = 0.14` (= 2 × 0.07 per side).

Stored as `fees_paid` on each position; deducted from `realized_pnl` on
resolution. Voided markets refund fees so realized_pnl stays 0.

This is **conservative** — assumes taker on both sides. Maker fills are
free on Kalshi. If real execution lands as maker (the strategy is not
latency-sensitive; resting limit orders at calibration-implied fair value
is natural), the fee model overstates costs.

For fee math by component, see [`../components/fee-modeling-kalshi.md`](../components/fee-modeling-kalshi.md).

---

## Sizing — equal-σ (risk parity)

Per [equal-σ sizing](../components/equal-sigma-sizing.md):

```
risk_budget = book_σ_target × NAV / (σ_i × √N_target)
clipped by max_position_frac × NAV
```

where `σ_i` is the per-bet σ for the (category, side, 5¢ bin) stratum
looked up from the σ-table.

A candidate with no σ at any fallback level (bin → pooled (category, side)
→ aggregate) is rejected at entry — a signal we can't size is a signal we
don't trust.

---

## Constraint hierarchy at entry

Applied in order in `enter()`. First failing check raises `RejectedEntry`
with a reason. Other candidates in the tick still get their turn.

| # | Constraint | Default | Purpose |
|---|---|---|---|
| 1 | `risk_budget ≤ max_position_frac × nav` | 1% | Per-position safety net (defends against pathologically small σ) |
| 2 | `risk_budget ≤ cash` | n/a | Hard budget constraint |
| 3 | `event_risk(event_ticker) + risk ≤ max_event_frac × nav` | 5% | Per-event correlation cap |
| 4 | `bin_risk(side, bin_low) + risk ≤ max_bin_frac × nav` | 15% | Per (side, 5¢ bin) tail-concentration cap |
| 5 | `open_in_event < max_positions_per_event` | 1 | One position per event |
| 6 | `open_in_subseries < max_positions_per_subseries` | 1 | Subseries = event_ticker minus trailing segment |
| 7 | `open_in_series < max_positions_per_series` | 3 | Series = series_ticker (e.g. KXNFL) |
| 8 | `trades_today < max_trades_per_day` | 20 | Daily throughput cap |
| 9 | `not has_open_position(ticker)` | n/a | One open position per market max |

Dollar caps (1-4) are primary; count caps (5-7) are derivative guardrails
against correlated stacking that the dollar caps don't catch.

---

## Schema

### `positions` (one row per trade)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `ticker`, `event_ticker`, `series_ticker` | TEXT | Unique constraint on `ticker` for `status='open'` |
| `category` | TEXT | sports / crypto / weather / etc. |
| `side` | TEXT | sell_yes / buy_yes |
| `contracts` | INTEGER | Integer count |
| `entry_price` | REAL | In (0, 1) |
| `risk_budget`, `reward_potential` | REAL | Dollar values |
| `edge_pp` | REAL | Fee-adjusted edge in pp |
| `entry_time`, `expected_close_time` | TEXT (ISO) | UTC |
| `status` | TEXT | open / closed / voided |
| `close_price`, `close_time`, `realized_pnl`, `market_result` | (nullable) | Set on resolution |
| `fees_paid` | REAL | Round-trip taker fee model |

Indexes: `(status)`, `(event_ticker, status)`, `(entry_time)`, unique
`(ticker)` where `status = 'open'`.

### `daily_snapshots` (one row per UTC date)

| Column | Type | Notes |
|---|---|---|
| `snapshot_date` | TEXT PK | ISO date |
| `nav`, `cash`, `locked_risk` | REAL | End-of-day book state |
| `open_positions`, `trades_today` | INTEGER | |
| `realized_pnl_today` | REAL | Sum of realized_pnl on positions closing today |

Written by `snapshot_today()` at the end of each tick.

### `clv_snapshots` (one row per market fetch)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `ticker` | TEXT | |
| `snapshot_time` | TEXT (ISO) | |
| `yes_bid`, `yes_ask`, `last_price` | REAL (nullable) | |
| `market_status` | TEXT | |

Written by `monitor.sweep()` on every fetched market. Used by [CLV
instrumentation](../components/clv-instrumentation.md) to compute the
closing-line value per resolved position.

### `meta` (key/value)

Currently stores `initial_nav` (set on first DB creation).

---

## Schema migrations

`_apply_migrations()` runs on every `PaperPortfolio()` open. Pattern:

- New tables: `CREATE TABLE IF NOT EXISTS` in the schema script
- New columns: inspect `PRAGMA table_info(...)`, add with `ALTER TABLE`,
  optionally backfill

This lets running daemons pick up schema changes at next launchd tick
without downtime. The CLV table was added this way 2026-04-24.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-20 | Initial schema + Kelly sizing + flat caps | Phase 3 launch |
| 2026-04-21 | Equal-σ sizing replaces fractional Kelly | Per-bet σ varies 30× across bins; Kelly under-sized by 4-14× ([sizing reevaluation](../components/equal-sigma-sizing.md) §why) |
| 2026-04-21 | `max_bin_frac=0.15` replaces `max_category_frac=0.20` | Finer grain matches σ-table key |
| 2026-04-23 | Expiry screen (28d) + shadow ledger | Long-dated markets don't return signal in time to validate |
| 2026-04-24 | `clv_snapshots` table added | CLV measurement requires per-market bid/ask snapshots over time |
| 2026-04-25 | Doc consolidated into platform/ | Was distributed across portfolio.py docstring + plan.md + sizing-reevaluation |
