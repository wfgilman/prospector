"""
Tests for the Ledger SQLite append-only log.

All tests use a temporary in-memory database (db_path=":memory:") so nothing
touches disk and tests remain isolated.
"""

from __future__ import annotations

import pytest

from prospector.ledger import Ledger, RunRecord


def _scored_record(**overrides) -> RunRecord:
    defaults = dict(
        timestamp="2024-01-01T00:00:00+00:00",
        validation_status="valid",
        template="false_breakout",
        config_json='{"template":"false_breakout","params":{},"securities":["BTC-PERP"]}',
        securities=["BTC-PERP"],
        rationale="Testing false breakout on BTC",
        thinking="This is my reasoning.",
        backtest_status="scored",
        score=42.5,
        n_trades=25,
        pct_return=0.12,
        max_drawdown=0.08,
        profit_factor=1.8,
        win_rate=0.56,
        sharpe_ratio=1.1,
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


@pytest.fixture
def ledger(tmp_path):
    ld = Ledger(tmp_path / "test.db")
    yield ld
    ld.close()


# ---------------------------------------------------------------------------
# log / count
# ---------------------------------------------------------------------------

def test_log_assigns_run_id(ledger):
    r = _scored_record()
    assert r.run_id is None
    run_id = ledger.log(r)
    assert run_id == 1
    assert r.run_id == 1


def test_count_increments(ledger):
    assert ledger.count() == 0
    ledger.log(_scored_record())
    assert ledger.count() == 1
    ledger.log(_scored_record(timestamp="2024-01-02T00:00:00+00:00"))
    assert ledger.count() == 2


def test_log_minimal_record(ledger):
    """Invalid-JSON records have mostly None fields — should still insert cleanly."""
    r = RunRecord(
        timestamp="2024-01-01T00:00:00+00:00",
        validation_status="invalid_json",
        error="No JSON object found",
    )
    run_id = ledger.log(r)
    assert run_id == 1
    assert ledger.count() == 1


# ---------------------------------------------------------------------------
# get_sliding_window
# ---------------------------------------------------------------------------

def test_get_sliding_window_empty(ledger):
    assert ledger.get_sliding_window() == []


def test_get_sliding_window_order_and_limit(ledger):
    ledger.log(_scored_record(timestamp="2024-01-01T00:00:00+00:00", score=10.0))
    ledger.log(_scored_record(timestamp="2024-01-02T00:00:00+00:00", score=20.0))
    ledger.log(_scored_record(timestamp="2024-01-03T00:00:00+00:00", score=30.0))

    window = ledger.get_sliding_window(2)
    assert len(window) == 2
    # Most recent first
    assert window[0].score == 30.0
    assert window[1].score == 20.0


def test_get_sliding_window_securities_round_trip(ledger):
    ledger.log(_scored_record(securities=["BTC-PERP", "ETH-PERP"]))
    window = ledger.get_sliding_window(1)
    assert window[0].securities == ["BTC-PERP", "ETH-PERP"]


def test_get_sliding_window_empty_securities(ledger):
    r = RunRecord(
        timestamp="2024-01-01T00:00:00+00:00",
        validation_status="invalid_json",
        securities=[],
    )
    ledger.log(r)
    window = ledger.get_sliding_window(1)
    assert window[0].securities == []


# ---------------------------------------------------------------------------
# last_n_templates
# ---------------------------------------------------------------------------

def test_last_n_templates_empty(ledger):
    assert ledger.last_n_templates() == []


def test_last_n_templates_only_valid(ledger):
    """Only validation_status='valid' rows contribute to stagnation detection."""
    ledger.log(_scored_record(template="false_breakout"))
    ledger.log(RunRecord(
        timestamp="2024-01-02T00:00:00+00:00",
        validation_status="invalid_json",
        template="triple_screen",
    ))
    ledger.log(_scored_record(
        timestamp="2024-01-03T00:00:00+00:00", template="false_breakout"
    ))

    templates = ledger.last_n_templates(5)
    assert templates == ["false_breakout", "false_breakout"]


def test_last_n_templates_limit(ledger):
    for i in range(6):
        ledger.log(_scored_record(
            timestamp=f"2024-01-0{i+1}T00:00:00+00:00", template="false_breakout"
        ))
    assert len(ledger.last_n_templates(3)) == 3


# ---------------------------------------------------------------------------
# format_sliding_window
# ---------------------------------------------------------------------------

def test_format_sliding_window_cold_start(ledger):
    text = ledger.format_sliding_window()
    assert "first run" in text.lower()
    assert "baseline" in text.lower()


def test_format_sliding_window_includes_run_id(ledger):
    ledger.log(_scored_record())
    text = ledger.format_sliding_window()
    assert "1" in text


def test_format_sliding_window_scored_row_has_metrics(ledger):
    ledger.log(_scored_record(score=84.3, n_trades=47, max_drawdown=0.12))
    text = ledger.format_sliding_window()
    assert "84.3" in text
    assert "47" in text
    assert "12%" in text


def test_format_sliding_window_rejected_row(ledger):
    ledger.log(_scored_record(
        backtest_status="rejected",
        rejection_reason="insufficient_trades: 7 < 20",
        score=None,
    ))
    text = ledger.format_sliding_window()
    assert "rejected" in text


def test_format_sliding_window_securities_stripped(ledger):
    """Securities in the table should show 'BTC,ETH' not 'BTC-PERP,ETH-PERP'."""
    ledger.log(_scored_record(securities=["BTC-PERP", "ETH-PERP"]))
    text = ledger.format_sliding_window()
    assert "BTC,ETH" in text
    assert "PERP" not in text
