from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from prospector.dashboard import (
    _hours_to_expiry,
    build_pnl_series,
    load_category_breakdown,
    load_portfolio_summary,
    load_positions,
    load_tick_history,
)
from prospector.strategies.pm_underwriting.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
)


@pytest.fixture
def portfolio(tmp_path: Path) -> PaperPortfolio:
    cfg = PortfolioConfig(
        initial_nav=10_000.0,
        max_position_frac=0.05,
        max_event_frac=0.5,
        max_bin_frac=0.5,
        max_trades_per_day=100,
        max_positions_per_event=5,
        max_positions_per_subseries=5,
        max_positions_per_series=50,
    )
    p = PaperPortfolio(tmp_path / "portfolio.db", cfg)
    yield p
    p.close()


def test_load_portfolio_summary_empty(tmp_path: Path, portfolio: PaperPortfolio) -> None:
    summary = load_portfolio_summary(portfolio.db_path)
    assert summary is not None
    assert summary.nav == 10_000.0
    assert summary.open_positions == 0
    assert summary.realized_pnl == 0.0


def test_load_portfolio_summary_missing_db(tmp_path: Path) -> None:
    assert load_portfolio_summary(tmp_path / "nope.db") is None


def test_load_positions_and_summary_after_entry(portfolio: PaperPortfolio) -> None:
    pos = portfolio.enter(
        ticker="KXNFL-T1",
        event_ticker="KXNFL-E1-A",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.9,
        edge_pp=2.0,
        risk_budget=50.0,
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
    )
    open_df = load_positions(portfolio.db_path, status="open")
    assert len(open_df) == 1
    assert open_df.iloc[0]["ticker"] == "KXNFL-T1"

    summary = load_portfolio_summary(portfolio.db_path)
    assert summary.open_positions == 1
    assert summary.locked_risk == pytest.approx(pos.risk_budget)
    assert summary.realized_pnl == 0.0


def test_build_pnl_series_tracks_realized_pnl(portfolio: PaperPortfolio) -> None:
    portfolio.enter(
        ticker="KXNFL-T1",
        event_ticker="KXNFL-E1-A",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.9,
        edge_pp=2.0,
        risk_budget=50.0,
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
    )
    portfolio.resolve(
        "KXNFL-T1",
        market_result="no",
        close_time=datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc),
    )

    pnl_df = build_pnl_series(portfolio.db_path)
    assert len(pnl_df) == 1
    # Won a sell_yes at 0.9 → positive realized P&L after fees.
    assert pnl_df.iloc[0]["pnl"] > 0


def test_build_pnl_series_empty_anchors_at_zero(portfolio: PaperPortfolio) -> None:
    pnl_df = build_pnl_series(portfolio.db_path)
    assert len(pnl_df) == 1
    assert pnl_df.iloc[0]["pnl"] == 0.0


def test_load_tick_history_parses_summary_and_timestamp(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "paper_trade-20260421.log").write_text(
        "2026-04-21 14:10:42,972 INFO prospector.runner monitor: resolved=0 voided=0\n"
        "2026-04-21 14:10:42,973 INFO prospector.runner daily cap reached\n"
        "entered=0 rejected=0 candidates=0 resolved=0 voided=0\n"
        "2026-04-21 14:25:45,356 INFO prospector.runner monitor: resolved=1 voided=0\n"
        "entered=2 rejected=3 candidates=7 resolved=1 voided=0\n"
    )
    ticks = load_tick_history(log_dir)
    assert len(ticks) == 2
    assert ticks[-1].entered == 2
    assert ticks[-1].rejected == 3
    assert ticks[-1].candidates == 7
    assert ticks[-1].resolved == 1
    assert ticks[-1].timestamp == datetime(2026, 4, 21, 14, 25, 45, tzinfo=timezone.utc)


def test_load_tick_history_empty_dir(tmp_path: Path) -> None:
    assert load_tick_history(tmp_path / "nope") == []
    (tmp_path / "empty").mkdir()
    assert load_tick_history(tmp_path / "empty") == []


def test_load_category_breakdown_missing_db(tmp_path: Path) -> None:
    assert load_category_breakdown(tmp_path / "nope.db").empty


def test_load_category_breakdown_empty(portfolio: PaperPortfolio) -> None:
    assert load_category_breakdown(portfolio.db_path).empty


def test_hours_to_expiry_is_numeric_and_sortable() -> None:
    now = datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc)
    expected = pd.Series(
        [
            pd.Timestamp(now) + pd.Timedelta(hours=5, minutes=12),
            pd.Timestamp(now) + pd.Timedelta(days=3, hours=4),
            pd.Timestamp(now) - pd.Timedelta(minutes=30),
            pd.NaT,
        ]
    )

    hours = _hours_to_expiry(expected, now)

    assert hours.iloc[0] == pytest.approx(5.2)
    assert hours.iloc[1] == pytest.approx(76.0)
    assert hours.iloc[2] == pytest.approx(-0.5)
    assert pd.isna(hours.iloc[3])
    # Crucially, sorting the numeric series orders by duration — not by
    # the lexicographic ordering a preformatted string ("3d 4h" vs "5h 12m")
    # would have produced.
    sorted_vals = hours.dropna().sort_values().tolist()
    assert sorted_vals == sorted(sorted_vals)
    assert sorted_vals[0] == pytest.approx(-0.5)
    assert sorted_vals[-1] == pytest.approx(76.0)


def test_load_category_breakdown_mixed_positions(portfolio: PaperPortfolio) -> None:
    # Two open sports positions, one resolved sports win, one resolved crypto loss.
    portfolio.enter(
        ticker="KXNFL-T1",
        event_ticker="KXNFL-E1-A",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.9,
        edge_pp=4.0,
        risk_budget=50.0,
        entry_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
    )
    portfolio.enter(
        ticker="KXNFL-T2",
        event_ticker="KXNFL-E2-A",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.85,
        edge_pp=6.0,
        risk_budget=40.0,
        entry_time=datetime(2026, 4, 21, 12, 5, tzinfo=timezone.utc),
    )
    portfolio.enter(
        ticker="KXNFL-T3",
        event_ticker="KXNFL-E3-A",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.9,
        edge_pp=3.0,
        risk_budget=25.0,
        entry_time=datetime(2026, 4, 21, 12, 10, tzinfo=timezone.utc),
    )
    portfolio.resolve(
        "KXNFL-T3",
        market_result="no",
        close_time=datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc),
    )
    portfolio.enter(
        ticker="KXBTC-T1",
        event_ticker="KXBTC-E1",
        series_ticker="KXBTC",
        category="crypto",
        side="sell_yes",
        entry_price=0.92,
        edge_pp=3.5,
        risk_budget=30.0,
        entry_time=datetime(2026, 4, 21, 13, 30, tzinfo=timezone.utc),
    )
    portfolio.resolve(
        "KXBTC-T1",
        market_result="yes",
        close_time=datetime(2026, 4, 21, 14, 0, tzinfo=timezone.utc),
    )

    df = load_category_breakdown(portfolio.db_path)
    assert set(df["category"]) == {"sports", "crypto"}
    df = df.set_index("category")

    # Contract counts are integer-quantized so risk/reward drift from the
    # notional ask by pennies; cross-check against the positions table
    # rather than hardcode the sized amounts.
    open_sports = load_positions(portfolio.db_path, status="open")
    open_sports = open_sports[open_sports["category"] == "sports"]
    expected_risk = open_sports["risk_budget"].sum()
    expected_upside = open_sports["reward_potential"].sum()

    sports = df.loc["sports"]
    assert int(sports["open_count"]) == 2
    assert sports["locked_risk"] == pytest.approx(expected_risk)
    assert int(sports["closed_count"]) == 1
    assert int(sports["wins"]) == 1
    assert int(sports["losses"]) == 0
    assert sports["realized_pnl"] > 0
    assert sports["upside"] == pytest.approx(expected_upside)
    assert sports["avg_edge_pp"] == pytest.approx(5.0)  # only counts open: (4 + 6) / 2

    crypto = df.loc["crypto"]
    assert int(crypto["open_count"]) == 0
    assert int(crypto["closed_count"]) == 1
    assert int(crypto["wins"]) == 0
    assert int(crypto["losses"]) == 1
    assert crypto["realized_pnl"] < 0
