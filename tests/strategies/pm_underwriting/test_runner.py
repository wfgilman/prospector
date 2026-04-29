from datetime import datetime, timedelta, timezone

import pytest

from prospector.kalshi.models import Market, Orderbook, OrderbookLevel
from prospector.strategies.pm_underwriting.calibration import Calibration, build_bins_from_rows
from prospector.strategies.pm_underwriting.portfolio import PaperPortfolio, PortfolioConfig
from prospector.strategies.pm_underwriting.runner import RunnerConfig, run_once
from prospector.strategies.pm_underwriting.sizing import SigmaEntry, SigmaTable


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
    # Canonical close_time = 12h after the canonical test "now" of
    # 2026-04-20 10:00 — sits inside the default time-to-close window
    # (6-24h) so most tests don't need to override it. Long-dated /
    # short-dated tests override via _mkt_with_close.
    return Market(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker="KXNFL",
        title="t",
        yes_sub_title="",
        no_sub_title="",
        status=status,
        result="",
        open_time=datetime(2026, 4, 20, 4, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 4, 20, 22, 0, tzinfo=timezone.utc),
        expiration_time=None,
        yes_bid=0.50,
        yes_ask=None,
        no_bid=0.50,
        no_ask=None,
        last_price=None,
        volume=100,
        volume_24h=0,
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
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    with PaperPortfolio(portfolio.db_path.parent / "p2.db", cfg) as port:
        report = run_once(client, port, calibration, sigma_table, now=now)
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
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    report = run_once(client, portfolio, calibration, sigma_table, now=now)
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
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    with PaperPortfolio(tmp_path / "strict.db", cfg) as p:
        report = run_once(client, p, calibration, sigma_table, now=now)
        assert report.entered == 1


def _mkt_with_close(ticker: str, close_time: datetime) -> Market:
    m = _mkt(ticker, event_ticker="KXNFL-E1")
    # Market dataclass is frozen; build a fresh one with the close_time
    # overridden.
    return Market(**{**m.__dict__, "close_time": close_time})


def test_time_to_close_window_rejects_outside_band(
    tmp_path, portfolio, calibration, sigma_table
):
    """Markets outside [min_hours_to_close, max_hours_to_close] get shadow-
    rejected instead of entered; their metadata lands in the shadow parquet
    for counterfactual replay. Window default is 6-24h, mirroring the PIT
    distribution the calibration was fit on."""
    now = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
    too_soon_close = now + timedelta(hours=2)        # < 6h
    in_window_close = now + timedelta(hours=12)      # in [6, 24]
    too_late_close = now + timedelta(days=10)        # > 24h

    markets = [
        _mkt_with_close("TOOSOON", too_soon_close),
        _mkt_with_close("INWIN", in_window_close),
        _mkt_with_close("TOOLATE", too_late_close),
    ]
    obs = {m.ticker: _ob(yes=[(0.82, 500)], no=[(0.17, 500)]) for m in markets}
    client = FakeClient(markets, obs)

    shadow_root = tmp_path / "shadow_root"
    config = RunnerConfig(
        min_hours_to_close=6.0,
        max_hours_to_close=24.0,
        shadow_ledger_root=shadow_root,
    )
    report = run_once(client, portfolio, calibration, sigma_table, config, now=now)

    assert report.entered == 1
    assert report.shadow_rejected == 2
    assert portfolio.has_open_position("INWIN")
    assert not portfolio.has_open_position("TOOSOON")
    assert not portfolio.has_open_position("TOOLATE")

    shadow_path = shadow_root / "shadow" / "shadow_rejections.parquet"
    import pandas as pd
    df = pd.read_parquet(shadow_path).sort_values("ticker").reset_index(drop=True)
    assert len(df) == 2
    by_ticker = df.set_index("ticker")
    assert by_ticker.loc["TOOLATE", "reject_reason"] == "ttc_gt_24h"
    assert by_ticker.loc["TOOSOON", "reject_reason"] == "ttc_lt_6h"
    for ticker in ("TOOSOON", "TOOLATE"):
        assert by_ticker.loc[ticker, "edge_pp"] > 0
        assert by_ticker.loc[ticker, "sigma_bin"] > 0
        assert by_ticker.loc[ticker, "risk_budget"] > 0


def test_time_to_close_window_disabled_when_bounds_are_none(
    tmp_path, portfolio, calibration, sigma_table
):
    """min_/max_hours_to_close = None disables the relevant edge of the
    screen — letting long-dated and same-tick markets through."""
    now = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
    long_dated_close = datetime(2027, 3, 1, tzinfo=timezone.utc)
    market = _mkt_with_close("LONG", long_dated_close)
    client = FakeClient(
        [market], {"LONG": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])}
    )
    config = RunnerConfig(
        min_hours_to_close=None,
        max_hours_to_close=None,
        shadow_ledger_root=tmp_path,
    )
    report = run_once(client, portfolio, calibration, sigma_table, config, now=now)
    assert report.entered == 1
    assert report.shadow_rejected == 0
    assert portfolio.has_open_position("LONG")


def test_time_to_close_screen_no_shadow_root_means_no_parquet(
    tmp_path, portfolio, calibration, sigma_table
):
    """If shadow_ledger_root is None, the screen still applies but nothing
    is written to disk (useful for unit tests)."""
    now = datetime(2026, 4, 23, 10, 0, tzinfo=timezone.utc)
    long_dated_close = datetime(2027, 3, 1, tzinfo=timezone.utc)
    market = _mkt_with_close("LONG", long_dated_close)
    client = FakeClient(
        [market], {"LONG": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])}
    )
    config = RunnerConfig(
        min_hours_to_close=6.0,
        max_hours_to_close=24.0,
        shadow_ledger_root=None,
    )
    report = run_once(client, portfolio, calibration, sigma_table, config, now=now)
    assert report.shadow_rejected == 1
    assert not portfolio.has_open_position("LONG")


def test_entry_price_band_excludes_out_of_band_candidates(
    portfolio, calibration, sigma_table
):
    """Insurance-book scoping: with a 0.55-0.75 band, candidates entering
    at 0.82-0.84 (the calibration's signal range) are filtered out."""
    markets = [
        _mkt("HI1", event_ticker="KXNFL-E1"),
        _mkt("HI2", event_ticker="KXNFL-E2"),
    ]
    obs = {
        "HI1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)]),
        "HI2": _ob(yes=[(0.83, 500)], no=[(0.16, 500)]),
    }
    client = FakeClient(markets, obs)
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    config = RunnerConfig(entry_price_min=0.55, entry_price_max=0.75)
    report = run_once(client, portfolio, calibration, sigma_table, config, now=now)
    assert report.entered == 0
    assert portfolio.state().open_positions == 0


def test_entry_price_band_includes_in_band_candidates(
    portfolio, calibration, sigma_table
):
    """Same fixture, looser band that includes 0.82-0.84 — entries proceed."""
    markets = [
        _mkt("HI1", event_ticker="KXNFL-E1"),
        _mkt("HI2", event_ticker="KXNFL-E2"),
    ]
    obs = {
        "HI1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)]),
        "HI2": _ob(yes=[(0.83, 500)], no=[(0.16, 500)]),
    }
    client = FakeClient(markets, obs)
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    config = RunnerConfig(entry_price_min=0.70, entry_price_max=0.95)
    report = run_once(client, portfolio, calibration, sigma_table, config, now=now)
    assert report.entered == 2


def test_entry_price_band_default_is_full_range(portfolio, calibration, sigma_table):
    """Default RunnerConfig (no band overrides) accepts the full [0, 1]
    range — preserves the lottery-book behavior."""
    markets = [_mkt("T1", event_ticker="KXNFL-E1")]
    obs = {"T1": _ob(yes=[(0.82, 500)], no=[(0.17, 500)])}
    client = FakeClient(markets, obs)
    now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    report = run_once(client, portfolio, calibration, sigma_table, RunnerConfig(), now=now)
    assert report.entered == 1
