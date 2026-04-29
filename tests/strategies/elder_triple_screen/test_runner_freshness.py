"""Tests for the elder runner's OHLCV-staleness audit.

The runner refreshes OHLCV at every tick but the refresh can fail
silently (HTTP 200 with no new bars, or HTTP 5xx that the tick swallows
as a WARNING). The freshness audit is the second line of defence: walk
the cohort's short-TF parquets and surface anything that hasn't been
updated when it should have been.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from prospector.strategies.elder_triple_screen.runner import _check_freshness


def _write_short_parquet(
    base: Path, coin_safe: str, short_tf: str, last_bar: datetime
) -> None:
    """Drop a one-row parquet at <base>/<coin_safe>/<short_tf>.parquet."""
    coin_dir = base / coin_safe
    coin_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        [
            {
                "timestamp": last_bar,
                "open": 1.0, "high": 1.0, "low": 1.0,
                "close": 1.0, "volume": 1.0, "n_trades": 1,
            }
        ]
    )
    df.to_parquet(coin_dir / f"{short_tf}.parquet", index=False)


def test_check_freshness_classifies_three_cohorts(tmp_path: Path) -> None:
    """Fresh, stale, and very-stale parquets land in the right buckets."""
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    _write_short_parquet(tmp_path, "FRESH_PERP", "4h", now - timedelta(hours=2))
    _write_short_parquet(tmp_path, "STALE_PERP", "4h", now - timedelta(hours=12))
    _write_short_parquet(tmp_path, "DEAD_PERP", "4h", now - timedelta(days=30))

    universe = ["FRESH-PERP", "STALE-PERP", "DEAD-PERP"]

    with patch(
        "prospector.strategies.elder_triple_screen.runner.OHLCV_DIR", tmp_path
    ):
        stale, very_stale = _check_freshness(universe, "4h", now)
    assert stale == ["STALE-PERP"]
    assert very_stale == ["DEAD-PERP"]


def test_check_freshness_missing_parquet_marked_stale(tmp_path: Path) -> None:
    """A coin in the cohort with no parquet file at all is stale."""
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    universe = ["NEVER-PERP"]
    with patch(
        "prospector.strategies.elder_triple_screen.runner.OHLCV_DIR", tmp_path
    ):
        stale, very_stale = _check_freshness(universe, "4h", now)
    assert stale == ["NEVER-PERP"]
    assert very_stale == []


def test_check_freshness_empty_parquet_marked_stale(tmp_path: Path) -> None:
    """An empty parquet (zero rows) is treated as stale."""
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    coin_dir = tmp_path / "EMPTY_PERP"
    coin_dir.mkdir()
    pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume", "n_trades"]
    ).to_parquet(coin_dir / "4h.parquet", index=False)

    with patch(
        "prospector.strategies.elder_triple_screen.runner.OHLCV_DIR", tmp_path
    ):
        stale, very_stale = _check_freshness(["EMPTY-PERP"], "4h", now)
    assert stale == ["EMPTY-PERP"]
    assert very_stale == []


def test_check_freshness_unknown_tf_returns_empty(tmp_path: Path) -> None:
    """An unsupported timeframe returns empty lists rather than crashing."""
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    with patch(
        "prospector.strategies.elder_triple_screen.runner.OHLCV_DIR", tmp_path
    ):
        stale, very_stale = _check_freshness(["X-PERP"], "5m", now)
    assert stale == []
    assert very_stale == []


def test_check_freshness_naive_timestamp_treated_as_utc(tmp_path: Path) -> None:
    """Parquets written without tz info should still get classified correctly
    — the runner localizes naive timestamps to UTC."""
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    naive_last = (now - timedelta(hours=2)).replace(tzinfo=None)
    _write_short_parquet(tmp_path, "NAIVE_PERP", "4h", naive_last)

    with patch(
        "prospector.strategies.elder_triple_screen.runner.OHLCV_DIR", tmp_path
    ):
        stale, very_stale = _check_freshness(["NAIVE-PERP"], "4h", now)
    assert stale == []
    assert very_stale == []
