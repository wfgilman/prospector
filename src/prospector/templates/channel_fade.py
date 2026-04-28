"""
Template: channel_fade — Elder Strategy 3 (mean reversion from EMA channel)

Draw an EMA-centred channel:
    upper = ema × (1 + channel_coefficient)
    lower = ema × (1 − channel_coefficient)

LONG  : price's low touches/penetrates the lower channel AND a confirmation
        oscillator shows a higher low than its previous touch (bullish
        divergence proxy).
SHORT : symmetric on the upper channel.

Stop:   half the penetration distance beyond the channel.
Target: the EMA value zone (conservative) at the entry bar.

Config keys:
    timeframe              "1h" | "4h" | "1d"
    ema_period             int 15–60
    channel_coefficient    real 0.01–0.10
    confirmation           "rsi" | "macd_hist" | "force_index_2"
    divergence_lookback    int 5–30   (bars between the two touch lows)
    min_touches            int 1–3    (number of channel touches before
                                       a divergence-confirmed fade is taken)
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


def _confirmation(df: pd.DataFrame, name: str) -> pd.Series:
    if name == "rsi":
        return _rsi(df["close"])
    if name == "macd_hist":
        return _macd_hist(df["close"])
    if name == "force_index_2":
        return _force_index_2(df)
    raise ValueError(f"Unknown confirmation indicator: {name!r}")


def run(df: pd.DataFrame, config: dict) -> list[Signal]:
    validate_ohlcv(df)

    period = int(config["ema_period"])
    coef = float(config["channel_coefficient"])
    conf_name = config["confirmation"]
    lookback = int(config["divergence_lookback"])
    min_touches = int(config.get("min_touches", 1))

    ema = _ema(df["close"], period)
    upper = ema * (1.0 + coef)
    lower = ema * (1.0 - coef)
    conf = _confirmation(df, conf_name)

    signals: list[Signal] = []
    warmup = max(period, 26, 14) + lookback
    last_lower_touch_idx: int | None = None
    last_upper_touch_idx: int | None = None
    long_touches = 0
    short_touches = 0

    for i in range(warmup, len(df)):
        bar_low = float(df["low"].iloc[i])
        bar_high = float(df["high"].iloc[i])
        l_lower = float(lower.iloc[i])
        l_upper = float(upper.iloc[i])
        l_ema = float(ema.iloc[i])

        # ----- Lower channel touch → long candidate -----
        if bar_low <= l_lower:
            long_touches += 1
            if last_lower_touch_idx is not None and (
                i - last_lower_touch_idx >= lookback
                and long_touches >= min_touches
                and conf.iloc[i] > conf.iloc[last_lower_touch_idx]
                and bar_low > float(df["low"].iloc[last_lower_touch_idx])
                # bullish divergence proxy: price made shallower low,
                # confirmation indicator made higher low
            ):
                penetration = max(0.0, l_lower - bar_low)
                entry = float(df["close"].iloc[i])
                stop = bar_low - penetration / 2.0
                target = l_ema
                if stop < entry < target:
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
                            long_touches = 0
            last_lower_touch_idx = i

        # ----- Upper channel touch → short candidate -----
        if bar_high >= l_upper:
            short_touches += 1
            if last_upper_touch_idx is not None and (
                i - last_upper_touch_idx >= lookback
                and short_touches >= min_touches
                and conf.iloc[i] < conf.iloc[last_upper_touch_idx]
                and bar_high < float(df["high"].iloc[last_upper_touch_idx])
            ):
                penetration = max(0.0, bar_high - l_upper)
                entry = float(df["close"].iloc[i])
                stop = bar_high + penetration / 2.0
                target = l_ema
                if target < entry < stop:
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
                            short_touches = 0
            last_upper_touch_idx = i

    return signals
