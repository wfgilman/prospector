"""Backtest harness: NAV simulation, scoring, and walk-forward validation."""

from prospector.harness.engine import (
    DEFAULT_CONFIG,
    BacktestConfig,
    BacktestResult,
    TradeRecord,
    compute_score,
    run_backtest,
)
from prospector.harness.walk_forward import WalkForwardFold, WalkForwardResult, run_walk_forward

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "DEFAULT_CONFIG",
    "TradeRecord",
    "WalkForwardFold",
    "WalkForwardResult",
    "compute_score",
    "run_backtest",
    "run_walk_forward",
]
