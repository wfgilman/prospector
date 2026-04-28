"""
Template: kangaroo_tail — Elder Strategy 5 (failed-raid reversal)

Detect a single very tall bar bracketed by normal-height bars, then fade it.

Geometry:
    avg_height = mean( high − low ) over `context_bars` immediately before bar i
    The bar at i is a tail if (high_i − low_i) >= tail_multiplier × avg_height
    AND the bracketing bars (i−1, i+1) each have height < tail_multiplier × avg_height.

Direction:
    "Upward tail"   : tail's body sits high in its range AND
                      the close-side is in the upper half of the bar
                      → SHORT entry on bar (i + entry_lag)
    "Downward tail" : symmetric → LONG entry

Stop:   halfway up/down the tail (not at the tip — too wide otherwise)
Target: target_multiplier × tail_height in the fade direction

Config keys:
    timeframe          "1h" | "4h" | "1d"
    tail_multiplier    real 1.5–4.0   (× context_bars avg height)
    context_bars       int  10–30
    entry_lag          int  1–3       (bars after the tail to enter)
    target_multiplier  real 0.3–1.0   (target distance / tail height in fade direction)
"""

from __future__ import annotations

import pandas as pd

from prospector.templates.base import MIN_REWARD_RISK, Direction, Signal, validate_ohlcv


def run(df: pd.DataFrame, config: dict) -> list[Signal]:
    validate_ohlcv(df)

    tail_mult = float(config["tail_multiplier"])
    context = int(config["context_bars"])
    entry_lag = int(config["entry_lag"])
    target_mult = float(config["target_multiplier"])

    heights = (df["high"] - df["low"]).astype(float)
    avg_h = heights.rolling(context).mean()

    signals: list[Signal] = []

    for i in range(context + 1, len(df) - entry_lag - 1):
        h_i = float(heights.iloc[i])
        avg = float(avg_h.iloc[i - 1])
        if avg <= 0 or pd.isna(avg):
            continue
        if h_i < tail_mult * avg:
            continue
        # Bracketing bars must be normal-height.
        h_prev = float(heights.iloc[i - 1])
        h_next = float(heights.iloc[i + 1]) if i + 1 < len(df) else float("nan")
        if pd.isna(h_next):
            continue
        if h_prev >= tail_mult * avg or h_next >= tail_mult * avg:
            continue

        bar_high = float(df["high"].iloc[i])
        bar_low = float(df["low"].iloc[i])
        bar_open = float(df["open"].iloc[i])
        bar_close = float(df["close"].iloc[i])
        body_top = max(bar_open, bar_close)
        body_bot = min(bar_open, bar_close)
        mid = (bar_high + bar_low) / 2.0

        tail_up = body_bot > mid     # body sits in upper half → upward tail
        tail_down = body_top < mid   # body sits in lower half → downward tail
        if not (tail_up or tail_down):
            continue

        entry_idx = i + entry_lag
        if entry_idx >= len(df):
            continue
        entry = float(df["close"].iloc[entry_idx])
        tail_height = bar_high - bar_low

        if tail_up:
            # Short the failure of the upward thrust.
            stop = bar_low + tail_height / 2.0
            target = entry - target_mult * tail_height
            if not (target < entry < stop):
                continue
        else:
            # Long the failure of the downward thrust.
            stop = bar_high - tail_height / 2.0
            target = entry + target_mult * tail_height
            if not (stop < entry < target):
                continue

        try:
            sig = Signal(
                bar_index=entry_idx,
                direction=Direction.SHORT if tail_up else Direction.LONG,
                entry=entry, stop=stop, target=target,
            )
        except ValueError:
            continue
        if sig.reward_risk_ratio >= MIN_REWARD_RISK:
            signals.append(sig)

    return signals
