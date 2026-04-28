"""Portfolio lifecycle + sizing tests for the elder triple-screen book."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from prospector.strategies.elder_triple_screen.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
)
from prospector.templates.base import Direction


@pytest.fixture
def portfolio(tmp_path: Path) -> PaperPortfolio:
    return PaperPortfolio(
        db_path=tmp_path / "p.db",
        config=PortfolioConfig(
            initial_nav=10_000.0,
            risk_per_trade=0.02,
            max_position_frac=0.05,
        ),
    )


def _now() -> datetime:
    return datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_initial_state(portfolio: PaperPortfolio) -> None:
    assert portfolio.nav() == 10_000.0
    assert portfolio.cash() == 10_000.0
    assert portfolio.locked_risk() == 0.0
    assert portfolio.open_positions() == []


def test_size_position_iron_triangle(portfolio: PaperPortfolio) -> None:
    # Risk per trade = 2% × 10000 = $200.
    # entry=100, stop=98 → per_unit_risk=2 → units=100, risk=$200.
    units, risk = portfolio.size_position(entry=100.0, stop=98.0)
    assert units == 100.0
    assert risk == 200.0


def test_size_position_clipped_by_max_frac(portfolio: PaperPortfolio) -> None:
    # entry=100, stop=99.99 → per_unit_risk=0.01 → units would be huge
    # but risk dollars are clipped to max(2%, 5%)×NAV = $200 (smaller wins).
    units, risk = portfolio.size_position(entry=100.0, stop=99.99)
    assert risk == 200.0
    assert pytest.approx(units * 0.01, abs=0.01) == 200.0


def test_open_and_close_long_at_target(portfolio: PaperPortfolio) -> None:
    units, risk = portfolio.size_position(entry=100.0, stop=98.0)
    pid = portfolio.open_position(
        coin="ZK-PERP", direction=Direction.LONG,
        units=units, entry_price=100.0,
        stop_price=98.0, target_price=104.0,
        risk_budget=risk, entry_bar_index=10,
        entry_time=_now(),
    )
    assert portfolio.has_open_position("ZK-PERP")
    assert portfolio.locked_risk() == 200.0
    assert portfolio.cash() == 9_800.0
    assert portfolio.nav() == 10_000.0   # unrealized doesn't count

    cp = portfolio.close_position(
        position_id=pid, exit_price=104.0, exit_bar_index=15,
        exit_time=_now(), exit_reason="target", funding_cost=2.0,
    )
    # gross = 100 units × (104 - 100) = $400
    assert cp.gross_pnl == 400.0
    # fees = round-trip notional × (taker + slippage) per side
    # = 100 × (100 + 104) × (0.00035 + 0.0005) = 100 × 204 × 0.00085 = 17.34
    assert pytest.approx(cp.fees_paid, rel=1e-6) == 17.34
    assert cp.funding_cost == 2.0
    assert pytest.approx(cp.net_pnl, rel=1e-6) == 400.0 - 17.34 - 2.0
    assert not portfolio.has_open_position("ZK-PERP")
    assert pytest.approx(portfolio.nav(), rel=1e-6) == 10_000.0 + cp.net_pnl


def test_open_short_and_close_at_stop(portfolio: PaperPortfolio) -> None:
    units, risk = portfolio.size_position(entry=100.0, stop=102.0)
    pid = portfolio.open_position(
        coin="HMSTR-PERP", direction=Direction.SHORT,
        units=units, entry_price=100.0,
        stop_price=102.0, target_price=96.0,
        risk_budget=risk, entry_bar_index=5,
        entry_time=_now(),
    )
    cp = portfolio.close_position(
        position_id=pid, exit_price=102.0, exit_bar_index=8,
        exit_time=_now(), exit_reason="stop", funding_cost=-1.0,
    )
    # Short losing 2 points × 100 units = -$200
    assert cp.gross_pnl == -200.0
    # SHORT receives funding when rate>0 → cost negative → net adds back
    assert pytest.approx(cp.net_pnl, abs=0.01) == -200.0 - cp.fees_paid - (-1.0)


def test_no_double_open_for_same_coin(portfolio: PaperPortfolio) -> None:
    portfolio.open_position(
        coin="XAI-PERP", direction=Direction.LONG, units=10,
        entry_price=10.0, stop_price=9.5, target_price=11.0,
        risk_budget=5.0, entry_bar_index=1, entry_time=_now(),
    )
    with pytest.raises(ValueError):
        portfolio.open_position(
            coin="XAI-PERP", direction=Direction.LONG, units=10,
            entry_price=10.0, stop_price=9.5, target_price=11.0,
            risk_budget=5.0, entry_bar_index=2, entry_time=_now(),
        )


def test_close_unknown_position_raises(portfolio: PaperPortfolio) -> None:
    with pytest.raises(ValueError):
        portfolio.close_position(
            position_id=999, exit_price=100, exit_bar_index=0,
            exit_time=_now(), exit_reason="forced", funding_cost=0.0,
        )


def test_daily_snapshot(portfolio: PaperPortfolio) -> None:
    pid = portfolio.open_position(
        coin="ENA-PERP", direction=Direction.LONG, units=10,
        entry_price=10.0, stop_price=9.5, target_price=11.0,
        risk_budget=5.0, entry_bar_index=1, entry_time=_now(),
    )
    portfolio.close_position(
        position_id=pid, exit_price=11.0, exit_bar_index=3,
        exit_time=_now(), exit_reason="target", funding_cost=0.0,
    )
    portfolio.upsert_daily_snapshot(_now().date())
    # Sanity: a row exists.
    import sqlite3
    con = sqlite3.connect(portfolio.db_path)
    rows = con.execute("SELECT nav, open_positions FROM daily_snapshots").fetchall()
    con.close()
    assert len(rows) == 1
    nav, n_open = rows[0]
    assert n_open == 0
    assert nav > 10_000.0   # closed at target, profit
