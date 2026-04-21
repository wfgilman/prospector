from datetime import datetime, timezone

import pytest

from prospector.kalshi.models import Market, Orderbook, OrderbookLevel
from prospector.underwriting.calibration import Calibration, build_bins_from_rows
from prospector.underwriting.portfolio import PaperPortfolio, PortfolioConfig
from prospector.underwriting.runner import RunnerConfig, run_once
from prospector.underwriting.sizing import SigmaEntry, SigmaTable


class FakeClient:
    """Minimal stub with scan and monitor surface."""

    def __init__(self, markets: list[Market], orderbooks: dict[str, Orderbook]):
        self._markets = markets
        self._orderbooks = orderbooks

    def iter_markets(self, *, status: str = "open", event_ticker: str | None = None, **_):
        for m in self._markets:
            if event_ticker is not None and m.event_ticker != event_ticker:
                continue
            yield m

    def iter_events(self, status: str = "open"):
        seen = set()
        for m in self._markets:
            if m.event_ticker and m.event_ticker not in seen:
                seen.add(m.event_ticker)
                yield {"event_ticker": m.event_ticker}

    def fetch_orderbook(self, ticker: str, depth: int = 1) -> Orderbook:
        return self._orderbooks[ticker]

    def fetch_market(self, ticker: str) -> Market:
        for m in self._markets:
            if m.ticker == ticker:
                return m
        raise KeyError(ticker)


def _mkt(ticker: str, event_ticker: str = "KXNFL-2026", status: str = "active") -> Market:
    return Market(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker="KXNFL",
        title="t",
        status=status,
        result="",
        open_time=datetime(2026, 4, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        expiration_time=None,
        yes_bid=0.50,
        yes_ask=None,
        no_bid=0.50,
        no_ask=None,
        last_price=None,
        volume=100,
        open_interest=50,
        category="",
        raw={},
    )


def _ob(yes: list[tuple[float, int]], no: list[tuple[float, int]]) -> Orderbook:
    return Orderbook(
        ticker="T",
        yes=[OrderbookLevel(p, s) for p, s in yes],
        no=[OrderbookLevel(p, s) for p, s in no],
    )


@pytest.fixture
def calibration():
    # Strong sell-yes signal at implied 80-85%: actual 72% (dev -10.5pp at mid).
    # Sized so every test price (0.82-0.84) clears the 5pp fee-adjusted floor.
    sports = build_bins_from_rows([(80, 85, 1_000, 720)])
    assert sports[0].side == "sell_yes"
    return Calibration(
        built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        data_window_start="x",
        data_window_end="y",
        min_volume=10,
        curves={"sports": sports, "aggregate": sports},
    )


@pytest.fixture
def portfolio(tmp_path):
    # Runner tests stage multiple positions on the same series/subseries; the
    # diversity caps get their own coverage in test_portfolio.
    cfg = PortfolioConfig(
        initial_nav=10_000.0,
        max_trades_per_day=5,
        max_position_frac=0.01,
        max_event_frac=1.0,
        max_bin_frac=1.0,
        max_positions_per_event=10,
        max_positions_per_subseries=10,
        max_positions_per_series=99,
    )
    with PaperPortfolio(tmp_path / "p.db", cfg) as p:
        yield p


@pytest.fixture
def sigma_table():
    # Flat 1.0 σ at every fallback level — tests don't exercise σ shape, only
    # that the runner routes σ through to the portfolio correctly.
    return SigmaTable(
        built_at="2026-04-20T00:00:00+00:00",
        source_window="test",
        aggregate=SigmaEntry(n=1000, mu=0.1, sigma=1.0),
        pooled={},
        bins={},
    )


def test_run_once_enters_candidates(portfolio, calibration, sigma_table):
    markets = [
        _mkt("T1", event_ticker="KXNFL-E1"),
        _mkt("T2", event_ticker="KXNFL-E2"),
    ]
    obs = {
        "T1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)]),
        "T2": _ob(yes=[(0.83, 500)], no=[(0.16, 500)]),
    }
    client = FakeClient(markets, obs)
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    report = run_once(client, portfolio, calibration, sigma_table, now=now)
    assert report.entered == 2
    assert portfolio.state().open_positions == 2


def test_run_once_respects_remaining_daily_cap(portfolio, calibration, sigma_table):
    # Pre-fill 4 of 5 trades
    for i in range(4):
        portfolio.enter(
            ticker=f"PRE-{i}",
            event_ticker=f"PRE-EV-{i}",
            series_ticker="X",
            category="sports",
            side="sell_yes",
            entry_price=0.80,
            edge_pp=5.0,
            risk_budget=20.0,
            entry_time=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
        )
    markets = [_mkt(f"T{i}", event_ticker=f"KXNFL-EV-{i}") for i in range(5)]
    obs = {m.ticker: _ob(yes=[(0.82, 500)], no=[(0.17, 500)]) for m in markets}
    # Monitor sweep will try to fetch the 4 pre-existing positions; include them
    # as still-active in the fake client so sweep is a no-op for them.
    for i in range(4):
        markets.append(_mkt(f"PRE-{i}", event_ticker=f"PRE-EV-{i}", status="active"))
    client = FakeClient(markets, obs)
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    report = run_once(client, portfolio, calibration, sigma_table, now=now)
    # Only 1 slot left
    assert report.entered == 1


def test_run_once_sorts_by_edge_desc(portfolio, calibration, sigma_table):
    # Two markets: one at implied 0.82 (better), one at 0.84 (smaller edge, closer to bin mid)
    markets = [
        _mkt("LOW", event_ticker="KXNFL-E1"),
        _mkt("HIGH", event_ticker="KXNFL-E2"),
    ]
    obs = {
        "LOW": _ob(yes=[(0.84, 500)], no=[(0.15, 500)]),
        "HIGH": _ob(yes=[(0.82, 500)], no=[(0.17, 500)]),
    }
    client = FakeClient(markets, obs)
    cfg = PortfolioConfig(
        initial_nav=10_000.0,
        max_trades_per_day=1,
        max_position_frac=0.01,
        max_event_frac=1.0,
        max_bin_frac=1.0,
        max_positions_per_event=10,
        max_positions_per_subseries=10,
        max_positions_per_series=99,
    )
    with PaperPortfolio(portfolio.db_path.parent / "p2.db", cfg) as port:
        report = run_once(client, port, calibration, sigma_table)
        assert report.entered == 1
        open_tickers = [p.ticker for p in port.open_positions()]
        # LOW's entry (0.84) is further above calibration (0.75) than HIGH's (0.82),
        # so LOW has the larger fee-adjusted edge and gets the one open slot.
        assert open_tickers == ["LOW"]


def test_run_once_resolves_and_enters_same_tick(portfolio, calibration, sigma_table):
    # Existing open position in a market that settled; scanner finds a new entry
    portfolio.enter(
        ticker="OLD",
        event_ticker="KXNFL-E-OLD",
        series_ticker="X",
        category="sports",
        side="sell_yes",
        entry_price=0.80,
        edge_pp=5.0,
        risk_budget=20.0,
        entry_time=datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc),
    )
    markets = [
        _mkt("OLD", event_ticker="KXNFL-E-OLD", status="settled"),
        _mkt("NEW", event_ticker="KXNFL-E-NEW"),
    ]
    # OLD settled "no" (win); NEW has an edge
    markets[0] = Market(**{**markets[0].__dict__, "result": "no"})
    obs = {"NEW": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])}
    client = FakeClient(markets, obs)
    report = run_once(client, portfolio, calibration, sigma_table)
    assert report.monitor.resolved == 1
    assert report.entered == 1
    # NAV bumped by the win
    assert portfolio.state().nav > 10_000.0


def test_run_once_writes_daily_snapshot(portfolio, calibration, sigma_table):
    client = FakeClient(
        [_mkt("T1", event_ticker="KXNFL-E1")],
        {"T1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])},
    )
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    run_once(client, portfolio, calibration, sigma_table, now=now)
    row = portfolio._conn.execute(
        "SELECT * FROM daily_snapshots WHERE snapshot_date = ?",
        ("2026-04-20",),
    ).fetchone()
    assert row is not None
    assert row["open_positions"] == 1


def test_run_once_filters_categories(portfolio, calibration, sigma_table):
    # Crypto event, but we only allow sports
    crypto_market = _mkt("KXETH-T1", event_ticker="KXETH-2026")
    client = FakeClient([crypto_market], {"KXETH-T1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])})
    config = RunnerConfig(categories=("sports",))
    report = run_once(client, portfolio, calibration, sigma_table, config)
    assert report.entered == 0


def test_run_once_respects_diversity_caps_by_default(tmp_path, calibration, sigma_table):
    """Under default strict caps, two candidates on the same event yield 1 entry."""
    cfg = PortfolioConfig(initial_nav=10_000.0, max_trades_per_day=20, max_position_frac=0.01)
    # Three markets on the SAME event — diversity cap should allow only one
    markets = [
        _mkt("A", event_ticker="KXNFL-E1"),
        _mkt("B", event_ticker="KXNFL-E1"),
        _mkt("C", event_ticker="KXNFL-E1"),
    ]
    obs = {m.ticker: _ob(yes=[(0.82, 500)], no=[(0.17, 500)]) for m in markets}
    client = FakeClient(markets, obs)
    with PaperPortfolio(tmp_path / "strict.db", cfg) as p:
        report = run_once(client, p, calibration, sigma_table)
        assert report.entered == 1
