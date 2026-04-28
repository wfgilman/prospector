"""
Template: impulse_system — Elder Strategy 2

Color each bar by the joint slope of a fast EMA and the MACD-Histogram:
    GREEN  : EMA rising AND MACD-Hist rising         (bullish impulse)
    RED    : EMA falling AND MACD-Hist falling       (bearish impulse)
    BLUE   : mixed                                   (neutral)

Entry rule:
    LONG  : the bar where color flips from RED to non-RED after a red run
    SHORT : the bar where color flips from GREEN to non-GREEN after a green run

Stop:    LONG  → low of the preceding red sequence
         SHORT → high of the preceding green sequence
Target:  symmetric reward across entry by `MIN_REWARD_RISK` × risk distance.

Config keys:
    timeframe   "1h" | "4h" | "1d"   (informational only; data must match)
    ema_period  int  8–30
    macd_fast   int  6–18
    macd_slow   int  20–40           (must be > macd_fast)
    macd_signal int  5–15
    hold_bars   int  1–60            (timeout)
"""

from __future__ import annotations

import pandas as pd

from prospector.templates.base import MIN_REWARD_RISK, Direction, Signal, validate_ohlcv


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _macd_hist(close: pd.Series, fast: int, slow: int, signal: int) -> pd.Series:
    macd = _ema(close, fast) - _ema(close, slow)
    sig = _ema(macd, signal)
    return macd - sig


def _bar_colors(df: pd.DataFrame, ema_period: int, macd_fast: int,
                macd_slow: int, macd_signal: int) -> pd.Series:
    ema = _ema(df["close"], ema_period)
    ema_slope = ema.diff()
    hist = _macd_hist(df["close"], macd_fast, macd_slow, macd_signal)
    hist_slope = hist.diff()
    colors = pd.Series("blue", index=df.index, dtype=object)
    colors[(ema_slope > 0) & (hist_slope > 0)] = "green"
    colors[(ema_slope < 0) & (hist_slope < 0)] = "red"
    return colors


def run(df: pd.DataFrame, config: dict) -> list[Signal]:
    validate_ohlcv(df)

    ema_period = int(config["ema_period"])
    macd_fast = int(config["macd_fast"])
    macd_slow = int(config["macd_slow"])
    macd_signal = int(config["macd_signal"])
    hold_bars = int(config.get("hold_bars", 20))

    if macd_fast >= macd_slow:
        raise ValueError("macd_fast must be < macd_slow")

    colors = _bar_colors(df, ema_period, macd_fast, macd_slow, macd_signal)

    signals: list[Signal] = []
    # Need enough warm-up bars for slow EMA + MACD signal smoothing.
    warmup = macd_slow + macd_signal + ema_period
    run_color: str | None = None
    run_start: int = -1

    for i in range(warmup, len(df)):
        c = colors.iloc[i]

        if run_color is None:
            run_color = c
            run_start = i
            continue

        if c == run_color:
            continue

        # Color changed. Check whether the prior run yields a setup.
        if run_color == "red" and c != "red":
            # Long entry on bar i.
            entry = float(df["close"].iloc[i])
            stop = float(df["low"].iloc[run_start:i].min())
            risk = entry - stop
            if risk > 0 and entry > stop:
                target = entry + risk * MIN_REWARD_RISK
                try:
                    sig = Signal(
                        bar_index=i, direction=Direction.LONG,
                        entry=entry, stop=stop, target=target,
                    )
                except ValueError:
                    pass
                else:
                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                        signals.append(sig)
        elif run_color == "green" and c != "green":
            # Short entry on bar i.
            entry = float(df["close"].iloc[i])
            stop = float(df["high"].iloc[run_start:i].max())
            risk = stop - entry
            if risk > 0 and stop > entry:
                target = entry - risk * MIN_REWARD_RISK
                try:
                    sig = Signal(
                        bar_index=i, direction=Direction.SHORT,
                        entry=entry, stop=stop, target=target,
                    )
                except ValueError:
                    pass
                else:
                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                        signals.append(sig)
        # blue → green or green → blue or blue → red etc. start a new run.
        run_color = c
        run_start = i

    # Optional: hold_bars caps the search window per signal — applied by harness via
    # exit-on-target/stop logic, plus end_of_data; we don't cap here.
    _ = hold_bars
    return signals
