"""Dashboard loader tests for the crypto_perp (elder triple-screen) schema.

The kalshi book stores `realized_pnl` and `close_time`; the elder book
stores `net_pnl` and `exit_time`. The dashboard needs separate loaders
that translate these into the same `PortfolioSummary` shape so the
comparison view can render both books side-by-side.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from prospector.dashboard import (
    _load_positions_elder,
    _load_summary_elder,
    _pnl_series_elder,
    load_elder_tick_history,
    pnl_series_for,
    summary_for,
)
from prospector.manifest import StrategyEntry
from prospector.strategies.elder_triple_screen.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
)
from prospector.templates.base import Direction


@pytest.fixture
def elder_portfolio(tmp_path: Path) -> PaperPortfolio:
    return PaperPortfolio(
        db_path=tmp_path / "elder.db",
        config=PortfolioConfig(initial_nav=10_000.0),
    )


def _entry(db: Path, log_dir: Path) -> StrategyEntry:
    return StrategyEntry(
        name="elder_triple_screen",
        display_name="Elder Triple-Screen",
        schema="crypto_perp",
        portfolio_db=db,
        log_dir=log_dir,
        launchd_label="com.prospector.paper-trade-elder",
        enabled=True,
    )


def test_load_summary_elder_empty(elder_portfolio: PaperPortfolio) -> None:
    summary = _load_summary_elder(elder_portfolio.db_path)
    assert summary is not None
    assert summary.nav == 10_000.0
    assert summary.realized_pnl == 0.0
    assert summary.open_positions == 0
    assert summary.locked_risk == 0.0


def test_load_summary_elder_missing_db(tmp_path: Path) -> None:
    assert _load_summary_elder(tmp_path / "nope.db") is None


def test_load_summary_elder_after_open_position(
    elder_portfolio: PaperPortfolio,
) -> None:
    elder_portfolio.open_position(
        coin="kPEPE-PERP",
        direction=Direction.LONG,
        units=1000.0,
        entry_price=0.10,
        stop_price=0.095,
        target_price=0.115,
        risk_budget=5.0,
        entry_bar_index=42,
        entry_time=datetime(2026, 4, 28, 14, 0, tzinfo=timezone.utc),
    )

    summary = _load_summary_elder(elder_portfolio.db_path)
    assert summary.open_positions == 1
    assert summary.locked_risk == pytest.approx(5.0)
    assert summary.realized_pnl == 0.0


def test_pnl_series_elder_after_close(
    elder_portfolio: PaperPortfolio,
) -> None:
    pos_id = elder_portfolio.open_position(
        coin="WLD-PERP",
        direction=Direction.LONG,
        units=10.0,
        entry_price=2.0,
        stop_price=1.9,
        target_price=2.3,
        risk_budget=1.0,
        entry_bar_index=1,
        entry_time=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
    )
    elder_portfolio.close_position(
        position_id=pos_id,
        exit_price=2.3,
        exit_bar_index=10,
        exit_time=datetime(2026, 4, 28, 20, 0, tzinfo=timezone.utc),
        exit_reason="target",
        funding_cost=0.0,
    )

    pnl_df = _pnl_series_elder(elder_portfolio.db_path)
    assert len(pnl_df) == 1
    # Long 10 @ 2.0 → 2.3 grosses +3.0; fees + slippage trim it but stay positive.
    assert pnl_df.iloc[0]["pnl"] > 0


def test_load_positions_elder_filters_by_status(
    elder_portfolio: PaperPortfolio,
) -> None:
    elder_portfolio.open_position(
        coin="ZRO-PERP",
        direction=Direction.SHORT,
        units=20.0,
        entry_price=3.0,
        stop_price=3.15,
        target_price=2.55,
        risk_budget=3.0,
        entry_bar_index=1,
        entry_time=datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc),
    )
    open_df = _load_positions_elder(elder_portfolio.db_path, status="open")
    assert len(open_df) == 1
    assert open_df.iloc[0]["coin"] == "ZRO-PERP"
    closed_df = _load_positions_elder(
        elder_portfolio.db_path, status="closed"
    )
    assert closed_df.empty


def test_summary_for_dispatches_on_schema(
    elder_portfolio: PaperPortfolio, tmp_path: Path
) -> None:
    entry = _entry(elder_portfolio.db_path, tmp_path / "logs")
    summary = summary_for(entry)
    assert summary is not None
    assert summary.nav == 10_000.0


def test_pnl_series_for_dispatches_on_schema(
    elder_portfolio: PaperPortfolio, tmp_path: Path
) -> None:
    entry = _entry(elder_portfolio.db_path, tmp_path / "logs")
    df = pnl_series_for(entry)
    # No closed positions yet → placeholder anchored at zero.
    assert len(df) == 1
    assert df.iloc[0]["pnl"] == 0.0


def test_load_elder_tick_history_parses_dict_form(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "paper_trade-20260428.log").write_text(
        "2026-04-28 14:10:42,972 INFO prospector.runner refresh start\n"
        "2026-04-28 14:10:43,100 INFO prospector.runner tick: "
        "{'closed': 0, 'opened': 1, 'skipped_open': 2, 'open_after_tick': 3, 'nav': 10005.12}\n"
        "2026-04-28 18:10:42,500 INFO prospector.runner refresh start\n"
        "2026-04-28 18:10:43,000 INFO prospector.runner tick: "
        "{'closed': 1, 'opened': 0, 'skipped_open': 0, 'open_after_tick': 2, 'nav': 10010.00}\n"
    )
    ticks = load_elder_tick_history(log_dir)
    assert len(ticks) == 2
    # First tick: opened=1, skipped=2, open_after=3, closed=0
    # → mapped onto entered/rejected/candidates/resolved.
    assert ticks[0].entered == 1
    assert ticks[0].rejected == 2
    assert ticks[0].candidates == 3
    assert ticks[0].resolved == 0
    assert ticks[0].timestamp == datetime(
        2026, 4, 28, 14, 10, 43, tzinfo=timezone.utc
    )
    assert ticks[1].resolved == 1
    assert ticks[1].entered == 0


def test_load_elder_tick_history_empty_dir(tmp_path: Path) -> None:
    assert load_elder_tick_history(tmp_path / "nope") == []


def test_load_elder_tick_history_matches_launchd_once_form(
    tmp_path: Path,
) -> None:
    """The launchd path logs `once: {...}`; the foreground loop logs `tick: {...}`.
    Both must be parsed so the dashboard's "Last tick" stays accurate."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "paper_trade-20260428.log").write_text(
        "2026-04-28 06:52:23,895 paper_trade_elder INFO once: "
        "{'closed': 0, 'opened': 0, 'skipped_open': 0, "
        "'open_after_tick': 0, 'nav': 10000.0}\n"
    )
    ticks = load_elder_tick_history(log_dir)
    assert len(ticks) == 1
    assert ticks[0].entered == 0
    assert ticks[0].rejected == 0
    assert ticks[0].candidates == 0
    assert ticks[0].resolved == 0
    assert ticks[0].timestamp == datetime(
        2026, 4, 28, 6, 52, 23, tzinfo=timezone.utc
    )
