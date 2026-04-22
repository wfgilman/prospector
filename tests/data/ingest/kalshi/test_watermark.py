"""Unit tests for the ingest watermark state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from prospector.data.ingest.kalshi import watermark


def test_load_missing_state_returns_empty_schema(tmp_path: Path) -> None:
    s = watermark.load(tmp_path)
    assert s == {"trades_by_ticker": {}, "events_last_pulled_at": {}}


def test_update_and_reload_roundtrip(tmp_path: Path) -> None:
    s = watermark.load(tmp_path)
    ts = datetime(2025, 10, 1, 12, 30, 45, tzinfo=timezone.utc)
    pulled = datetime(2026, 4, 22, 12, tzinfo=timezone.utc)
    watermark.update_trades(
        s, "KXBTC-X-B500",
        last_trade_id="t123",
        last_trade_time=ts,
        pulled_at=pulled,
    )
    watermark.update_events_pulled(s, "KXBTC", pulled)
    watermark.save(tmp_path, s)

    s2 = watermark.load(tmp_path)
    assert s2["trades_by_ticker"]["KXBTC-X-B500"]["last_trade_id"] == "t123"
    assert s2["events_last_pulled_at"]["KXBTC"] == pulled.isoformat()


def test_last_trade_time_parses_back_to_datetime(tmp_path: Path) -> None:
    s = {"trades_by_ticker": {}}
    ts = datetime(2025, 10, 1, 12, 30, 45, tzinfo=timezone.utc)
    pulled = datetime(2026, 4, 22, 12, tzinfo=timezone.utc)
    watermark.update_trades(
        s, "T", last_trade_id="id", last_trade_time=ts, pulled_at=pulled
    )
    got = watermark.last_trade_time(s, "T")
    assert got == ts


def test_missing_ticker_returns_none() -> None:
    s = {"trades_by_ticker": {}}
    assert watermark.last_trade_time(s, "NOTHING") is None
