"""End-to-end sweep test using a synthetic OHLCV that hits target on bar 5."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from prospector.strategies.elder_triple_screen import monitor as monitor_mod
from prospector.strategies.elder_triple_screen import signal as signal_mod
from prospector.strategies.elder_triple_screen.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
)
from prospector.templates.base import Direction


def _short_df_with_target_at(target_price: float, target_bar: int = 5) -> pd.DataFrame:
    """Flat OHLCV with a single bar that touches the target."""
    n = 20
    base = 100.0
    rows = []
    for i in range(n):
        if i == target_bar:
            rows.append({
                "timestamp": pd.Timestamp(2024, 1, 1, tz="UTC") + pd.Timedelta(hours=4 * i),
                "open": base, "high": target_price + 0.01,
                "low": base - 0.5, "close": base + 0.1, "volume": 1.0,
            })
        else:
            rows.append({
                "timestamp": pd.Timestamp(2024, 1, 1, tz="UTC") + pd.Timedelta(hours=4 * i),
                "open": base, "high": base + 0.5,
                "low": base - 0.5, "close": base + 0.1, "volume": 1.0,
            })
    return pd.DataFrame(rows)


def test_sweep_closes_at_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = PaperPortfolio(
        db_path=tmp_path / "p.db",
        config=PortfolioConfig(initial_nav=10_000.0),
    )
    portfolio.open_position(
        coin="TESTCOIN-PERP", direction=Direction.LONG,
        units=100.0, entry_price=100.0,
        stop_price=98.0, target_price=104.0,
        risk_budget=200.0, entry_bar_index=2,
        entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    df_short = _short_df_with_target_at(target_price=104.0, target_bar=5)

    def fake_pair(_: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame(), df_short

    monkeypatch.setattr(monitor_mod, "load_ohlcv_pair", fake_pair)
    monkeypatch.setattr(signal_mod, "load_ohlcv_pair", fake_pair)

    closed = monitor_mod.sweep(portfolio)
    assert len(closed) == 1
    cp = closed[0]
    assert cp.exit_reason == "target"
    assert cp.gross_pnl == 100.0 * (104.0 - 100.0)


def test_sweep_keeps_position_when_neither_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = PaperPortfolio(
        db_path=tmp_path / "p.db",
        config=PortfolioConfig(),
    )
    portfolio.open_position(
        coin="TESTCOIN-PERP", direction=Direction.LONG,
        units=100.0, entry_price=100.0,
        stop_price=80.0, target_price=200.0,
        risk_budget=200.0, entry_bar_index=2,
        entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    df_short = _short_df_with_target_at(target_price=300.0, target_bar=99)  # never hits

    def fake_pair(_: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame(), df_short

    monkeypatch.setattr(monitor_mod, "load_ohlcv_pair", fake_pair)
    monkeypatch.setattr(signal_mod, "load_ohlcv_pair", fake_pair)

    closed = monitor_mod.sweep(portfolio)
    assert closed == []
    assert portfolio.has_open_position("TESTCOIN-PERP")
