# Strategy Output Contract

The output contract defines the JSON schema that the inner-loop LLM must produce on every iteration. It is the single interface between three system layers: the LLM (producer), the orchestrator (validator and router), and the backtest harness (consumer). If this contract is wrong, the layers cannot communicate; if it is ambiguous, the LLM will produce invalid configs that waste iterations.

The contract has two tiers: a **top-level envelope** that is the same for every proposal, and **per-template parameter schemas** that define the valid parameter space for each strategy template. The orchestrator validates both tiers before forwarding to the harness.

---

## Top-Level Envelope

```json
{
  "template": "<template_id>",
  "params": { },
  "securities": ["BTC-PERP", "ETH-PERP"],
  "rationale": "Short explanation of why this config is worth trying given recent results."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `template` | `string` | yes | One of the registered template IDs (see below). |
| `params` | `object` | yes | Template-specific parameters. Validated against the per-template schema. |
| `securities` | `array[string]` | yes | One or more Hyperliquid perpetual pairs to backtest. Min 1, max TBD. Must be from the allowed universe. |
| `rationale` | `string` | yes | 1-3 sentences. Why this config explores a different or promising region of the space. Logged to the ledger for sliding-window feedback and human review. |

### Validation rules (orchestrator)

1. `template` must match a registered template ID exactly.
2. `params` must pass the per-template schema: all required fields present, correct types, values within defined ranges.
3. `securities` must be non-empty and contain only symbols present in the allowed universe (defined by the data pipeline at startup).
4. `rationale` must be non-empty. No structural validation beyond that — it is free text for logging.
5. The complete config must be **materially different** from the last N proposals in the ledger (see diversity rules below).

---

## Template Registry

Each template has an ID, a set of required and optional parameters, and the parameter ranges the orchestrator enforces. The LLM sees this registry in its prompt.

---

### `triple_screen` — Pullback to Value

Trade in the direction of the higher-timeframe trend, enter on a counter-trend pullback in the lower timeframe.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `long_tf` | `string` | yes | `["1w", "1d"]` | — | Higher timeframe for trend determination |
| `short_tf` | `string` | yes | `["1d", "4h", "1h"]` | — | Lower timeframe for entry timing |
| `slow_ema` | `int` | yes | 15–50 | 26 | Slow EMA period (trend filter) |
| `fast_ema` | `int` | yes | 5–25 | 13 | Fast EMA period (value zone) |
| `oscillator` | `string` | yes | `["force_index_2", "stochastic", "rsi"]` | — | Oscillator for entry timing |
| `osc_entry_threshold` | `float` | yes | 0–100 | — | Oversold/overbought level for entry. Interpretation depends on oscillator (e.g., stochastic < 30, force_index < 0). |

**Constraint:** `fast_ema` < `slow_ema`. `short_tf` must be a shorter interval than `long_tf`.

---

### `impulse_system` — Momentum Entry on Color Change

Buy when both EMA slope and MACD-Histogram slope turn bullish simultaneously. Color-coded bar system.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `timeframe` | `string` | yes | `["1d", "4h", "1h"]` | — | Candle timeframe |
| `ema_period` | `int` | yes | 8–30 | 13 | EMA period for slope calculation |
| `macd_fast` | `int` | yes | 6–20 | 12 | MACD fast period |
| `macd_slow` | `int` | yes | 15–40 | 26 | MACD slow period |
| `macd_signal` | `int` | yes | 5–15 | 9 | MACD signal smoothing period |
| `hold_bars` | `int` | no | 1–20 | `null` | Optional max holding period. `null` = exit only on color change. |

**Constraint:** `macd_fast` < `macd_slow`.

---

### `channel_fade` — Mean Reversion from Extremes

Buy at the lower channel line, sell at the upper. Requires divergence confirmation.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `timeframe` | `string` | yes | `["1d", "4h", "1h"]` | — | Candle timeframe |
| `ema_period` | `int` | yes | 15–50 | 26 | Channel centerline EMA period |
| `channel_coefficient` | `float` | yes | 0.01–0.10 | 0.04 | Channel width as fraction of EMA value |
| `confirmation` | `string` | yes | `["macd_histogram", "force_index"]` | — | Indicator used for divergence confirmation |
| `auto_fit_channel` | `bool` | no | — | `false` | If `true`, override `channel_coefficient` with a value fitted to contain 95% of bars over the lookback. |

---

### `false_breakout` — Reversal on Failed Range Break

Fade breakouts from trading ranges when price returns inside the range.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `timeframe` | `string` | yes | `["1d", "4h", "1h"]` | — | Candle timeframe |
| `range_lookback` | `int` | yes | 15–60 | 30 | Number of bars to define the trading range |
| `range_threshold` | `float` | yes | 0.01–0.10 | 0.03 | Minimum range width as fraction of price |
| `confirmation_bars` | `int` | yes | 1–3 | 1 | Bars price must spend back inside range to confirm false breakout |
| `volume_filter` | `bool` | no | — | `false` | If `true`, require below-average volume on the breakout bar. |

---

### `kangaroo_tail` — Single-Bar Reversal

Trade against a single tall bar protruding from a tight range.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `timeframe` | `string` | yes | `["1d", "4h", "1h"]` | — | Candle timeframe |
| `tail_multiplier` | `float` | yes | 1.5–5.0 | 2.5 | How many times taller than average the tail bar must be |
| `context_bars` | `int` | yes | 5–30 | 15 | Lookback window for average bar height |
| `max_hold_bars` | `int` | yes | 2–10 | 5 | Maximum bars to hold (short-term signal) |

---

### `ema_divergence` — EMA Slope + Oscillator Divergence

Enter when a strong divergence between price and oscillator occurs near the EMA value zone.

| Parameter | Type | Required | Range | Default | Description |
|---|---|---|---|---|---|
| `timeframe` | `string` | yes | `["1d", "4h", "1h"]` | — | Candle timeframe |
| `ema_period` | `int` | yes | 15–50 | 26 | Trend EMA period |
| `oscillator` | `string` | yes | `["macd_histogram", "force_index", "rsi"]` | — | Oscillator for divergence detection |
| `divergence_lookback` | `int` | yes | 10–60 | 30 | How far back to scan for divergence peaks/troughs |

---

## Diversity Rules

The orchestrator rejects configs that are too similar to recent proposals. Two configs are considered duplicates if **all** of the following are true:

1. Same `template`.
2. Same `securities` (order-independent).
3. Parameter-vector distance below threshold — measured as normalized Euclidean distance across numeric params, where each param is scaled to [0, 1] within its valid range. Enum/bool params are 0 (same) or 1 (different). Threshold TBD empirically, starting at 0.15.

Different templates are always considered diverse regardless of parameter similarity.

---

## Example: Complete LLM Output

```json
{
  "template": "triple_screen",
  "params": {
    "long_tf": "1d",
    "short_tf": "4h",
    "slow_ema": 30,
    "fast_ema": 15,
    "oscillator": "stochastic",
    "osc_entry_threshold": 25
  },
  "securities": ["BTC-PERP", "ETH-PERP"],
  "rationale": "Previous triple_screen runs used force_index_2 on 1h with default EMAs — all had negative Sharpe. Switching to stochastic on 4h with wider EMA spread to capture longer pullbacks."
}
```

---

## Open Questions

- **~~Timeframe vocabulary.~~** Resolved. Hyperliquid provides `1h`, `4h`, `1d` (among others). The data pipeline stores all three. `1w` is theoretically available but not downloaded. Note: 1h data is capped at ~208 days due to the 5000-candle API limit.
- **Securities universe.** POC universe: BTC-PERP, ETH-PERP, SOL-PERP. Expand to top N by liquidity after the vertical slice is validated.
- **Diversity threshold.** 0.15 normalized distance is a starting point. Tune after observing how tightly the model clusters proposals in practice.
- **Multi-security behavior.** Does the harness backtest each security independently and aggregate results, or does the template see all securities simultaneously? Most templates are single-security; clarify for cross-security validation.
