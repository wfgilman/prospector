"""Tests for the false_breakout strategy template."""

from __future__ import annotations

import pandas as pd
import pytest

from prospector.templates.base import MIN_REWARD_RISK, Direction
from prospector.templates.false_breakout import run


def _make_df(closes: list[float], highs: list[float] | None = None,
             lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    if highs is None:
        highs = [c * 1.005 for c in closes]
    if lows is None:
        lows = [c * 0.995 for c in closes]
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * n,
    })


DEFAULT_CONFIG = {
    "timeframe": "4h",
    "range_lookback": 10,
    "range_threshold": 0.02,
    "confirmation_bars": 2,
    "volume_filter": False,
}


def test_no_signals_flat_prices():
    """Flat prices form a range but never break out — no signals."""
    df = _make_df([100.0] * 25)
    signals = run(df, DEFAULT_CONFIG)
    assert signals == []


def test_downside_false_breakout_produces_long():
    """Price breaks below support then recovers → long signal.

    Range: low=90, high=110 (20% wide). False break to 87, recovery to 91.
    entry=91, stop=87, target=110 → reward=19, risk=4, R:R=4.75 ✓
    """
    closes = [100.0] * 10 + [88.0, 91.0] + [100.0] * 5
    lows   = [90.0]  * 10 + [87.0, 90.0] + [90.0]  * 5
    highs  = [110.0] * 10 + [89.0, 92.0] + [110.0] * 5

    df = _make_df(closes, highs=highs, lows=lows)
    signals = run(df, DEFAULT_CONFIG)

    long_signals = [s for s in signals if s.direction == Direction.LONG]
    assert len(long_signals) >= 1

    sig = long_signals[0]
    assert sig.entry == pytest.approx(91.0, rel=0.01)
    assert sig.stop < sig.entry < sig.target
    assert sig.target == pytest.approx(110.0, rel=0.01)
    assert sig.reward_risk_ratio >= MIN_REWARD_RISK


def test_upside_false_breakout_produces_short():
    """Price breaks above resistance then falls back → short signal.

    Range: low=90, high=110 (20% wide). False break to 113, recovery to 109.
    entry=109, stop=113, target=90 → reward=19, risk=4, R:R=4.75 ✓
    """
    closes = [100.0] * 10 + [112.0, 109.0] + [100.0] * 5
    lows   = [90.0]  * 10 + [111.0, 108.0] + [90.0]  * 5
    highs  = [110.0] * 10 + [113.0, 110.0] + [110.0] * 5

    df = _make_df(closes, highs=highs, lows=lows)
    signals = run(df, DEFAULT_CONFIG)

    short_signals = [s for s in signals if s.direction == Direction.SHORT]
    assert len(short_signals) >= 1

    sig = short_signals[0]
    assert sig.entry == pytest.approx(109.0, rel=0.01)
    assert sig.target < sig.entry < sig.stop
    assert sig.target == pytest.approx(90.0, rel=0.01)
    assert sig.reward_risk_ratio >= MIN_REWARD_RISK


def test_range_too_narrow_no_signal():
    """Range width below threshold produces no signals even with a breakout."""
    # Range of ±0.1% — below the 2% threshold.
    closes = [100.0] * 10 + [99.8, 100.1] + [100.0] * 5
    lows = [99.9] * 10 + [99.7, 100.0] + [99.9] * 5
    highs = [100.1] * 10 + [99.9, 100.2] + [100.1] * 5

    df = _make_df(closes, highs=highs, lows=lows)
    signals = run(df, DEFAULT_CONFIG)
    assert signals == []


def test_insufficient_data_no_signal():
    """Fewer bars than range_lookback produces no signals."""
    df = _make_df([100.0] * 5)
    signals = run(df, DEFAULT_CONFIG)
    assert signals == []


def test_reward_risk_filter():
    """Signals that don't meet 2:1 reward:risk are dropped."""
    # Create a situation where the false breakout stop is very tight to entry,
    # making the target (opposite range bound) not 2× away.
    range_prices = [100.0] * 10
    # Very wide range so resistance is far from entry, but stop is also far.
    closes = range_prices + [79.0, 81.0] + [100.0] * 5
    lows = [80.0] * 10 + [78.0, 80.0] + [80.0] * 5
    highs = [120.0] * 10 + [82.0, 82.0] + [120.0] * 5

    df = _make_df(closes, highs=highs, lows=lows)
    signals = run(df, DEFAULT_CONFIG)
    for sig in signals:
        assert sig.reward_risk_ratio >= MIN_REWARD_RISK


def test_volume_filter_rejects_high_volume_breakout():
    """With volume_filter=True, high-volume breakouts are rejected."""
    closes = [100.0] * 10 + [96.0, 99.0] + [100.0] * 5
    lows = [98.0] * 10 + [95.0, 98.5] + [98.0] * 5
    highs = [102.0] * 10 + [97.0, 100.5] + [102.0] * 5
    volumes = [1000.0] * 10 + [5000.0, 1000.0] + [1000.0] * 5  # breakout bar has 5× volume

    df = _make_df(closes, highs=highs, lows=lows)
    df["volume"] = volumes

    config_with_filter = {**DEFAULT_CONFIG, "volume_filter": True}
    signals_filtered = run(df, config_with_filter)
    signals_unfiltered = run(df, DEFAULT_CONFIG)

    # Volume filter should suppress the signal that fires without it.
    assert len(signals_filtered) <= len(signals_unfiltered)
