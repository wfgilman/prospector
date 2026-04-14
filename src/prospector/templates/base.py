"""
Base types shared across all strategy templates.

A template is a pure function: given OHLCV data and a config dict, it returns
a list of Signal objects. No position sizing, no NAV tracking, no I/O.

The harness owns all execution concerns. Templates own only signal logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Signal:
    """
    A trade signal produced by a strategy template.

    All prices are in quote currency (USDC for Hyperliquid perps).
    bar_index refers to the row in the OHLCV DataFrame on which the signal
    fires — i.e. the bar whose close triggers entry.
    """

    bar_index: int           # Row index in the OHLCV DataFrame
    direction: Direction
    entry: float             # Intended entry price
    stop: float              # Stop-loss price
    target: float            # Profit target price

    def __post_init__(self) -> None:
        if self.entry <= 0 or self.stop <= 0 or self.target <= 0:
            raise ValueError("Signal prices must be positive")
        if self.direction == Direction.LONG:
            if not (self.stop < self.entry < self.target):
                raise ValueError(
                    f"LONG signal requires stop < entry < target, "
                    f"got stop={self.stop} entry={self.entry} target={self.target}"
                )
        else:
            if not (self.target < self.entry < self.stop):
                raise ValueError(
                    f"SHORT signal requires target < entry < stop, "
                    f"got target={self.target} entry={self.entry} stop={self.stop}"
                )

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk_ratio(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


# Minimum reward:risk ratio enforced by the harness (Iron Triangle rule).
MIN_REWARD_RISK = 2.0


def validate_ohlcv(df: pd.DataFrame) -> None:
    """Raise if a DataFrame is missing required OHLCV columns."""
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV DataFrame missing columns: {missing}")
    if df.empty:
        raise ValueError("OHLCV DataFrame is empty")
