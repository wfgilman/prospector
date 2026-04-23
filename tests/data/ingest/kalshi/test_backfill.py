"""Unit tests for the backfill driver's endpoint-selection logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from prospector.data.ingest.kalshi.backfill import (
    _parse_cutoff,
    _parse_event_close_time,
    _pick_endpoint_mode,
)


class TestParseCutoff:
    def test_prefers_trades_created_ts(self):
        raw = {
            "market_settled_ts": "2026-02-21T00:00:00Z",
            "orders_updated_ts": "2026-02-21T00:00:00Z",
            "trades_created_ts": "2026-02-21T00:00:00Z",
        }
        got = _parse_cutoff(raw)
        assert got == datetime(2026, 2, 21, tzinfo=timezone.utc)

    def test_falls_back_to_market_settled_ts(self):
        raw = {"market_settled_ts": "2026-01-15T12:00:00Z"}
        got = _parse_cutoff(raw)
        assert got == datetime(2026, 1, 15, 12, tzinfo=timezone.utc)

    def test_missing_raises(self):
        with pytest.raises(KeyError, match="cutoff"):
            _parse_cutoff({})


class TestPickEndpointMode:
    def test_before_cutoff_uses_historical(self):
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        strike = datetime(2025, 10, 29, tzinfo=timezone.utc)
        assert _pick_endpoint_mode(strike, cutoff) is True

    def test_at_or_after_cutoff_uses_live(self):
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        strike = datetime(2026, 3, 15, tzinfo=timezone.utc)
        assert _pick_endpoint_mode(strike, cutoff) is False

    def test_exact_boundary_uses_live(self):
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        strike = datetime(2026, 2, 21, tzinfo=timezone.utc)
        # Kalshi's cutoff semantics: 'before' means strictly less than.
        assert _pick_endpoint_mode(strike, cutoff) is False

    def test_missing_strike_date_falls_back_to_historical(self):
        cutoff = datetime(2026, 2, 21, tzinfo=timezone.utc)
        # Conservative: unknown dates go historical so we don't silently miss
        # old events.
        assert _pick_endpoint_mode(None, cutoff) is True


class TestParseEventCloseTime:
    def test_uses_strike_date(self):
        ev = {"strike_date": "2026-03-18T18:00:00Z"}
        got = _parse_event_close_time(ev)
        assert got == datetime(2026, 3, 18, 18, tzinfo=timezone.utc)

    def test_falls_back_to_last_updated_ts(self):
        ev = {"last_updated_ts": "2025-10-01T00:00:00Z"}
        got = _parse_event_close_time(ev)
        assert got == datetime(2025, 10, 1, tzinfo=timezone.utc)

    def test_missing_returns_none(self):
        assert _parse_event_close_time({}) is None
