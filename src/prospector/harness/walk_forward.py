"""
Walk-Forward Validation

Splits an OHLCV DataFrame into N equal consecutive folds and runs a backtest
on each fold independently. Reveals whether a strategy's performance is
consistent across time or concentrated in a single lucky period.

This is a temporal consistency check, not a traditional hyperparameter-search
walk-forward. The (template, config) pair is fixed; we evaluate whether it
holds up across all time windows in the dataset.

Usage:
    signals = false_breakout.run(df, config)
    wf = run_walk_forward(signals, df, n_folds=5)
    print(wf.avg_test_score, wf.consistent)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from prospector.harness.engine import (
    DEFAULT_CONFIG,
    BacktestConfig,
    BacktestResult,
    run_backtest,
)
from prospector.templates.base import Signal


@dataclass
class WalkForwardFold:
    """Result for a single fold of the walk-forward validation."""

    fold_index: int
    start_bar: int   # Inclusive start row in the original DataFrame
    end_bar: int     # Exclusive end row in the original DataFrame
    n_signals: int   # Signals falling within this fold's bar range
    result: BacktestResult


@dataclass
class WalkForwardResult:
    """Aggregate result of a walk-forward validation run."""

    folds: list[WalkForwardFold]
    n_folds: int
    n_scored_folds: int        # Folds with status="scored"
    avg_test_score: float      # Mean score across scored folds (nan if none)
    # Min score across all folds: rejected→-9999, catastrophic→-1000, scored→actual score
    worst_test_score: float
    score_std: float           # Std dev of scored fold scores (0.0 if < 2 scored folds)
    consistent: bool           # True if all scored folds have score > 0
    fold_scores: list[float] = field(default_factory=list)  # nan/-1000 for non-scored folds


def run_walk_forward(
    signals: list[Signal],
    df: pd.DataFrame,
    n_folds: int = 5,
    config: BacktestConfig = DEFAULT_CONFIG,
) -> WalkForwardResult:
    """
    Split df into n_folds equal consecutive windows and backtest each independently.

    Args:
        signals: Pre-generated signals from the full dataset. Signals are
                 filtered to each fold's bar range and bar indices are adjusted
                 to be relative to the fold's start row.
        df:      The same OHLCV DataFrame used to generate the signals.
        n_folds: Number of equal-size time windows to evaluate.
        config:  Backtest execution parameters (fees, risk, NAV bounds).

    Returns:
        WalkForwardResult with per-fold results and aggregate statistics.

    Notes:
        No data leakage: templates only use past bars in their lookback windows.
        Filtering pre-generated signals by bar_index and adjusting indices is
        equivalent to re-running the template on each fold's slice, because
        templates are stateless and only look at data up to the current bar.

        Walk-forward does not guarantee a train/test split within each fold.
        It answers a different but equally important question: "Does this
        config produce similar results across all time periods?"
    """
    n_bars = len(df)
    if n_folds < 1:
        raise ValueError(f"n_folds must be >= 1, got {n_folds}")
    if n_folds > n_bars:
        raise ValueError(f"n_folds ({n_folds}) exceeds number of bars ({n_bars})")

    fold_size = n_bars // n_folds
    folds: list[WalkForwardFold] = []

    for fold_idx in range(n_folds):
        start = fold_idx * fold_size
        # Last fold absorbs any remainder bars
        end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else n_bars

        # Slice the DataFrame for this fold; reset index so iloc[0] = fold start
        fold_df = df.iloc[start:end].reset_index(drop=True)

        # Filter and re-index signals falling within [start, end)
        fold_signals = []
        for s in signals:
            if start <= s.bar_index < end:
                # Adjust bar_index to be relative to the fold's start row
                fold_signals.append(
                    Signal(
                        bar_index=s.bar_index - start,
                        direction=s.direction,
                        entry=s.entry,
                        stop=s.stop,
                        target=s.target,
                    )
                )

        result = run_backtest(fold_signals, fold_df, config)
        folds.append(WalkForwardFold(
            fold_index=fold_idx,
            start_bar=start,
            end_bar=end,
            n_signals=len(fold_signals),
            result=result,
        ))

    # Aggregate statistics
    scored = [f for f in folds if f.result.status == "scored"]
    n_scored = len(scored)

    scored_scores = [f.result.score for f in scored]
    avg_score = sum(scored_scores) / n_scored if n_scored > 0 else float("nan")

    if n_scored >= 2:
        mean_s = avg_score
        score_std = math.sqrt(sum((s - mean_s) ** 2 for s in scored_scores) / n_scored)
    else:
        score_std = 0.0

    consistent = n_scored > 0 and all(s > 0 for s in scored_scores)

    # worst_test_score: map non-scored to sentinel values for comparability
    all_scores = []
    for f in folds:
        if f.result.status == "scored":
            all_scores.append(f.result.score)
        elif f.result.status == "catastrophic":
            all_scores.append(-1000.0)
        else:  # rejected
            all_scores.append(-9999.0)
    worst_score = min(all_scores) if all_scores else float("nan")

    return WalkForwardResult(
        folds=folds,
        n_folds=n_folds,
        n_scored_folds=n_scored,
        avg_test_score=avg_score,
        worst_test_score=worst_score,
        score_std=score_std,
        consistent=consistent,
        fold_scores=all_scores,
    )
