"""Tests for the Hyperliquid funding-history download pipeline.

No network calls — the client is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from prospector.data.download_funding import (
    _funding_to_df,
    _last_time_ms,
    _parquet_path,
    download_funding_pair,
)


def _make_row(ts_ms: int, rate: float = 0.0000125, premium: float = 0.0005) -> dict:
    return {
        "coin": "BTC",
        "fundingRate": str(rate),
        "premium": str(premium),
        "time": ts_ms,
    }


def test_funding_to_df_types_and_columns():
    rows = [
        _make_row(1_700_000_000_000),
        _make_row(1_700_003_600_000, rate=0.00001),
    ]
    df = _funding_to_df(rows)
    assert list(df.columns) == ["time", "coin", "funding_rate", "premium"]
    assert str(df["time"].dtype).startswith("datetime64")
    assert df["funding_rate"].dtype == "float64"
    assert df["funding_rate"].iloc[0] == 0.0000125


def test_funding_to_df_empty():
    df = _funding_to_df([])
    assert df.empty
    assert list(df.columns) == ["time", "coin", "funding_rate", "premium"]


def test_last_time_ms_returns_none_for_missing(tmp_path):
    path = tmp_path / "missing.parquet"
    assert _last_time_ms(path) is None


def test_last_time_ms_reads_latest(tmp_path):
    path = tmp_path / "BTC.parquet"
    df = _funding_to_df(
        [_make_row(1_700_000_000_000), _make_row(1_700_003_600_000)]
    )
    df.to_parquet(path, index=False)
    ts = _last_time_ms(path)
    assert ts == 1_700_003_600_000


def test_parquet_path_normalizes_coin(tmp_path):
    p = _parquet_path("btc-perp", base=tmp_path)
    assert p.name == "BTC_PERP.parquet"


def test_download_funding_pair_incremental(tmp_path):
    """Simulate: existing data ends at T1, mock returns new rows from T2 onward,
    assert the file has both eras and is deduped."""
    path = tmp_path / "BTC.parquet"
    first_rows = [
        _make_row(1_700_000_000_000),
        _make_row(1_700_003_600_000),
    ]
    _funding_to_df(first_rows).to_parquet(path, index=False)

    # Mock client returns 2 new rows in first batch, empty in second.
    new_rows = [
        _make_row(1_700_007_200_000, rate=0.00002),
        _make_row(1_700_010_800_000, rate=0.00003),
    ]
    client = MagicMock()
    client.funding_history.side_effect = [new_rows, []]

    df = download_funding_pair("BTC", lookback_days=30, base=tmp_path, client=client)
    assert len(df) == 4
    assert df["time"].is_monotonic_increasing

    # Re-running with empty mock should be a no-op (already up to date).
    client.funding_history.side_effect = [[]]
    df2 = download_funding_pair("BTC", lookback_days=30, base=tmp_path, client=client)
    assert len(df2) == 4


def test_download_funding_pair_fresh(tmp_path):
    """Simulate: no existing data, mock returns a full window, writes fresh."""
    client = MagicMock()
    rows = [_make_row(1_700_000_000_000 + i * 3_600_000) for i in range(10)]
    client.funding_history.side_effect = [rows, []]
    df = download_funding_pair("ETH", lookback_days=1, base=tmp_path, client=client)
    assert len(df) == 10
    assert df["coin"].unique().tolist() == ["BTC"]  # mock data reused BTC coin field
    assert _parquet_path("ETH", base=tmp_path).exists()


def test_download_funding_pair_dedupe_on_overlap(tmp_path):
    """If mock returns rows overlapping existing data, dedupe keeps one row
    per (time, coin)."""
    path = tmp_path / "BTC.parquet"
    _funding_to_df([
        _make_row(1_700_000_000_000, rate=0.00001),
    ]).to_parquet(path, index=False)
    # Batch re-delivers the same tick plus two new ones
    client = MagicMock()
    client.funding_history.side_effect = [
        [
            _make_row(1_700_000_000_000, rate=0.99999),  # duplicate time
            _make_row(1_700_003_600_000, rate=0.00002),
            _make_row(1_700_007_200_000, rate=0.00003),
        ],
        [],
    ]
    df = download_funding_pair("BTC", lookback_days=30, base=tmp_path, client=client)
    assert len(df) == 3
