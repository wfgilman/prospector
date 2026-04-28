"""
Funding-rate cost adjustment for Hyperliquid perp backtests.

The base `run_backtest` harness models trading fees + slippage but not the
hourly funding charge that Hyperliquid perps accrue. Funding can be a
material drag (or boost) on multi-bar holds, so this module applies a
post-hoc funding cost to each `TradeRecord` based on:

  - the OHLCV bar timestamps for entry_bar / exit_bar
  - the position's direction (LONG pays funding when rate > 0; SHORT
    receives when rate > 0)
  - the position's notional at entry (units × entry_price)
  - the per-hour funding-rate series for that coin

Funding cost per trade = sum over each hour in [entry_time, exit_time)
of (notional × funding_rate × side_sign), where side_sign = +1 for LONG
and −1 for SHORT.

Usage:
    funding_df = load_funding("BTC")
    costs = funding_costs(trades, ohlcv_df, funding_df)
    adjusted_pnls = [t.net_pnl - c for t, c in zip(trades, costs)]
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from prospector.harness.engine import TradeRecord
from prospector.templates.base import Direction

REPO_ROOT = Path(__file__).resolve().parents[3]
FUNDING_DIR = REPO_ROOT / "data" / "hyperliquid" / "funding"


def load_funding(coin_root: str) -> pd.DataFrame:
    """Load `<coin_root>.parquet` and return columns time + funding_rate."""
    safe = coin_root.upper()
    path = FUNDING_DIR / f"{safe}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No funding history for {coin_root}: {path}")
    df = pd.read_parquet(path)
    df = df[["time", "funding_rate"]].sort_values("time").reset_index(drop=True)
    return df


def funding_cost(
    trade: TradeRecord,
    ohlcv: pd.DataFrame,
    funding_df: pd.DataFrame,
) -> float:
    """
    Return the funding charge (positive = cost to position) for a single
    closed trade. Integrates funding across each whole hour in the hold
    window using `merge_asof` between bar timestamps and funding ticks.
    """
    if trade.exit_bar <= trade.entry_bar:
        return 0.0
    if funding_df.empty:
        return 0.0

    entry_ts = ohlcv["timestamp"].iloc[trade.entry_bar]
    exit_ts = ohlcv["timestamp"].iloc[trade.exit_bar]

    relevant = funding_df[
        (funding_df["time"] >= entry_ts) & (funding_df["time"] < exit_ts)
    ]
    if relevant.empty:
        return 0.0

    notional = trade.units * trade.entry_price
    side_sign = 1.0 if trade.signal.direction == Direction.LONG else -1.0
    rate_sum = float(relevant["funding_rate"].sum())
    return notional * rate_sum * side_sign


def funding_costs(
    trades: list[TradeRecord],
    ohlcv: pd.DataFrame,
    funding_df: pd.DataFrame,
) -> list[float]:
    """Compute per-trade funding costs in the same order as `trades`."""
    return [funding_cost(t, ohlcv, funding_df) for t in trades]
