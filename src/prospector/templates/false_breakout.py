"""
Template: false_breakout — Reversal on Failed Range Break

Most breakouts from trading ranges fail. Fade the breakout when price
breaks out of a range and then closes back inside.

Rules:
  1. Identify a trading range: price contained in a horizontal band for
     `range_lookback` bars, with width >= `range_threshold` × mid price.
  2. Downside false breakout → Long:
       Price closes below support, then closes back above support within
       `confirmation_bars`. Enter on the confirming close. Stop at the
       false-breakout low. Target = upper bound of the range.
  3. Upside false breakout → Short:
       Price closes above resistance, then closes back below within
       `confirmation_bars`. Enter on the confirming close. Stop at the
       false-breakout high. Target = lower bound of the range.
  4. Optional: volume_filter — require the breakout bar to have
     below-average volume (weak conviction on the breakout).

Config keys:
    timeframe           str — informational only; data must match
    range_lookback      int 15–60
    range_threshold     float 0.01–0.10  (min range width as fraction of price)
    confirmation_bars   int 1–3
    volume_filter       bool (optional, default False)

Data contract:
    Single DataFrame: timestamp, open, high, low, close, volume.
    Sorted ascending by timestamp.
"""

from __future__ import annotations

import pandas as pd

from prospector.templates.base import Direction, MIN_REWARD_RISK, Signal, validate_ohlcv


def _range_bounds(df: pd.DataFrame, lookback: int, end_i: int) -> tuple[float, float] | None:
    """
    Return (support, resistance) for the `lookback` bars ending at end_i (exclusive),
    or None if the window is too short.
    """
    start = end_i - lookback
    if start < 0:
        return None
    window = df.iloc[start:end_i]
    support = window["low"].min()
    resistance = window["high"].max()
    return support, resistance


def run(
    df: pd.DataFrame,
    config: dict,
) -> list[Signal]:
    """
    Generate false-breakout signals.

    Args:
        df:     Single-timeframe OHLCV DataFrame, sorted ascending.
        config: Dict matching the false_breakout parameter schema.

    Returns:
        List of Signal objects.
    """
    validate_ohlcv(df)

    lookback = int(config["range_lookback"])
    threshold = float(config["range_threshold"])
    confirm_bars = int(config["confirmation_bars"])
    volume_filter = bool(config.get("volume_filter", False))

    avg_volume = df["volume"].rolling(lookback).mean()
    signals: list[Signal] = []

    # We need lookback bars to define the range, plus up to confirm_bars for
    # the confirmation. Start scanning once we have enough history.
    for i in range(lookback, len(df) - confirm_bars):
        bounds = _range_bounds(df, lookback, i)
        if bounds is None:
            continue
        support, resistance = bounds

        mid = (support + resistance) / 2
        if mid <= 0:
            continue

        range_width = (resistance - support) / mid
        if range_width < threshold:
            continue  # Range too tight — not a meaningful range.

        bar = df.iloc[i]

        # Volume filter: breakout bar must have below-average volume.
        if volume_filter and not pd.isna(avg_volume.iloc[i]):
            if bar["volume"] >= avg_volume.iloc[i]:
                continue

        # --- Downside false breakout → Long ---
        if bar["close"] < support:
            # Look for a close back above support within confirmation_bars.
            for j in range(i + 1, min(i + 1 + confirm_bars, len(df))):
                confirm_bar = df.iloc[j]
                if confirm_bar["close"] > support:
                    entry = confirm_bar["close"]
                    stop = df["low"].iloc[i:j + 1].min()  # Low of false-breakout sequence
                    target = resistance  # Opposite side of the range

                    if stop >= entry or (entry - stop) < 1e-8:
                        break

                    try:
                        sig = Signal(
                            bar_index=j,
                            direction=Direction.LONG,
                            entry=entry,
                            stop=stop,
                            target=target,
                        )
                    except ValueError:
                        break

                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                        signals.append(sig)
                    break

        # --- Upside false breakout → Short ---
        elif bar["close"] > resistance:
            for j in range(i + 1, min(i + 1 + confirm_bars, len(df))):
                confirm_bar = df.iloc[j]
                if confirm_bar["close"] < resistance:
                    entry = confirm_bar["close"]
                    stop = df["high"].iloc[i:j + 1].max()  # High of false-breakout sequence
                    target = support  # Opposite side of the range

                    if stop <= entry or (stop - entry) < 1e-8:
                        break

                    try:
                        sig = Signal(
                            bar_index=j,
                            direction=Direction.SHORT,
                            entry=entry,
                            stop=stop,
                            target=target,
                        )
                    except ValueError:
                        break

                    if sig.reward_risk_ratio >= MIN_REWARD_RISK:
                        signals.append(sig)
                    break

    return signals
