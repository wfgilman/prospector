# Prospector — Candidate Strategy Templates
## Derived from Alexander Elder, *The New Trading for a Living*

This document defines a set of strategy templates that Prospector's inner loop can instantiate, parameterize, and backtest. Each template is designed to be simple, rule-based, and expressible as executable code with a small number of tunable parameters.

---

## Foundational Concepts (Apply to All Strategies)

### The Iron Triangle (Every Trade)
Every strategy must produce three numbers before entering a trade:
1. **Entry price** — where to get in
2. **Stop price** — where to get out if wrong
3. **Target price** — where to take profits

The reward-to-risk ratio (target distance / stop distance) must be ≥ 2:1.

### The 2% Rule (Position Sizing)
Risk per trade must never exceed 2% of account equity. Position size = (Account × 0.02) / (Entry − Stop). This is non-negotiable and lives in the harness, not in the strategy.

### The 6% Rule (Monthly Drawdown Cap)
If total losses + open risk for the month reach 6% of account equity, stop trading until next month. This is a circuit breaker in the harness.

---

## Strategy 1: Triple Screen — Pullback to Value

**Core idea:** Trade in the direction of the higher-timeframe trend, enter on a counter-trend pullback in the lower timeframe.

**Parameters:**
- `long_tf`: Higher timeframe (e.g., weekly/daily)
- `short_tf`: Lower timeframe (e.g., daily/4h)
- `slow_ema`: Slow EMA period (default: 26)
- `fast_ema`: Fast EMA period (default: 13)
- `oscillator`: Which oscillator for entry timing (Force Index 2-period, Stochastic, RSI)
- `osc_buy_threshold`: Oversold level (e.g., Stochastic < 30, or Force Index < 0)
- `osc_sell_threshold`: Overbought level

**Rules:**
1. **Screen 1 (trend filter):** On `long_tf`, determine trend direction. If slow EMA is rising → only look for longs. If falling → only shorts. If flat → stand aside.
2. **Screen 2 (entry signal):** On `short_tf`, wait for oscillator to reach oversold (for longs) or overbought (for shorts) — a counter-trend wave.
3. **Screen 3 (entry technique):** Enter using average EMA penetration method: place buy order at (fast EMA − average downside penetration from past 4–6 pullbacks). Alternatively, buy one tick above previous bar's high.
4. **Stop:** Below most recent minor low (for longs).
5. **Target:** Value zone on `long_tf` chart, or upper channel line.

**Why it suits Prospector:** Highly mechanical. The three screens are independently computable. Multiple oscillator choices give the inner loop a search space without excessive complexity.

---

## Strategy 2: Impulse System — Momentum Entry on Color Change

**Core idea:** Buy when both EMA slope and MACD-Histogram slope turn bullish simultaneously. The system acts as a censorship filter: red bars prohibit buying, green bars prohibit shorting.

**Parameters:**
- `ema_period`: Fast EMA (default: 13)
- `macd_fast`, `macd_slow`, `macd_signal`: MACD parameters (default: 12, 26, 9)
- `hold_bars`: How many bars to hold if no exit signal (optional timeout)

**Rules:**
1. Color each bar:
   - **Green:** EMA rising AND MACD-Histogram rising → bullish impulse
   - **Red:** EMA falling AND MACD-Histogram falling → bearish impulse
   - **Blue:** Mixed → neutral
2. **Entry:** Buy when the first non-red bar appears after a red sequence (momentum reversal). Short when first non-green bar appears after green sequence.
3. **Exit:** When color changes against your position in either timeframe. Momentum traders exit immediately; swing traders can hold through blue bars but must exit on opposing color.
4. **Stop:** Below the low of the red bar sequence (for longs).

**Why it suits Prospector:** Binary color coding makes it trivially programmable. The "first bar after color change" entry is unambiguous. Produces many signals — good for a system that needs statistical significance.

---

## Strategy 3: Channel Fade — Mean Reversion from Extremes

**Core idea:** Prices oscillate around value. Buy when price touches the lower channel line, sell at the upper channel line.

**Parameters:**
- `ema_period`: Channel centerline EMA (default: 26)
- `channel_coefficient`: Channel width as % of EMA (start at 3–5%, auto-fit to contain 95% of bars over 100 periods)
- `confirmation_indicator`: MACD-Histogram or Force Index for divergence confirmation

**Rules:**
1. Draw channel: upper = EMA × (1 + coefficient), lower = EMA × (1 − coefficient).
2. **Buy signal:** Price touches or penetrates lower channel line AND confirmation indicator shows bullish divergence (shallower low than previous touch).
3. **Sell signal:** Price touches or penetrates upper channel line AND confirmation indicator shows bearish divergence.
4. **Hard rule:** Never buy above the upper channel line. Never short below the lower channel line.
5. **Target:** Opposite channel line, or EMA (value zone) for conservative targets.
6. **Stop:** Halfway through the penetration below the channel (tight stop — if the channel doesn't hold, get out fast).

**Why it suits Prospector:** Mean reversion strategies tend to work well in ranging markets, which crypto spends a lot of time in. The channel coefficient is a single parameter the inner loop can optimize per asset.

---

## Strategy 4: False Breakout Reversal

**Core idea:** Most breakouts from trading ranges fail. Professionals fade breakouts while amateurs chase them. Trade the reversal when price breaks out of a range and then returns.

**Parameters:**
- `range_lookback`: How many bars define the trading range (e.g., 20–50)
- `range_threshold`: Minimum range width as % of price
- `confirmation_bars`: How many bars price must spend back inside range to confirm false breakout (default: 1–2)

**Rules:**
1. Identify a trading range: price contained within a horizontal support/resistance zone for `range_lookback` bars.
2. **False downside breakout → Buy:** Price breaks below support, then closes back above support within `confirmation_bars`. Entry on the close back inside the range. Stop at the low of the false breakout.
3. **False upside breakout → Sell short:** Price breaks above resistance, then closes back below. Entry on the close back inside. Stop at the high of the false breakout.
4. **Confirmation:** Volume should be light on the breakout (weak conviction) and/or MACD-Histogram divergence present.
5. **Target:** Opposite side of the trading range.

**Why it suits Prospector:** Elder calls this one of his favorite setups. It has a naturally tight stop (the breakout extreme), producing good risk/reward ratios. The pattern is geometric and algorithmically detectable.

---

## Strategy 5: Kangaroo Tail Reversal

**Core idea:** A single very tall bar protruding from a tight price range signals a failed bull or bear raid. Trade against the tail.

**Parameters:**
- `tail_multiplier`: How many times taller than average bar height the tail bar must be (default: 2–3x)
- `context_bars`: Number of preceding bars to measure average height (default: 10–20)
- `bracket_requirement`: Bars immediately before and after the tail must be normal height

**Rules:**
1. Identify a kangaroo tail: a bar at least `tail_multiplier` × average bar height, bracketed by normal-height bars on both sides.
2. **Upward tail → Sell:** The tall bar protrudes upward. Short when the next bar confirms by trading near the base of the tail. Stop halfway up the tail (not at the tip — too much risk).
3. **Downward tail → Buy:** The tall bar protrudes downward. Buy when next bar confirms. Stop halfway down the tail.
4. **Important:** This is a short-term signal. Expect the move to play out within 3–5 bars on whatever timeframe you're using.

**Why it suits Prospector:** One of Elder's "short list of reliable formations." Extremely unambiguous to detect algorithmically — it's just a height comparison. The tight stop and short holding period make it good for generating many quick trades with clear outcomes.

---

## Strategy 6: EMA Slope + Divergence Combo

**Core idea:** Elder's personal favorite — combine a strong trend (rising/falling EMA) with a divergence on an oscillator to catch reversals near value.

**Parameters:**
- `ema_period`: Trend EMA (default: 22 or 26)
- `oscillator`: MACD-Histogram, Force Index, or RSI
- `divergence_lookback`: How far back to check for divergence peaks/troughs

**Rules:**
1. **Bullish setup:** Price makes a lower low while oscillator makes a higher low (bullish divergence). EMA is flat or beginning to turn up.
2. **Entry:** Buy when oscillator ticks up from its divergent low.
3. **Bearish setup:** Price makes a higher high while oscillator makes a lower high (bearish divergence). EMA is flat or beginning to turn down.
4. **Entry:** Short when oscillator ticks down from its divergent high.
5. **Stop:** Below the divergent low (for longs) or above the divergent high (for shorts).
6. **Target:** Value zone (between fast and slow EMA) initially, then upper/lower channel line.

**Why it suits Prospector:** Divergences are among the strongest signals in technical analysis per Elder. They are mathematically well-defined (comparing oscillator peaks to price peaks) and produce infrequent but high-quality signals.

---

## Risk Management Rules (Harness-Level, Not Strategy-Level)

These are enforced by the backtest harness regardless of which strategy is active:

| Rule | Value | Description |
|------|-------|-------------|
| Max risk per trade | 2% of equity | Iron Triangle — position sizing formula |
| Max monthly drawdown | 6% of equity | Circuit breaker — stop trading if hit |
| Min reward:risk ratio | 2:1 | Reject trades where target/stop < 2 |
| Max concurrent positions | TBD | Prevent overexposure |
| Slippage assumption | TBD (based on Hyperliquid data) | Realistic fill modeling |
| Transaction cost | Hyperliquid fee schedule | Maker/taker fees |

---

## Adaptation Notes for Crypto / Hyperliquid

Several Elder concepts need adjustment for 24/7 crypto markets:

1. **No opening/closing distinction.** Elder's insight about amateurs driving opens and professionals driving closes doesn't directly apply to crypto's continuous trading. Instead, consider session-based analysis (Asian/European/US trading hours) as a proxy.

2. **Volume patterns differ.** Crypto volume is distributed differently than equities. The inner loop should validate whether volume-based signals (Force Index, on-balance volume) behave similarly on crypto assets.

3. **Higher volatility.** Channel coefficients and stop distances will likely need to be wider for crypto. The inner loop should auto-calibrate channel width per asset.

4. **Funding rates.** Hyperliquid perpetuals have funding rates that act as a carrying cost. Strategies that hold positions for extended periods need to account for funding drag.

5. **Leverage.** Available but dangerous. Start with 1x (no leverage). The harness should enforce this until strategies are proven profitable on paper.

6. **No general market indicators.** NH-NL, A/D line, and other breadth indicators don't exist for crypto in the same way. The inner loop may need to construct proxies (e.g., percentage of top-100 tokens above their 50-day MA).

---

## Implementation Priority

Start with **Strategy 1 (Triple Screen)** and **Strategy 4 (False Breakout)**. These are Elder's most proven approaches, they have clear mechanical rules, and they produce enough signals to generate meaningful backtest data. Add the remaining strategies once the harness and feedback loop are working.