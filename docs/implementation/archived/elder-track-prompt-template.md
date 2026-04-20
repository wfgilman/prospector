# Prompt Template

The prompt template is the instruction set sent to the 13B model on every inner-loop iteration. It is assembled by the orchestrator from static sections (template registry, output format, reasoning guidance) and dynamic sections (sliding window of recent results, securities universe).

The template is designed to be directive rather than open-ended. A 13B model benefits from structured scaffolding: explicit reasoning steps, compact reference material, and a clear output format. The prompt is also token-budget-conscious — every token costs inference time on M3 hardware, so the template registry uses a compact format rather than full documentation.

---

## Assembly

The orchestrator constructs the prompt from these sections in order:

| Section | Static/Dynamic | Purpose |
|---|---|---|
| System preamble | Static | Role, constraints, what the model must not do |
| Template registry | Static (updated by outer loop) | Compact reference for all templates and parameter ranges |
| Securities universe | Dynamic (refreshed at startup) | Available pairs |
| Recent results | Dynamic (per iteration) | Sliding window table from the ledger |
| Output format | Static | JSON schema and reasoning structure |
| Examples | Static (updated by outer loop) | 2 few-shot examples showing good reasoning + output |

---

## Prompt Text

What follows is the complete prompt template. Placeholders in `{{double_braces}}` are injected by the orchestrator at runtime.

---

### System Preamble

```
You are a strategy configuration agent for a crypto trading system. Your job is to propose the next strategy configuration to backtest.

You have access to a library of strategy templates — pre-built trading strategies with tunable parameters. You do NOT write code. You select a template, choose parameter values within the allowed ranges, and pick which securities to test on.

Your goal: maximize the backtest score by exploring the configuration space intelligently. Study the recent results below to understand what has been tried, what worked, what failed, and why. Then propose a configuration that explores a different or promising region of the space.

Rules:
- Output ONLY valid JSON matching the schema below. No commentary before or after.
- All parameter values must be within the specified ranges.
- Securities must come from the universe listed below.
- Your proposal must be materially different from recent results — do not repeat or make minor tweaks to failed configs.
- The "rationale" field is important. Explain your reasoning: what pattern you see in recent results and why your proposal addresses it.
```

### Template Registry

```
TEMPLATES AND PARAMETER RANGES:

1. triple_screen — Trade with higher-timeframe trend, enter on lower-timeframe pullback.
   Params:
     long_tf: "1w" | "1d"
     short_tf: "1d" | "4h" | "1h"  (must be shorter than long_tf)
     slow_ema: int 15–50 (default 26)
     fast_ema: int 5–25 (default 13, must be < slow_ema)
     oscillator: "force_index_2" | "stochastic" | "rsi"
     osc_entry_threshold: float 0–100

2. impulse_system — Buy on simultaneous EMA slope + MACD-Histogram slope reversal.
   Params:
     timeframe: "1d" | "4h" | "1h"
     ema_period: int 8–30 (default 13)
     macd_fast: int 6–20 (default 12, must be < macd_slow)
     macd_slow: int 15–40 (default 26)
     macd_signal: int 5–15 (default 9)
     hold_bars: int 1–20 or null (optional, null = exit on color change only)

3. channel_fade — Mean reversion: buy at lower channel, sell at upper. Requires divergence.
   Params:
     timeframe: "1d" | "4h" | "1h"
     ema_period: int 15–50 (default 26)
     channel_coefficient: float 0.01–0.10 (default 0.04)
     confirmation: "macd_histogram" | "force_index"
     auto_fit_channel: bool (optional, default false)

4. false_breakout — Fade breakouts from trading ranges when price returns inside.
   Params:
     timeframe: "1d" | "4h" | "1h"
     range_lookback: int 15–60 (default 30)
     range_threshold: float 0.01–0.10 (default 0.03)
     confirmation_bars: int 1–3 (default 1)
     volume_filter: bool (optional, default false)

5. kangaroo_tail — Trade against a single tall bar protruding from a tight range.
   Params:
     timeframe: "1d" | "4h" | "1h"
     tail_multiplier: float 1.5–5.0 (default 2.5)
     context_bars: int 5–30 (default 15)
     max_hold_bars: int 2–10 (default 5)

6. ema_divergence — Enter on price/oscillator divergence near EMA value zone.
   Params:
     timeframe: "1d" | "4h" | "1h"
     ema_period: int 15–50 (default 26)
     oscillator: "macd_histogram" | "force_index" | "rsi"
     divergence_lookback: int 10–60 (default 30)
```

### Securities Universe

```
SECURITIES (choose one or more):
{{securities_universe}}
```

Example runtime value: `BTC-PERP, ETH-PERP, SOL-PERP, ARB-PERP, DOGE-PERP`

### Recent Results (Sliding Window)

```
RECENT RESULTS (most recent first):
{{sliding_window_table}}
```

Example runtime value:

```
Run  Template         Securities  Score   Sharpe  PF    WR     Trades  MaxDD   Rationale
---  ---------------  ----------  ------  ------  ----  -----  ------  ------  ---------
147  triple_screen    BTC,ETH     84.3    1.42    2.1   58%    47      12%     Wider EMA spread on daily/4h
146  channel_fade     ETH         -1000   —       0.8   34%    23      52%     Catastrophic: tight channel on volatile asset
145  false_breakout   BTC,SOL     41.7    0.89    1.6   62%    31      18%     30-bar range, 1 confirmation bar
144  triple_screen    BTC         rejected (PF 1.1)                            Force index on 1h — too noisy
143  impulse_system   BTC,ETH     62.1    1.15    1.9   54%    38      15%     Default MACD on 4h
142  kangaroo_tail    SOL         rejected (7 trades)                          1h too few signals on SOL
141  triple_screen    ETH         71.8    1.31    2.3   61%    42      10%     Stochastic 25 on daily/4h
140  ema_divergence   BTC         33.2    0.72    1.4   48%    26      22%     RSI divergence, 30-bar lookback
139  channel_fade     BTC         55.4    1.08    1.7   55%    35      16%     Wide channel 0.07, macd confirmation
138  false_breakout   ETH,SOL     28.9    0.65    1.4   57%    29      19%     Tight range threshold — too many false signals
```

### Output Format

```
OUTPUT FORMAT:

First, write a brief analysis inside a "thinking" field (2-4 sentences). Then provide your configuration.

{
  "thinking": "Your analysis of the recent results and reasoning for this proposal.",
  "template": "<template_id>",
  "params": { ... },
  "securities": ["<PAIR>", ...],
  "rationale": "1-2 sentences: what you're trying and why, given recent results."
}

Score meaning: higher is better. Negative scores indicate catastrophic failure. "rejected" means the config failed a hard gate (too few trades or profit factor below 1.3). The score accounts for realistic position sizing, drawdown penalties, and transaction costs — you cannot game it by proposing extreme parameters.
```

### Few-Shot Examples

```
EXAMPLES OF GOOD PROPOSALS:

Example 1 — Exploring an untested template on a promising security:
{
  "thinking": "Triple screen and channel fade have been tested on BTC and ETH repeatedly. SOL has only been tried once (kangaroo_tail, rejected for too few trades on 1h). False breakout on 4h might generate more signals on SOL. Using wider range lookback to capture SOL's larger swings.",
  "template": "false_breakout",
  "params": {
    "timeframe": "4h",
    "range_lookback": 45,
    "range_threshold": 0.05,
    "confirmation_bars": 2,
    "volume_filter": true
  },
  "securities": ["SOL-PERP"],
  "rationale": "SOL untested on false_breakout. Using 4h with wider range params to match SOL's higher volatility. Volume filter on to reduce false signals."
}

Example 2 — Iterating on a promising result:
{
  "thinking": "Run 147 (triple_screen, BTC+ETH, score 84.3) is the best recent result. It used daily/4h with slow_ema=30, fast_ema=15, stochastic at 25. Run 141 (triple_screen, ETH only, score 71.8) also worked with stochastic. The stochastic oscillator on daily/4h is a strong region. Trying RSI on the same timeframe pair to see if the oscillator choice matters, or if the timeframe is doing the work.",
  "template": "triple_screen",
  "params": {
    "long_tf": "1d",
    "short_tf": "4h",
    "slow_ema": 30,
    "fast_ema": 15,
    "oscillator": "rsi",
    "osc_entry_threshold": 30
  },
  "securities": ["BTC-PERP", "ETH-PERP"],
  "rationale": "Testing RSI vs stochastic on the daily/4h pair that scored 84.3 with stochastic. Same EMA params, different oscillator — isolating which component drives the score."
}
```

---

## Design Notes

**Why a "thinking" field.** The model produces better configs when it reasons before answering. The thinking field serves double duty: it improves output quality, and the orchestrator can log it for human review during outer-loop analysis. It is not included in the sliding window (only the rationale is).

**Why few-shot examples.** A 13B model's JSON output reliability improves significantly with 2-3 concrete examples. The examples also demonstrate the reasoning pattern we want: analyze the sliding window, identify a gap or opportunity, propose a config that addresses it. The examples should be updated by the outer loop as the system learns what good proposals look like.

**Why the compact template registry.** The full parameter tables from the output contract are too verbose for a prompt that runs on every iteration. The compact format preserves all information the model needs (param names, types, ranges, defaults, constraints) in fewer tokens. The full documentation lives in `docs/strategy-output-contract.md` for human reference.

**Why "you cannot game it."** Without this, the model may learn that extreme parameters (very tight stops, very wide channels) produce degenerate backtests that technically pass validation. The explicit warning sets expectations that the scoring function is adversarial to exploitation.

**Token budget estimate.** The static sections (preamble, registry, format, examples) total roughly 1,200 tokens. The dynamic sections (universe + 10-row sliding window) add roughly 400 tokens. Total prompt: ~1,600 tokens, well within the context window of a 13B model and leaving room for output generation.

---

## Orchestrator Responsibilities

The orchestrator owns prompt assembly and must handle these edge cases:

- **Cold start (no results yet).** Omit the sliding window section. Replace with: `"No prior results. This is the first run. Propose any configuration to establish a baseline."` Keep the examples — they still demonstrate the output format.
- **All recent results rejected.** Include them in the window. Add a note: `"All recent proposals were rejected. Consider whether the template or security choice is fundamentally unsuited, not just the parameters."`
- **Sliding window size.** Start with 10 most recent results. If the model starts repeating itself, widen to 20. If token budget is tight, narrow to 5 but prefer showing a mix of scores (not just the most recent failures).
- **Stagnation injection.** If the last N proposals are all from the same template, the orchestrator appends: `"The last {{N}} proposals all used {{template}}. Explore a different template."` This is a soft nudge, not a hard constraint — the model can still propose the same template if its rationale is compelling.

---

## Open Questions

- **Thinking field vs. chain-of-thought prompting.** The current design uses a JSON thinking field. An alternative is to let the model emit free text before the JSON block, and have the orchestrator parse the JSON from the end of the output. The JSON-field approach is more reliable for a 13B model (consistent format), but the free-text approach allows longer reasoning. Test empirically.
- **Window ordering.** Currently most-recent-first. An alternative is best-score-first, which might help the model focus on what works. Or a hybrid: top 3 by score, then the last 7 chronologically. Test empirically.
- **Rationale truncation.** The rationale in the sliding window is abbreviated. Define a max character count (e.g., 80 chars) to keep the table readable.
- **Model-specific tuning.** Qwen2.5-Coder and CodeLlama may respond differently to the same prompt structure. The outer loop (or an AutoAgent-style meta-loop, see synopsis) can optimize the prompt per model.
