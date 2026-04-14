# Scoring Function

The scoring function is the single number that ranks one strategy configuration against another. It determines what the system optimizes for. The sibling projects (kalshi-autoagent, options-autoagent) proved that composite scoring (per-trade quality) and EV scoring (total dollars) produce opposite optimal configs from the same strategy code. This is not a side effect — it is the central design decision.

Prospector uses **sequential NAV simulation** as its primary score. This approach was the final, most battle-tested form in both sibling projects, chosen because it is the closest proxy to "would this actually make money in a real account."

---

## Primary Score: NAV Simulation

Simulate a trading account through all trades produced by a backtest run, in chronological order. The score reflects whether the strategy grows a realistic account while surviving drawdowns.

### Formula

```
score = pct_return × 200 − dd_penalty − sample_penalty
```

Where:

| Term | Definition |
|---|---|
| `pct_return` | `(final_nav − initial_nav) / initial_nav` |
| `dd_penalty` | `0` if `max_drawdown ≤ 0.20`, else `((max_drawdown − 0.20) / 0.10)² × 200` |
| `sample_penalty` | `0` if `n_trades ≥ 20`, else `(20 − n_trades) × 10` |

### NAV Parameters

| Parameter | Value | Rationale |
|---|---|---|
| `NAV_INITIAL` | $10,000 | Realistic starting capital for crypto perps |
| `NAV_CEILING` | $20,000 | 2× initial. Prevents unrealistic compounding from inflating scores. |
| `NAV_CATASTROPHIC` | $5,000 | 50% of initial. If NAV drops below this, `score = −1000`. |
| `RISK_PER_TRADE` | 0.02 | 2% of current NAV (Iron Triangle rule from strategy templates). |
| `MAX_MONTHLY_RISK` | 0.06 | 6% monthly drawdown cap. Circuit breaker halts trading for the month. |

### Position Sizing

Each trade is sized by the Iron Triangle: `position_size = (nav × RISK_PER_TRADE) / (entry − stop)`. This is enforced by the harness, not proposed by the model. The position size determines how many units the simulated account can afford, and the trade P&L scales accordingly.

If `entry − stop` produces a position size that exceeds available NAV, the trade is skipped (logged as "insufficient capital," not counted as a loss).

### Drawdown Calculation

Track the high-water mark of the simulated NAV across all trades. Max drawdown = `(peak − trough) / peak`. The penalty is quadratic above the 20% soft threshold, meaning a 30% drawdown is penalized 4× more than a 25% drawdown. This strongly discourages strategies that experience deep equity troughs even if they recover.

### Catastrophic Floor

If the simulated NAV drops below `NAV_CATASTROPHIC` at any point during the sequence, the run is immediately terminated and scored −1000. This prevents the optimization loop from exploring regions of strategy space that risk account destruction.

---

## Hard Gates (Pass/Fail Before Scoring)

These filters reject a backtest run before it reaches the scoring formula. A rejected run is logged to the ledger with a `rejected` status and the reason, but receives no numeric score.

| Gate | Threshold | Rationale |
|---|---|---|
| Minimum trades | ≥ 20 | Sibling projects proved that fewer trades produce unreliable scores. Small samples inflate metrics. |
| Profit factor | > 1.3 | `gross_profit / gross_loss`. Below 1.3, the edge is too thin to survive transaction costs and slippage in live execution. |
| Reward:risk ratio | ≥ 2:1 on every trade | Enforced by the harness per the Iron Triangle. Trades that don't meet this are never entered. |

---

## Diagnostic Metrics (Logged, Not Optimized)

These metrics are computed for every backtest run and included in the sliding window the model sees. They help the model reason about *why* a config scored the way it did, but they are not part of the objective function.

| Metric | Definition | Why it matters for reasoning |
|---|---|---|
| `sharpe_ratio` | Annualized `mean(trade_returns) / std(trade_returns)` | Risk-adjusted quality. High score + low Sharpe = lucky streak. |
| `profit_factor` | `gross_profit / gross_loss` | Edge magnitude. Thin PF with many trades = fragile. |
| `win_rate` | `winning_trades / total_trades` | Intuitive but misleading alone — a 30% WR strategy with 5:1 payoff ratio is excellent. |
| `total_return` | `final_nav − initial_nav` | Absolute dollars. Useful for sanity-checking the score. |
| `max_drawdown` | `(peak − trough) / peak` | Account survival risk. |
| `avg_trade_pnl` | `total_pnl / n_trades` | Per-trade edge in dollars. |
| `avg_hold_bars` | Mean bars held per position | Strategy character: scalp vs. swing vs. position. |
| `n_trades` | Total trades executed | Volume. Too few = unreliable. Too many on thin edge = fragile. |
| `monthly_returns` | Per-month P&L series | Consistency over time. Reveals regime dependence. |
| `longest_drawdown` | Bars from peak to recovery | Psychological and capital cost of waiting. |

---

## Sliding Window Format

The model sees the last N results (N = TBD, likely 10–20) formatted as a table in its prompt. Each row contains the config that was tried and its outcomes:

```
Run  Template         Securities  Score   Sharpe  PF    WR     Trades  MaxDD   Rationale (abbreviated)
---  ---------------  ----------  ------  ------  ----  -----  ------  ------  ----------------------
147  triple_screen    BTC,ETH     84.3    1.42    2.1   58%    47      12%     Wider EMA spread on daily/4h
146  channel_fade     ETH         -1000   —       0.8   34%    23      52%     Catastrophic: tight channel on volatile asset
145  false_breakout   BTC,SOL     41.7    0.89    1.6   62%    31      18%     30-bar range, 1 confirmation bar
144  triple_screen    BTC         rejected (PF 1.1)                            Force index on 1h — too noisy
```

The model uses this history to decide which region of the space to explore next. The rationale field is the model's own text from its previous proposal, reflected back to it.

---

## Transaction Cost Model

Scoring is only meaningful if the backtest models realistic execution costs. The harness applies these before computing any P&L:

| Cost | Model | Notes |
|---|---|---|
| Maker fee | Per Hyperliquid fee schedule | Limit orders. Currently 0.01% for most tiers. |
| Taker fee | Per Hyperliquid fee schedule | Market orders. Currently 0.035% for most tiers. |
| Slippage | TBD — calibrate from Hyperliquid orderbook data | Start conservative (e.g., 0.05% per side), refine with real depth data. |
| Funding rate | Actual historical funding rates applied to positions held across funding intervals | Significant for strategies holding > 8 hours. |

The slippage assumption is a hard-coded harness parameter, not a model-tunable knob. If the model could set slippage to zero, it would.

---

## Design Decisions and Rationale

**Why NAV simulation over Sharpe or composite:** Sharpe alone doesn't account for position sizing or drawdown trajectory. Composite scoring (PPT × weight + WR × weight) was the first approach in both sibling projects and was abandoned because it doesn't answer the question that matters: does this strategy grow an account? NAV simulation answers that question directly.

**Why a quadratic drawdown penalty:** Linear penalties don't sufficiently discourage deep drawdowns. A 40% drawdown is not twice as bad as a 20% drawdown — it requires a 67% gain to recover, and it destroys the trader's ability to stay in the game. The quadratic penalty encodes this nonlinearity.

**Why the NAV ceiling:** Without a cap, a strategy that gets lucky early compounds unrealistically, inflating the score. The $53B theoretical score in options-autoagent was a measurement artifact from uncapped compounding. The ceiling keeps scores grounded in realistic account trajectories.

**Why sample-size penalty rather than just a gate:** The gate at 20 trades is a hard minimum. The penalty adds a gradient: 19 trades is slightly penalized, 10 trades is heavily penalized. This discourages the model from proposing narrow configs that generate barely enough trades to pass the gate.

---

## Open Questions

- **NAV parameters.** $10K initial is a starting point. Adjust based on Hyperliquid minimum order sizes and realistic account sizes for the target pairs.
- **Slippage calibration.** The 0.05% starting assumption needs validation against real Hyperliquid orderbook depth for the target pairs.
- **Funding rate impact.** Need to determine whether historical funding rate data is available from Hyperliquid's API at sufficient granularity.
- **Walk-forward integration.** The score above applies to a single backtest window. Walk-forward validation (train score vs. test score) is a separate layer that detects overfitting. Define whether the optimization target is the test-window score, an average across windows, or the worst-window score.
- **Monthly return consistency.** Consider whether to add a consistency bonus (e.g., penalize strategies where > 50% of total return comes from a single month). Not included yet to avoid premature complexity.
