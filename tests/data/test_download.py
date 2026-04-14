"""
Tests for the OHLCV download pipeline.

These tests mock the Hyperliquid API client so no network calls are made.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from prospector.data.download import (
    _candles_to_df,
    _last_timestamp_ms,
    _parquet_path,
    download_pair,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_candle(ts_ms: int, price: float = 100.0, interval: str = "1h") -> dict:
    return {
        "t": ts_ms,
        "T": ts_ms + 3_600_000 - 1,
        "o": str(price),
        "h": str(price * 1.01),
        "l": str(price * 0.99),
        "c": str(price * 1.005),
        "v": "1000.0",
        "n": 500,
        "i": interval,
        "s": "BTC",
    }


def _mock_now(now_ms: int):
    """Patch datetime.now in the download module to return a fixed timestamp."""
    return patch(
        "prospector.data.download.datetime",
        **{"now.return_value": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)},
    )


# ---------------------------------------------------------------------------
# _candles_to_df
# ---------------------------------------------------------------------------

def test_candles_to_df_types():
    ts = 1_700_000_000_000
    df = _candles_to_df([_make_candle(ts)])
    assert df.shape == (1, 7)
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df["timestamp"].dt.tz is not None  # timezone-aware
    for col in ("open", "high", "low", "close", "volume"):
        assert pd.api.types.is_float_dtype(df[col]), f"{col} should be float"
    assert pd.api.types.is_integer_dtype(df["trades"])


def test_candles_to_df_values():
    ts = 1_700_000_000_000
    df = _candles_to_df([_make_candle(ts, price=50_000.0)])
    assert df["close"].iloc[0] == pytest.approx(50_250.0)
    assert df["volume"].iloc[0] == pytest.approx(1000.0)
    assert df["trades"].iloc[0] == 500


def test_candles_to_df_empty():
    df = _candles_to_df([])
    assert df.empty


# ---------------------------------------------------------------------------
# _last_timestamp_ms
# ---------------------------------------------------------------------------

def test_last_timestamp_ms_missing_file(tmp_path):
    assert _last_timestamp_ms(tmp_path / "nonexistent.parquet") is None


def test_last_timestamp_ms_reads_max(tmp_path):
    t1 = pd.Timestamp("2024-01-01", tz="UTC")
    t2 = pd.Timestamp("2024-06-01", tz="UTC")
    df = pd.DataFrame({"timestamp": [t1, t2]})
    path = tmp_path / "test.parquet"
    df.to_parquet(path, index=False)

    result = _last_timestamp_ms(path)
    expected = int(t2.timestamp() * 1000)
    assert result == expected


# ---------------------------------------------------------------------------
# _parquet_path
# ---------------------------------------------------------------------------

def test_parquet_path_strips_perp(tmp_path):
    path = _parquet_path("BTC-PERP", "1h", tmp_path)
    assert "BTC_PERP" in str(path)
    assert path.suffix == ".parquet"
    assert path.name == "1h.parquet"


# ---------------------------------------------------------------------------
# download_pair (mocked client)
# ---------------------------------------------------------------------------

def test_download_pair_fresh(tmp_path):
    """A fresh download fetches two pages of candles and stores them correctly."""
    bar_ms = 3_600_000  # 1h

    page1_start = 1_700_000_000_000
    page2_start = page1_start + 3 * bar_ms

    page1 = [_make_candle(page1_start + i * bar_ms) for i in range(3)]
    page2 = [_make_candle(page2_start + i * bar_ms) for i in range(3)]

    # now_ms sits exactly one bar after page2 ends so the loop terminates cleanly.
    now_ms = page2_start + 3 * bar_ms

    def fake_candles(coin, interval, start_ms, end_ms):
        if start_ms <= page1_start:
            return page1
        if start_ms <= page2_start:
            return page2
        return []

    mock_client = MagicMock()
    mock_client.candles.side_effect = fake_candles

    with _mock_now(now_ms):
        df = download_pair(
            coin="BTC-PERP",
            interval="1h",
            lookback_days=1,
            base=tmp_path,
            client=mock_client,
        )

    assert len(df) == 6
    assert df["timestamp"].is_monotonic_increasing


def test_download_pair_incremental(tmp_path):
    """Incremental update only fetches candles newer than the last stored bar."""
    bar_ms = 3_600_000

    # Pre-populate parquet with 3 candles.
    existing_ts = [
        pd.Timestamp(1_700_000_000_000 + i * bar_ms, unit="ms", tz="UTC")
        for i in range(3)
    ]
    existing_df = pd.DataFrame({
        "timestamp": existing_ts,
        "open": [100.0] * 3, "high": [101.0] * 3, "low": [99.0] * 3,
        "close": [100.5] * 3, "volume": [1000.0] * 3, "trades": [500] * 3,
    })
    path = _parquet_path("BTC-PERP", "1h", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_df.to_parquet(path, index=False)

    # One new candle immediately after the last stored one.
    last_ts_ms = int(existing_ts[-1].timestamp() * 1000)
    new_ts_ms = last_ts_ms + bar_ms
    new_candle = _make_candle(new_ts_ms, price=200.0)

    # Return the new candle on the first API call; terminate on the second.
    mock_client = MagicMock()
    mock_client.candles.side_effect = [[new_candle], []]

    # now_ms is exactly one bar after the new candle so the loop exits cleanly.
    now_ms = new_ts_ms + bar_ms

    with _mock_now(now_ms):
        df = download_pair(
            coin="BTC-PERP",
            interval="1h",
            base=tmp_path,
            client=mock_client,
        )

    assert len(df) == 4
    assert df["close"].iloc[-1] == pytest.approx(200.0 * 1.005)

    # The client's first call should start from the bar after the last stored one.
    first_call_start = mock_client.candles.call_args_list[0][0][2]
    assert first_call_start == new_ts_ms


def test_download_pair_no_duplicates(tmp_path):
    """Writing the same candles twice does not create duplicate rows."""
    bar_ms = 3_600_000
    base_ts = 1_700_000_000_000
    candles = [_make_candle(base_ts + i * bar_ms) for i in range(5)]

    # now_ms is exactly 5 bars after base so the first download terminates after
    # fetching all 5 candles in one batch.
    now_ms = base_ts + 5 * bar_ms

    mock_client = MagicMock()
    mock_client.candles.side_effect = [candles, []]

    with _mock_now(now_ms):
        download_pair("BTC-PERP", "1h", base=tmp_path, client=mock_client)

    # Simulate a second download where the API returns the same 5 candles again.
    # The incremental path fetches from last_ts + bar_ms = now_ms, which is past
    # now_ms, so no new candles are fetched — but if they were, dedup should apply.
    path = _parquet_path("BTC-PERP", "1h", tmp_path)
    df_before = pd.read_parquet(path)

    # Directly append a duplicate and verify dedup on re-save.
    from prospector.data.download import _append_and_save, _candles_to_df
    dup_df = _candles_to_df(candles)
    _append_and_save(path, dup_df)

    df_after = pd.read_parquet(path)
    assert df_after["timestamp"].duplicated().sum() == 0
    assert len(df_after) == len(df_before)
