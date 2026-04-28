"""Signal extraction tests — verifies the locked params + monkeypatched OHLCV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from prospector.strategies.elder_triple_screen import signal as signal_mod


@pytest.fixture
def fake_ohlcv_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a synthetic ohlcv tree at tmp_path/ohlcv with a clear up-trend."""
    base = tmp_path / "ohlcv" / "TESTCOIN_PERP"
    base.mkdir(parents=True)
    # 200 daily bars trending up — slow EMA will be rising → LONG bias.
    n_long = 200
    daily = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n_long, freq="1D", tz="UTC"),
        "open": [100 + 0.5 * i for i in range(n_long)],
        "high": [101 + 0.5 * i for i in range(n_long)],
        "low": [99 + 0.5 * i for i in range(n_long)],
        "close": [100 + 0.5 * i for i in range(n_long)],
        "volume": [1.0] * n_long,
    })
    daily.to_parquet(base / "1d.parquet")
    # 4h bars covering the same window (6 per day).
    n_short = n_long * 6
    short = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n_short, freq="4h", tz="UTC"),
        "open": [100 + 0.08 * i for i in range(n_short)],
        "high": [101 + 0.08 * i for i in range(n_short)],
        "low": [99 + 0.08 * i for i in range(n_short)],
        "close": [100 + 0.08 * i for i in range(n_short)],
        "volume": [1.0] * n_short,
    })
    short.to_parquet(base / "4h.parquet")
    monkeypatch.setattr(signal_mod, "OHLCV_DIR", tmp_path / "ohlcv")
    return tmp_path / "ohlcv"


def test_locked_params_match_candidate_16() -> None:
    """Drift-protection: locked params must match #3895 verbatim."""
    assert signal_mod.LOCKED_PARAMS == {
        "long_tf": "1d",
        "short_tf": "4h",
        "slow_ema": 15,
        "fast_ema": 5,
        "oscillator": "rsi",
        "osc_entry_threshold": 93.6812003903983,
    }


def test_extract_signals_runs(fake_ohlcv_dir: Path) -> None:
    sigs, df_short = signal_mod.extract_signals("TESTCOIN-PERP")
    # On the synthetic monotone-up data, RSI≥93 won't fire many shorts; it's
    # OK if signals are zero. The contract is "doesn't crash and returns a
    # list + DataFrame".
    assert isinstance(sigs, list)
    assert "timestamp" in df_short.columns
    assert len(df_short) > 0


def test_fresh_signals_filters_to_latest_bar(fake_ohlcv_dir: Path) -> None:
    sigs, df_short = signal_mod.extract_signals("TESTCOIN-PERP")
    latest = len(df_short) - 1
    fresh = signal_mod.fresh_signals_for("TESTCOIN-PERP", latest)
    # Either zero (no signal at latest) or all match latest_bar_index.
    assert all(f.signal.bar_index == latest for f in fresh)
