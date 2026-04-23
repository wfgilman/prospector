"""Unit tests for Kalshi ingest writers. No API calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from prospector.data.ingest.kalshi import writer
from prospector.kalshi.models import Market, Trade


def _trade(
    trade_id: str, ticker: str, created: datetime, yes: float = 0.5
) -> Trade:
    return Trade(
        trade_id=trade_id,
        ticker=ticker,
        count=10,
        yes_price=yes,
        no_price=1.0 - yes,
        taker_side="yes",
        created_time=created,
    )


def test_trades_to_frame_populates_event_ticker() -> None:
    trades = [
        _trade("t1", "KXBTC-X-B500", datetime(2025, 10, 1, 12, tzinfo=timezone.utc)),
        _trade("t2", "KXBTC-X-B500", datetime(2025, 10, 1, 13, tzinfo=timezone.utc)),
        _trade("t3", "KXBTC-Y-B500", datetime(2025, 10, 2, 13, tzinfo=timezone.utc)),
    ]
    mapping = {"KXBTC-X-B500": "KXBTC-X", "KXBTC-Y-B500": "KXBTC-Y"}
    df = writer.trades_to_frame(trades, mapping)
    assert list(df.columns) == [
        "trade_id", "ticker", "event_ticker", "count",
        "yes_price", "no_price", "taker_side", "created_time",
    ]
    assert df.loc[df["ticker"] == "KXBTC-X-B500", "event_ticker"].tolist() == [
        "KXBTC-X", "KXBTC-X"
    ]
    assert str(df["created_time"].dtype).startswith("datetime64")


def test_write_trades_idempotent(tmp_path: Path) -> None:
    trades = [
        _trade("t1", "A", datetime(2025, 10, 1, 12, tzinfo=timezone.utc)),
        _trade("t2", "A", datetime(2025, 10, 1, 13, tzinfo=timezone.utc)),
    ]
    df = writer.trades_to_frame(trades, {"A": "EA"})
    counts1 = writer.write_trades(df, tmp_path)
    counts2 = writer.write_trades(df, tmp_path)  # re-write same data
    assert counts1 == {"2025-10-01": 2}
    assert counts2 == {"2025-10-01": 2}  # dedup via trade_id

    path = tmp_path / "trades" / "date=2025-10-01" / "part.parquet"
    disk = pd.read_parquet(path)
    assert len(disk) == 2
    assert set(disk["trade_id"]) == {"t1", "t2"}


def test_write_trades_merges_new_into_existing(tmp_path: Path) -> None:
    first = writer.trades_to_frame(
        [_trade("t1", "A", datetime(2025, 10, 1, 12, tzinfo=timezone.utc))],
        {"A": "EA"},
    )
    writer.write_trades(first, tmp_path)
    second = writer.trades_to_frame(
        [
            _trade("t1", "A", datetime(2025, 10, 1, 12, tzinfo=timezone.utc)),
            _trade("t2", "A", datetime(2025, 10, 1, 13, tzinfo=timezone.utc)),
        ],
        {"A": "EA"},
    )
    counts = writer.write_trades(second, tmp_path)
    assert counts == {"2025-10-01": 2}
    disk = pd.read_parquet(
        tmp_path / "trades" / "date=2025-10-01" / "part.parquet"
    )
    assert set(disk["trade_id"]) == {"t1", "t2"}


def test_write_trades_partitions_by_utc_date(tmp_path: Path) -> None:
    trades = [
        _trade("t1", "A", datetime(2025, 10, 1, 12, tzinfo=timezone.utc)),
        _trade("t2", "A", datetime(2025, 10, 2,  1, tzinfo=timezone.utc)),
    ]
    df = writer.trades_to_frame(trades, {"A": "EA"})
    counts = writer.write_trades(df, tmp_path)
    assert set(counts) == {"2025-10-01", "2025-10-02"}


def _market(ticker: str, status: str = "finalized") -> Market:
    return Market(
        ticker=ticker, event_ticker="EVT", series_ticker="EVT",
        title="t", yes_sub_title="", no_sub_title="",
        status=status, result="yes",
        open_time=datetime(2025, 10, 1, tzinfo=timezone.utc),
        close_time=datetime(2025, 10, 2, tzinfo=timezone.utc),
        expiration_time=None,
        yes_bid=0.5, yes_ask=0.52, no_bid=0.48, no_ask=0.5,
        last_price=0.51, volume=100, volume_24h=0, open_interest=50,
        category="crypto", raw={},
    )


def test_write_markets_dedupes_within_day(tmp_path: Path) -> None:
    pulled = datetime(2026, 4, 22, 12, tzinfo=timezone.utc)
    first = writer.markets_to_frame([_market("A", "active")], pulled_at=pulled)
    second = writer.markets_to_frame(
        [_market("A", "finalized")],
        pulled_at=pulled + pd.Timedelta(minutes=5),
    )
    writer.write_markets(first, tmp_path)
    writer.write_markets(second, tmp_path)
    disk = pd.read_parquet(
        tmp_path / "markets" / "date=2026-04-22" / "part.parquet"
    )
    assert len(disk) == 1
    assert disk["status"].iloc[0] == "finalized"


def test_write_events_persists_raw_json(tmp_path: Path) -> None:
    ev = [{
        "event_ticker": "FED-25OCT",
        "series_ticker": "FED",
        "status": "settled",
        "title": "Fed Oct 2025",
        "category": "economics",
        "extra_field": {"nested": True},
    }]
    pulled = datetime(2026, 4, 22, 12, tzinfo=timezone.utc)
    counts = writer.write_events(ev, tmp_path, pulled)
    assert counts == {"2026-04-22": 1}
    disk = pd.read_parquet(
        tmp_path / "events" / "date=2026-04-22" / "part.parquet"
    )
    assert disk["event_ticker"].iloc[0] == "FED-25OCT"
    assert "extra_field" in disk["raw_json"].iloc[0]
