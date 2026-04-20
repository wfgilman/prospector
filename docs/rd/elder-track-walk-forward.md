# Walk-Forward Validation — Findings

## What was done

The oracle random search (n=2000 iterations, `data/prospector_oracle.db`) found a maximum in-sample score of 192.5 and characterized the full configuration space:

- `false_breakout × 4h` was the highest-density "winning cell" (41.7% scored rate)
- `triple_screen × 4h/1d` was secondary but productive (28-32% scored rate)

To test whether these in-sample scores reflect genuine edge or overfitting to a specific time window, the top-10 configs were re-evaluated with `run_walk_forward` using both `n_folds=5` and `n_folds=3` via `scripts/walk_forward_top_configs.py`.

## Results

### 5-fold walk-forward (most stringent)

Of the top-10 in-sample configs (scores 154–192):
- **5 of 10 configs (all `false_breakout` and one `triple_screen × BTC`)**: zero folds scored; every fold fell below the 20-trade gate.
- **5 of 10 configs (all `triple_screen`)**: at most 1 scored fold out of 5, except run #303 with 4/5.
- **Score degradation on scored folds: 63–82% below in-sample.**

### 3-fold walk-forward (looser — ~1700 bars per fold)

| run_id | template | secs | in-sample | best fold mean | scored/N | degradation |
|---|---|---|---|---|---|---|
| 86  | false_breakout | ETH | 192.5 | — | 0/3 | — |
| 303 | triple_screen  | SOL | 169.9 | 98.7 | 2/3 | **−42%** |
| 1407| false_breakout | ETH | 168.4 | — | 0/3 | — |
| 67  | false_breakout | ETH | 168.2 | — | 0/3 | — |
| 786 | triple_screen  | BTC | 167.1 | — | 0/3 | — |
| 1676| triple_screen  | ETH | 162.3 | 60.3 | 2/3 | **−63%** |
| 395 | false_breakout | ETH | 161.6 | — | 0/3 | — |
| 501 | triple_screen  | ETH | 159.6 | 77.5 | 2/3 | **−51%** |
| 354 | triple_screen  | SOL | 157.9 | 88.2 | 1/3 | **−44%** |
| 21  | triple_screen  | SOL | 154.5 | 74.8 | 2/3 | **−52%** |

## Interpretation

### `false_breakout` — structurally overfit

Every `false_breakout` config in the top 10 produces exactly zero scored folds under walk-forward, at both 3 and 5 folds. Root cause: the template produces only ~40–50 trades across the full ~5000-bar history. Split into 3 folds, that is ~15 trades per fold — consistently below the 20-trade minimum gate. The strategy cannot be validated at any reasonable number of temporal slices; the full-sample score is a single observation from an undersampled distribution.

This invalidates the "winning cell" finding from the oracle. High in-sample scores for `false_breakout × 4h` were driven by trade clustering in favorable periods, not by a durable edge.

### `triple_screen` — degrades sharply, but shows signal

Most `triple_screen × 4h` configs produce ≥60 trades over the full dataset, which distributes better across folds. However:
- Mean holdout score is 42–63% below in-sample.
- At least one fold per config still rejects or catastrophically underperforms.
- Only run #303 (`triple_screen × SOL × 4h`, 4/5 scored folds) comes close to temporal consistency.

### Cross-cutting conclusion

**The random search optimized for in-sample score, which is a leaky proxy for durable edge.** The observed max score of ~192 is not a discovered edge — it is what you get when you sample 2000 random configurations and keep the one that happened to land on a favorable slice of history. The winning `false_breakout` cell is a statistical artifact of sparse signals × lucky periods.

This is exactly the failure mode that walk-forward validation is designed to surface, and it is surfacing it unambiguously.

## Implications for architecture

1. **Any score from the in-sample inner loop is suspect.** Before treating a config as "good," it must pass walk-forward with consistent scoring across ≥3 folds and mean degradation below a threshold (exact threshold TBD, but −50% on best-security is not usable).

2. **The 20-trade minimum gate is the binding constraint, not scoring.** Strategies that produce <60 trades over the full dataset cannot be validated across time. Either:
   - Tighten templates to generate more trades (shorter lookbacks, looser confirmation)
   - Shift to denser-signal templates (e.g. funding-rate arb, event-driven, cross-exchange mispricing)
   - Accept that these strategies need more history than we have (1h is capped at 208 days; 4h at 833 days)

3. **The LLM inner-loop thesis and the random-search inner-loop thesis are both falsified for this problem.** Random found the in-sample ceiling fast; walk-forward shows the ceiling is fiction. The bottleneck is not search efficiency — it is the signal-generating process of the templates themselves.

4. **Walk-forward should be folded into the harness-level gate, not run as a post-hoc script.** Proposals that pass the single-window backtest but fail walk-forward should be flagged as `overfit` rather than `scored`.

## Next steps

- Add a walk-forward validation stage to the backtest harness, and make `overfit` a first-class `BacktestResult.status`.
- Re-run the oracle and rank by walk-forward mean score rather than single-window score.
- In parallel, pursue the literature review on LLM-suited denser-signal strategies (funding-rate arb, event-driven, cross-exchange); the current Elder-derived templates may not be the right shape for the data available.

## How to reproduce

```bash
source .venv/bin/activate
PYTHONPATH=src python scripts/walk_forward_top_configs.py \
    --db data/prospector_oracle.db --top 10 --folds 3
```

Change `--folds` to 5 for the stricter view; change `--top` to see further down the ranking.
