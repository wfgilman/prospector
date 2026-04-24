"""Tests for the Coinbase candles download pipeline. No network calls."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import chain, repeat
from unittest.mock import MagicMock

from prospector.data.download_coinbase import (
    _candles_to_df,
    _last_timestamp,
    _parquet_path,
    download_candles,
)


def _make_candle(ts_s: int, price: float = 100.0) -> list:
    # Coinbase order: [time, low, high, open, close, volume]
    return [ts_s, price - 1, price + 1, price, price + 0.5, 2.5]


def test_candles_to_df_column_order():
    raw = [_make_candle(1_700_000_000), _make_candle(1_700_000_060, 101.0)]
    df = _candles_to_df(raw)
    assert list(df.columns) == [
        "timestamp", "open", "high", "low", "close", "volume"
    ]
    assert df["open"].iloc[0] == 100.0
    assert df["open"].iloc[1] == 101.0
    assert str(df["timestamp"].dtype).startswith("datetime64")


def test_candles_to_df_empty():
    df = _candles_to_df([])
    assert df.empty
    assert list(df.columns) == [
        "timestamp", "open", "high", "low", "close", "volume"
    ]


def test_parquet_path_labels(tmp_path):
    assert _parquet_path("BTC-USD", 60, base=tmp_path).name == "1m.parquet"
    assert _parquet_path("ETH-USD", 300, base=tmp_path).name == "5m.parquet"
    # Unknown granularity falls back to "<N>s"
    assert _parquet_path("BTC-USD", 120, base=tmp_path).name == "120s.parquet"


def test_last_timestamp_missing(tmp_path):
    assert _last_timestamp(tmp_path / "missing.parquet") is None


def test_last_timestamp_reads_max(tmp_path):
    path = tmp_path / "BTC-USD" / "1m.parquet"
    path.parent.mkdir(parents=True)
    df = _candles_to_df([_make_candle(1_700_000_000), _make_candle(1_700_000_060)])
    df.to_parquet(path, index=False)
    ts = _last_timestamp(path)
    assert ts == datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)


def test_download_candles_fresh(tmp_path):
    client = MagicMock()
    # First two windows return data; remaining windows empty. The downloader
    # paginates through 'now', so we pad empties indefinitely.
    client.candles.side_effect = chain(
        [
            [_make_candle(1_700_000_000 + 60 * i) for i in range(5)],
            [_make_candle(1_700_000_000 + 60 * (i + 5)) for i in range(5)],
        ],
        repeat([]),
    )
    df = download_candles(
        "BTC-USD", granularity_s=60, lookback_days=1,
        base=tmp_path, client=client,
    )
    assert len(df) == 10
    assert df["timestamp"].is_monotonic_increasing


def test_download_candles_incremental_dedupes(tmp_path):
    path = tmp_path / "BTC-USD" / "1m.parquet"
    path.parent.mkdir(parents=True)
    _candles_to_df(
        [_make_candle(1_700_000_000 + 60 * i) for i in range(3)]
    ).to_parquet(path, index=False)

    client = MagicMock()
    client.candles.side_effect = chain(
        [[_make_candle(1_700_000_000 + 60 * i, price=999) for i in (1, 2, 3, 4, 5)]],
        repeat([]),
    )
    df = download_candles(
        "BTC-USD", granularity_s=60, lookback_days=1,
        base=tmp_path, client=client,
    )
    # 3 existing + 2 genuinely new (indexes 3, 4). Overlapping (1, 2) are
    # deduped — drop_duplicates keeps first (= existing) rows.
    assert len(df) == 6
    first_row = df.iloc[1]
    assert first_row["open"] == 100.0  # not 999
