"""
Funding-cost tests.

Verify the per-trade funding integration:
  - LONG with positive funding rate → positive cost (position pays)
  - SHORT with positive funding rate → negative cost (position receives)
  - empty hold window → zero cost
  - notional + rate-sum math is what we documented
"""

from __future__ import annotations

import pandas as pd

from prospector.harness.engine import TradeRecord
from prospector.harness.funding import funding_cost, funding_costs
from prospector.templates.base import Direction, Signal


def _trade(direction: Direction, entry_bar: int = 0, exit_bar: int = 4,
           entry_price: float = 100.0, units: float = 10.0) -> TradeRecord:
    """Construct a TradeRecord with valid Iron-Triangle prices."""
    if direction == Direction.LONG:
        sig = Signal(
            bar_index=entry_bar, direction=Direction.LONG,
            entry=entry_price, stop=entry_price - 1, target=entry_price + 5,
        )
    else:
        sig = Signal(
            bar_index=entry_bar, direction=Direction.SHORT,
            entry=entry_price, stop=entry_price + 1, target=entry_price - 5,
        )
    return TradeRecord(
        signal=sig, entry_bar=entry_bar, exit_bar=exit_bar,
        exit_reason="target", entry_price=entry_price,
        exit_price=entry_price + (3 if direction == Direction.LONG else -3),
        units=units, gross_pnl=10.0,
        transaction_cost=0.0, net_pnl=10.0,
        nav_before=10_000.0, nav_after=10_010.0,
        hold_bars=exit_bar - entry_bar,
    )


def _ohlcv(n: int = 24) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"),
        "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n,
        "volume": [1.0] * n,
    })


def _funding(rate: float, n: int = 24) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"),
        "funding_rate": [rate] * n,
    })


def test_long_pays_funding_when_rate_positive() -> None:
    ohlcv = _ohlcv()
    funding = _funding(0.0001)  # 1 bp/hr
    trade = _trade(Direction.LONG, entry_bar=0, exit_bar=10, entry_price=100, units=10)
    # entry=ts[0], exit=ts[10] → 10 hours of funding integration
    # notional = 10 × 100 = 1000; sum of rates = 10 × 0.0001 = 0.001
    # cost = 1000 × 0.001 × 1 = 1.0
    cost = funding_cost(trade, ohlcv, funding)
    assert cost == 1.0


def test_short_receives_funding_when_rate_positive() -> None:
    ohlcv = _ohlcv()
    funding = _funding(0.0001)
    trade = _trade(Direction.SHORT, entry_bar=0, exit_bar=10, entry_price=100, units=10)
    cost = funding_cost(trade, ohlcv, funding)
    assert cost == -1.0


def test_empty_hold_window_returns_zero() -> None:
    ohlcv = _ohlcv()
    funding = _funding(0.0001)
    trade = _trade(Direction.LONG, entry_bar=5, exit_bar=5)  # zero-duration
    assert funding_cost(trade, ohlcv, funding) == 0.0


def test_funding_costs_preserves_order() -> None:
    ohlcv = _ohlcv()
    funding = _funding(0.0001)
    trades = [
        _trade(Direction.LONG, entry_bar=0, exit_bar=5),
        _trade(Direction.SHORT, entry_bar=5, exit_bar=15),
    ]
    costs = funding_costs(trades, ohlcv, funding)
    # First: long, 5 hours, notional 1000, rate 5×0.0001=0.0005 → cost = 0.5
    # Second: short, 10 hours, notional 1000, rate 0.001 → cost = -1.0
    assert costs == [0.5, -1.0]
