from datetime import datetime, timezone

import pytest

from prospector.kalshi import KalshiError
from prospector.kalshi.models import Market
from prospector.strategies.pm_underwriting.monitor import sweep
from prospector.strategies.pm_underwriting.portfolio import PaperPortfolio, PortfolioConfig


class FakeClient:
    """Minimal stub matching the Kalshi client surface used by `sweep`."""

    def __init__(self, markets: dict[str, Market | Exception]):
        self.markets = markets
        self.calls: list[str] = []

    def fetch_market(self, ticker: str) -> Market:
        self.calls.append(ticker)
        value = self.markets[ticker]
        if isinstance(value, Exception):
            raise value
        return value


def _mkt(ticker: str, status: str, result: str = "") -> Market:
    return Market(
        ticker=ticker,
        event_ticker="KXNFL-2026",
        series_ticker="KXNFL",
        title="t",
        status=status,
        result=result,
        open_time=None,
        close_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        expiration_time=None,
        yes_bid=None,
        yes_ask=None,
        no_bid=None,
        no_ask=None,
        last_price=None,
        volume=0,
        open_interest=0,
        category="",
        raw={},
    )


@pytest.fixture
def portfolio(tmp_path):
    # Monitor tests stage three positions on the same series/subseries; they
    # aren't testing diversity, so the caps are loosened here.
    cfg = PortfolioConfig(
        initial_nav=10_000.0,
        max_trades_per_day=100,
        max_positions_per_event=10,
        max_positions_per_subseries=10,
        max_positions_per_series=99,
    )
    with PaperPortfolio(tmp_path / "p.db", cfg) as p:
        p.enter(
            ticker="T1",
            event_ticker="KXNFL-2026",
            series_ticker="KXNFL",
            category="sports",
            side="sell_yes",
            entry_price=0.80,
            edge_pp=5.0,
            risk_budget=20.0,
            entry_time=datetime(2026, 4, 20, tzinfo=timezone.utc),
        )
        p.enter(
            ticker="T2",
            event_ticker="KXNFL-2026b",
            series_ticker="KXNFL",
            category="sports",
            side="sell_yes",
            entry_price=0.85,
            edge_pp=6.0,
            risk_budget=15.0,
            entry_time=datetime(2026, 4, 20, tzinfo=timezone.utc),
        )
        p.enter(
            ticker="T3",
            event_ticker="KXNFL-2026c",
            series_ticker="KXNFL",
            category="sports",
            side="buy_yes",
            entry_price=0.10,
            edge_pp=4.0,
            risk_budget=50.0,
            entry_time=datetime(2026, 4, 20, tzinfo=timezone.utc),
        )
        yield p


def test_resolves_settled_yes(portfolio):
    client = FakeClient({
        "T1": _mkt("T1", "settled", "yes"),
        "T2": _mkt("T2", "active"),
        "T3": _mkt("T3", "active"),
    })
    report = sweep(client, portfolio)
    assert report.resolved == 1
    assert report.still_open == 2
    open_now = {p.ticker for p in portfolio.open_positions()}
    assert "T1" not in open_now


def test_resolves_settled_no(portfolio):
    client = FakeClient({
        "T1": _mkt("T1", "settled", "no"),
        "T2": _mkt("T2", "active"),
        "T3": _mkt("T3", "active"),
    })
    sweep(client, portfolio)
    # sell_yes at 0.80 + no_result = reward 80, minus round-trip fees
    # (0.14 * 0.8 * 0.2 * 100 contracts = 2.24)
    assert portfolio.state().nav == pytest.approx(10_000.0 + 80.0 - 2.24)


def test_voids_market_with_voided_status(portfolio):
    client = FakeClient({
        "T1": _mkt("T1", "voided"),
        "T2": _mkt("T2", "active"),
        "T3": _mkt("T3", "active"),
    })
    report = sweep(client, portfolio)
    assert report.voided == 1
    assert portfolio.state().nav == pytest.approx(10_000.0)


def test_voids_finalized_with_no_result(portfolio):
    # Some markets finalize without a binary outcome; treat as void.
    client = FakeClient({
        "T1": _mkt("T1", "settled", ""),
        "T2": _mkt("T2", "active"),
        "T3": _mkt("T3", "active"),
    })
    report = sweep(client, portfolio)
    assert report.voided == 1


def test_counts_errors(portfolio):
    client = FakeClient({
        "T1": KalshiError("boom"),
        "T2": _mkt("T2", "active"),
        "T3": _mkt("T3", "active"),
    })
    report = sweep(client, portfolio)
    assert report.errors == 1
    assert report.still_open == 2


def test_handles_empty_portfolio(tmp_path):
    with PaperPortfolio(tmp_path / "empty.db") as p:
        client = FakeClient({})
        report = sweep(client, p)
    assert report.checked == 0
    assert report.total_closed == 0
