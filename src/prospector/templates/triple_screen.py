"""
Template: triple_screen — Pullback to Value

Trade in the direction of the higher-timeframe trend, enter on a
counter-trend pullback on the lower timeframe.

Three screens:
  1. Higher-TF EMA slope  → determines trend direction (long/short/flat)
  2. Lower-TF oscillator  → times entry (oversold for longs, overbought for shorts)
  3. Entry technique       → buy one tick above the previous bar's high (long)
                             or sell one tick below the previous bar's low (short)

Config keys (all required unless marked optional):
    long_tf              "1w" | "1d"
    short_tf             "1d" | "4h" | "1h"  (must be shorter than long_tf)
    slow_ema             int 15–50
    fast_ema             int 5–25  (must be < slow_ema)
    oscillator           "stochastic" | "rsi" | "force_index_2"
    osc_entry_threshold  float 0–100

Data contract:
    Caller must pass two DataFrames: one for each timeframe.
    Both must contain columns: timestamp, open, high, low, close, volume.
    Rows must be sorted ascending by timestamp.
    The short-TF DataFrame is the entry timing frame.
    The long-TF DataFrame is the trend filter frame.
"""

from __future__ import annotations

import pandas as pd

from prospector.templates.base import Direction, MIN_REWARD_RISK, Signal, validate_ohlcv

# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _stochastic_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
    low_min = df["low"].rolling(period).min()
    high_max = df["high"].rolling(period).max()
    denom = high_max - low_min
    return ((df["close"] - low_min) / denom.replace(0, float("nan"))) * 100


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _force_index_2(df: pd.DataFrame) -> pd.Series:
    """2-period EMA of force index (Elder's preferred oscillator for entry)."""
    raw = df["close"].diff() * df["volume"]
    return raw.ewm(span=2, adjust=False).mean()


def _oscillator(df: pd.DataFrame, name: str) -> pd.Series:
    if name == "stochastic":
        return _stochastic_k(df)
    if name == "rsi":
        return _rsi(df["close"])
    if name == "force_index_2":
        return _force_index_2(df)
    raise ValueError(f"Unknown oscillator: {name!r}")


# ---------------------------------------------------------------------------
# Trend alignment
# ---------------------------------------------------------------------------

def _trend(df_long: pd.DataFrame, slow_ema_period: int, fast_ema_period: int) -> pd.Series:
    """
    Return a Series with values: 1 (up), -1 (down), 0 (flat).

    Trend is considered up when the slow EMA is rising (current > previous).
    Flat is not explicitly coded here; the caller filters on non-zero values.
    """
    slow = _ema(df_long["close"], slow_ema_period)
    slope = slow.diff()
    return slope.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def _align_long_tf_to_short(
    df_long: pd.DataFrame,
    df_short: pd.DataFrame,
) -> pd.Series:
    """
    For each short-TF bar, look up the most recent completed long-TF bar trend value.
    Returns a Series indexed like df_short.
    """
    # We'll use merge_asof to align timestamps.
    trend_long = _trend(df_long, slow_ema_period=1, fast_ema_period=1)  # placeholder; replaced below
    # This function is called with pre-computed trend passed in; see run().
    raise NotImplementedError("Use run() directly.")


def run(
    df_long: pd.DataFrame,
    df_short: pd.DataFrame,
    config: dict,
) -> list[Signal]:
    """
    Generate triple-screen signals.

    Args:
        df_long:  Higher-timeframe OHLCV, sorted ascending.
        df_short: Lower-timeframe OHLCV, sorted ascending.
        config:   Dict matching the triple_screen parameter schema.

    Returns:
        List of Signal objects, one per valid entry bar.
    """
    validate_ohlcv(df_long)
    validate_ohlcv(df_short)

    slow_ema_p = int(config["slow_ema"])
    fast_ema_p = int(config["fast_ema"])
    osc_name = config["oscillator"]
    osc_threshold = float(config["osc_entry_threshold"])

    if fast_ema_p >= slow_ema_p:
        raise ValueError("fast_ema must be < slow_ema")

    # --- Screen 1: higher-TF trend ---
    slow_ema_long = _ema(df_long["close"], slow_ema_p)
    trend_long = slow_ema_long.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    # Align long-TF trend to short-TF bars using last-known value.
    trend_aligned = pd.merge_asof(
        df_short[["timestamp"]].copy(),
        df_long[["timestamp"]].assign(trend=trend_long.values),
        on="timestamp",
        direction="backward",
    )["trend"].fillna(0).astype(int)

    # --- Screen 2: lower-TF oscillator ---
    osc = _oscillator(df_short, osc_name)
    fast_ema_short = _ema(df_short["close"], fast_ema_p)

    signals: list[Signal] = []

    for i in range(2, len(df_short)):
        trend = trend_aligned.iloc[i]
        if trend == 0:
            continue

        osc_val = osc.iloc[i]
        if pd.isna(osc_val):
            continue

        is_oversold = osc_val < osc_threshold
        is_overbought = osc_val > (100 - osc_threshold) if osc_name != "force_index_2" else osc_val > 0

        if trend == 1 and is_oversold:
            # Long: enter one tick above prior bar's high.
            entry = df_short["high"].iloc[i - 1] * 1.0001
            stop = df_short["low"].iloc[i - 5:i].min()
            value_zone = fast_ema_short.iloc[i]
            target = value_zone + (value_zone - stop) * MIN_REWARD_RISK
        elif trend == -1 and is_overbought:
            # Short: enter one tick below prior bar's low.
            entry = df_short["low"].iloc[i - 1] * 0.9999
            stop = df_short["high"].iloc[i - 5:i].max()
            value_zone = fast_ema_short.iloc[i]
            target = value_zone - (stop - value_zone) * MIN_REWARD_RISK
        else:
            continue

        if stop <= 0 or abs(entry - stop) < 1e-8:
            continue

        try:
            sig = Signal(
                bar_index=i,
                direction=Direction.LONG if trend == 1 else Direction.SHORT,
                entry=entry,
                stop=stop,
                target=target,
            )
        except ValueError:
            continue

        if sig.reward_risk_ratio >= MIN_REWARD_RISK:
            signals.append(sig)

    return signals
