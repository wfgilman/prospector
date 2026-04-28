"""
Template: ema_divergence — Elder Strategy 6 (EMA + oscillator divergence combo)

Bullish setup (LONG):
    Price prints a lower low (over `divergence_lookback`) while the
    oscillator prints a higher low. Enter when the oscillator ticks up
    from its divergent low.

Bearish setup (SHORT): symmetric — price higher high, oscillator lower high.

Stop:   below the divergent low (LONG) / above the divergent high (SHORT)
Target: value zone — the slow EMA at entry, plus the fast/slow EMA span as
        a stretch target if the value zone leaves headroom. Concretely we
        use: target = ema + reward_floor × risk in the trade direction,
        where reward_floor = MIN_REWARD_RISK = 2.

Config keys:
    timeframe              "1h" | "4h" | "1d"
    ema_period             int  15–50
    oscillator             "rsi" | "macd_hist" | "force_index_2"
    divergence_lookback    int  10–50
    min_separation         int  3–15   (min bars between the two extremes)
    confirm_window         int  1–5    (bars to wait for oscillator turn)
"""

from __future__ import annotations

import pandas as pd

from prospector.templates.base import MIN_REWARD_RISK, Direction, Signal, validate_ohlcv


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _macd_hist(close: pd.Series) -> pd.Series:
    macd = _ema(close, 12) - _ema(close, 26)
    sig = _ema(macd, 9)
    return macd - sig


def _force_index_2(df: pd.DataFrame) -> pd.Series:
    raw = df["close"].diff() * df["volume"]
    return raw.ewm(span=2, adjust=False).mean()


def _oscillator(df: pd.DataFrame, name: str) -> pd.Series:
    if name == "rsi":
        return _rsi(df["close"])
    if name == "macd_hist":
        return _macd_hist(df["close"])
    if name == "force_index_2":
        return _force_index_2(df)
    raise ValueError(f"Unknown oscillator: {name!r}")


def _local_min(series: pd.Series, idx: int, half_window: int = 2) -> bool:
    if idx - half_window < 0 or idx + half_window >= len(series):
        return False
    v = series.iloc[idx]
    if pd.isna(v):
        return False
    window = series.iloc[idx - half_window: idx + half_window + 1]
    return v == window.min()


def _local_max(series: pd.Series, idx: int, half_window: int = 2) -> bool:
    if idx - half_window < 0 or idx + half_window >= len(series):
        return False
    v = series.iloc[idx]
    if pd.isna(v):
        return False
    window = series.iloc[idx - half_window: idx + half_window + 1]
    return v == window.max()


def run(df: pd.DataFrame, config: dict) -> list[Signal]:
    validate_ohlcv(df)

    period = int(config["ema_period"])
    osc_name = config["oscillator"]
    lookback = int(config["divergence_lookback"])
    min_sep = int(config["min_separation"])
    confirm_window = int(config.get("confirm_window", 3))

    ema = _ema(df["close"], period)
    osc = _oscillator(df, osc_name)
    lows = df["low"]
    highs = df["high"]

    signals: list[Signal] = []
    warmup = max(period, 26, lookback) + min_sep + confirm_window

    # Track most-recent confirmed lows/highs in price + oscillator.
    last_low_idx: int | None = None
    last_high_idx: int | None = None

    for i in range(warmup, len(df) - confirm_window):
        if _local_min(lows, i):
            if last_low_idx is not None and (i - last_low_idx) >= min_sep \
                    and (i - last_low_idx) <= lookback:
                # Bullish divergence: lower low in price, higher low in oscillator
                if (lows.iloc[i] < lows.iloc[last_low_idx]
                        and osc.iloc[i] > osc.iloc[last_low_idx]):
                    # Wait up to confirm_window bars for oscillator to tick up.
                    for j in range(i + 1, min(i + 1 + confirm_window, len(df))):
                        if osc.iloc[j] > osc.iloc[i]:
                            entry = float(df["close"].iloc[j])
                            stop = float(lows.iloc[i])
                            risk = entry - stop
                            if risk > 0 and entry > stop:
                                # Target: max of EMA value zone, MIN_REWARD_RISK × risk.
                                target_value = float(ema.iloc[j])
                                target = max(
                                    target_value,
                                    entry + MIN_REWARD_RISK * risk,
                                )
                                if target > entry:
                                    try:
                                        sig = Signal(
                                            bar_index=j,
                                            direction=Direction.LONG,
                                            entry=entry, stop=stop, target=target,
                                        )
                                    except ValueError:
                                        break
                                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                                        signals.append(sig)
                            break
            last_low_idx = i

        if _local_max(highs, i):
            if last_high_idx is not None and (i - last_high_idx) >= min_sep \
                    and (i - last_high_idx) <= lookback:
                # Bearish divergence: higher high in price, lower high in oscillator
                if (highs.iloc[i] > highs.iloc[last_high_idx]
                        and osc.iloc[i] < osc.iloc[last_high_idx]):
                    for j in range(i + 1, min(i + 1 + confirm_window, len(df))):
                        if osc.iloc[j] < osc.iloc[i]:
                            entry = float(df["close"].iloc[j])
                            stop = float(highs.iloc[i])
                            risk = stop - entry
                            if risk > 0 and stop > entry:
                                target_value = float(ema.iloc[j])
                                target = min(
                                    target_value,
                                    entry - MIN_REWARD_RISK * risk,
                                )
                                if target < entry:
                                    try:
                                        sig = Signal(
                                            bar_index=j,
                                            direction=Direction.SHORT,
                                            entry=entry, stop=stop, target=target,
                                        )
                                    except ValueError:
                                        break
                                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                                        signals.append(sig)
                            break
            last_high_idx = i

    return signals
