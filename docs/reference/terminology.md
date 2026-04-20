# Terminology

Definitions for all jargon used in the Prospector codebase and design documents.

---

## Trading Concepts

**Bar / Candle**
One time unit of OHLCV data. A "4h bar" represents four hours of trading, summarized as Open, High, Low, Close, Volume. "Bar index" (`bar_index`) is the zero-based row index in a DataFrame.

**Close** (of a bar)
The last traded price during the bar's time window. Strategy logic fires on the close — signals are generated after a bar completes, not intra-bar.

**Direction**
Whether a trade is LONG (buy, profit if price rises) or SHORT (sell, profit if price falls). Defined as `Direction(str, Enum)` in `base.py`.

**Drawdown (DD)**
Peak-to-trough decline in account value (NAV). Expressed as a percentage of the peak. `max_drawdown = (peak - trough) / peak`. See also: DD penalty.

**DD Penalty**
The quadratic penalty applied to the primary score when max drawdown exceeds 20%. Formula: `((max_dd - 0.20) / 0.10)² × 200`. Quadratic, not linear, because deep drawdowns are disproportionately costly (capital destruction, psychological cost). Below 20% = no penalty.

**EMA (Exponential Moving Average)**
A moving average that weights recent data more than older data. Controlled by a `span` (period) parameter. Used for trend detection (slow EMA slope) and value zone identification (fast EMA). Implemented with `pd.Series.ewm(span=N, adjust=False).mean()`.

**Entry**
The intended execution price for a trade. For LONG: price to buy at. For SHORT: price to sell at. Part of the Iron Triangle.

**Force Index**
Elder's momentum oscillator: `close.diff() × volume`. Measures force behind price moves. 2-period EMA of force index (`force_index_2`) is the preferred entry oscillator in Triple Screen.

**Funding Rate**
A periodic payment between long and short holders in perpetual futures, keeping the futures price anchored to spot. Positive funding = longs pay shorts; negative = shorts pay longs. Applied every 8 hours on Hyperliquid. Significant for strategies holding positions overnight. Historical funding data availability from Hyperliquid API is an open question.

**HWM (High-Water Mark)**
The highest NAV value reached by the simulated account at any point. Used to calculate drawdown: `drawdown = (HWM - current_nav) / HWM`.

**Iron Triangle**
The three-legged risk framework enforced on every trade: (1) entry price, (2) stop-loss, (3) profit target, with ≥ 2:1 reward:risk ratio and 2% NAV risk per trade. Named for the three sides that form a trade's geometry. Enforced by `Signal.__post_init__` (geometry) and the harness (sizing).

**L2 / Level 2 / Order Book**
The full depth of buy (bid) and sell (ask) orders at each price level. "L2 snapshot" = point-in-time capture of the top N levels per side. Used to model slippage (the cost of walking the book). Hyperliquid only exposes the current book state via API — no historical L2 is available.

**MACD (Moving Average Convergence Divergence)**
Momentum indicator: difference between fast EMA and slow EMA, plus a "signal line" (EMA of the difference) and "histogram" (MACD minus signal). MACD Histogram measures momentum acceleration/deceleration.

**Mid Price**
The average of best bid and best ask: `(bid + ask) / 2`. Used as a reference price for spread calculations and range width normalization.

**NAV (Net Asset Value)**
The current simulated account value, including unrealized P&L. Replaces informal terms like "bankroll" or "equity." `NAV_INITIAL = $10,000`, `NAV_CEILING = $20,000`, `NAV_CATASTROPHIC = $5,000`.

**OHLCV**
Open, High, Low, Close, Volume — the five standard columns of candlestick bar data. All DataFrames in Prospector must include these plus a `timestamp` column (UTC, timezone-aware).

**Perp / Perpetual Future**
A derivative that tracks an underlying asset's price without an expiry date. Hyperliquid trades crypto perps (e.g., BTC-PERP, ETH-PERP). Perps use a funding rate mechanism to stay anchored to spot price.

**PIT Pricing (Point-In-Time)**
Prices as they were at a specific historical moment, not current prices. The kalshi-autoagent bug used stale terminal prices instead of PIT prices, inflating backtest scores from 45 to 140. The harness must use only prices that were knowable at the time of the bar.

**Profit Factor (PF)**
`gross_profit / gross_loss`. A PF of 1.0 means the strategy broke even before costs. Hard gate: PF > 1.3 required to pass to scoring.

**R:R / Reward-Risk Ratio**
`reward / risk = |target - entry| / |entry - stop|`. Hard minimum: 2:1 (every trade must offer at least twice as much potential gain as potential loss). Enforced at signal generation time and checked again by the harness. `MIN_REWARD_RISK = 2.0` in `base.py`.

**Resistance**
A price level where selling pressure historically has stopped upward moves. In `false_breakout`, resistance = `max(high)` over the lookback window.

**RSI (Relative Strength Index)**
Momentum oscillator ranging 0–100. Below 30 is traditionally "oversold" (entry for longs); above 70 is "overbought" (entry for shorts).

**Sharpe Ratio**
Risk-adjusted return: `mean(trade_returns) / std(trade_returns)`, annualized. Captures consistency, not just magnitude. High score + low Sharpe = lucky streak on few trades.

**Signal**
A trade instruction produced by a strategy template. Fields: `bar_index`, `direction`, `entry`, `stop`, `target`. Implemented as a frozen dataclass in `base.py` with geometry validation in `__post_init__`.

**Slippage**
The difference between the expected execution price and the actual fill price, caused by insufficient liquidity at the target price. The harness models slippage as a flat cost per trade (initially 0.05% per side). Calibrated from live orderbook data as it accumulates.

**Spread**
The difference between the best ask and best bid: `ask - bid`. Represents the minimum transaction cost for a round-trip trade. `spread_pct = spread / mid_price`.

**Stochastic**
Momentum oscillator: `(close - N-bar low) / (N-bar high - N-bar low) × 100`. Below 20 is oversold; above 80 is overbought.

**Stop (Stop-Loss)**
The price at which a losing trade is exited to cap the loss. For LONG: stop < entry. For SHORT: stop > entry. Part of the Iron Triangle.

**Support**
A price level where buying pressure historically has stopped downward moves. In `false_breakout`, support = `min(low)` over the lookback window.

**Target (Profit Target)**
The price at which a winning trade is exited to take profit. For LONG: target > entry. For SHORT: target < entry. Part of the Iron Triangle.

**TF (Timeframe)**
The duration of a single bar: `1h` (1 hour), `4h` (4 hours), `1d` (1 day), etc. Multiple timeframes are used by Triple Screen: higher-TF for trend direction, lower-TF for entry timing.

**Walk-Forward Validation**
A testing methodology that uses rolling train/test windows advancing through time. Prevents overfitting by ensuring the strategy is always tested on data it was never trained on. Required before any strategy is promoted to paper trading.

**Win Rate (WR)**
`winning_trades / total_trades`. Misleading in isolation — a 30% WR strategy with 5:1 payoff is excellent. Always interpret alongside profit factor and R:R.

---

## System Concepts

**Append-Only Ledger**
The SQLite database recording every discovery loop iteration. Records are never updated or deleted. The sliding window reads from this. Lessons from sibling projects: never truncate; don't react to < 20 iterations.

**Cold Start**
The first iteration of the discovery loop, when the sliding window is empty. The orchestrator uses a baseline prompt with no historical results injected.

**Diversity Rule**
The orchestrator rejects proposals that are too similar to recent ones. Same template + same securities + normalized Euclidean parameter distance < 0.15 = duplicate. Different templates are always diverse.

**Hard Gate**
A pass/fail filter applied before scoring. Current gates: ≥ 20 trades, PF > 1.3, ≥ 2:1 R:R per trade. Runs that fail a gate are logged with status `rejected` and no numeric score.

**Inner Loop**
The automated discovery process: LLM proposes → harness evaluates → result logged → repeat. The small model (13B) is the inner loop's intelligence. Runs continuously in the background.

**Iron Triangle**
See under Trading Concepts above.

**launchd**
macOS process management system (analogous to systemd on Linux). Used to keep the orderbook poller running persistently and to schedule the nightly OHLCV refresh. Plist files live in `~/Library/LaunchAgents/`.

**LoRA (Low-Rank Adaptation)**
A parameter-efficient fine-tuning technique that trains small adapter matrices on top of a frozen base model. Used periodically (not the primary feedback mechanism) to encode long-term lessons that don't fit in the context window. The sliding window is the primary feedback signal.

**Outer Loop**
Human + Claude/Opus review of accumulated results. Identifies structural gaps, authors new strategy templates, widens parameter ranges. Happens infrequently (not automated). The inner loop searches within the current space; the outer loop expands the space.

**Paper Portfolio / Paper Trading**
Forward-testing a promoted config against live market data without placing real orders. Validates that backtest results hold on unseen data before risking capital.

**Sample Penalty**
A penalty applied when a backtest produces fewer than 20 trades. Formula: `(20 - n_trades) × 10`. The hard gate rejects at <20 trades; the penalty adds a gradient so barely-passing configs score lower than configs with many trades.

**Sliding Window**
The last N backtest results (typically 10–20) formatted as a table and injected into the LLM's prompt. The model uses this to reason about which regions of strategy space are exhausted vs. unexplored. The primary feedback mechanism (LoRA is secondary).

**Stagnation**
When the inner loop produces N consecutive failures (all same template, all rejected, or declining scores). Triggers perturbation: inject a directive into the prompt to explore a different template or parameter region.

**Template**
A human-authored Python module implementing one strategy pattern. Takes OHLCV data + config dict, returns a list of Signals. Contains all execution logic. The LLM never writes template code — it only selects which template to use and what parameters to pass.

**Two-Loop Pattern**
The architecture proven in kalshi-autoagent: inner loop (small model) searches within a defined space; outer loop (human/Claude) expands the space when the inner loop saturates. Neither does the other's job.

**Vertical Slice**
Units 1–3 of the implementation plan: download data → implement one template → run a scored backtest. Validates the core pipeline without LLM involvement. All data quality, template, and harness bugs surface here before the loop adds complexity.

---

## Hyperliquid-Specific

**BTC-PERP, ETH-PERP, SOL-PERP**
The initial POC security universe. Hyperliquid uses the suffix format (e.g., `BTC-PERP`), but the API `candleSnapshot` endpoint requires the base name without the suffix (e.g., `BTC`). `HyperliquidClient._coin()` handles this stripping.

**candleSnapshot**
Hyperliquid REST API endpoint for historical OHLCV data. Max 5000 candles per request. Returns bars as dicts with keys `t` (open time ms), `T` (close time ms), `o`, `h`, `l`, `c`, `v`, `n` (trade count), `i` (interval), `s` (symbol).

**l2Book**
Hyperliquid WebSocket subscription for live order book data. Returns current book state only — no historical data. Top 10 levels per side stored as parquet.

**merge_asof**
A pandas function for time-based approximate joins. Used in `triple_screen.py` to align higher-timeframe trend values to lower-timeframe bars: for each lower-TF bar, it finds the most recent higher-TF bar with a timestamp ≤ the short-TF bar's timestamp.

**POC (Proof of Concept)**
The initial limited scope: 3 symbols (BTC-PERP, ETH-PERP, SOL-PERP), 2 templates, 1 backtest harness, 1 LLM loop. Validates the architecture before expanding.
