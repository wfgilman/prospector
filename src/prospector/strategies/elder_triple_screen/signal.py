"""Signal extractor for the locked elder triple-screen config.

Each tick we regenerate signals on the full OHLCV history and pick the
ones whose `bar_index` lies on the most recently printed bar. The
template is stateless, so this is the simplest correct extraction.

The locked config (#3895 from candidate 16's vol_q4 search) is
captured here as a module-level constant so live execution can't
silently drift from the validated parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from prospector.templates import triple_screen
from prospector.templates.base import Signal

REPO_ROOT = Path(__file__).resolve().parents[4]
OHLCV_DIR = REPO_ROOT / "data" / "ohlcv"


# Locked config — config #3895, see docs/rd/candidates/16-…
LOCKED_PARAMS = {
    "long_tf": "1d",
    "short_tf": "4h",
    "slow_ema": 15,
    "fast_ema": 5,
    "oscillator": "rsi",
    "osc_entry_threshold": 93.6812003903983,
}


@dataclass
class FreshSignal:
    coin: str
    signal: Signal
    bar_close_time: pd.Timestamp


def _coin_dir(coin: str) -> str:
    """Map any of {'BIGTIME', 'BIGTIME-PERP', 'BIGTIME_PERP'} → 'BIGTIME_PERP'."""
    safe = coin.replace("-", "_")
    return safe if safe.endswith("_PERP") else f"{safe}_PERP"


def load_ohlcv_pair(coin: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (df_long, df_short) for the locked TFs."""
    safe = _coin_dir(coin)
    df_long = pd.read_parquet(OHLCV_DIR / safe / f"{LOCKED_PARAMS['long_tf']}.parquet")
    df_short = pd.read_parquet(OHLCV_DIR / safe / f"{LOCKED_PARAMS['short_tf']}.parquet")
    return df_long.sort_values("timestamp").reset_index(drop=True), \
           df_short.sort_values("timestamp").reset_index(drop=True)


def extract_signals(coin: str) -> tuple[list[Signal], pd.DataFrame]:
    """Run the locked template on the coin's full history."""
    df_long, df_short = load_ohlcv_pair(coin)
    sigs = triple_screen.run(df_long, df_short, LOCKED_PARAMS)
    return sigs, df_short


def fresh_signals_for(coin: str, latest_bar_index: int) -> list[FreshSignal]:
    """Return signals at the most recently printed short-TF bar (and only that)."""
    sigs, df_short = extract_signals(coin)
    if not sigs:
        return []
    if latest_bar_index >= len(df_short):
        return []
    matched = [s for s in sigs if s.bar_index == latest_bar_index]
    if not matched:
        return []
    bar_time = df_short["timestamp"].iloc[latest_bar_index]
    return [FreshSignal(coin=coin, signal=s, bar_close_time=bar_time) for s in matched]
