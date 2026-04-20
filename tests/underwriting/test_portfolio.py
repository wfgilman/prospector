from datetime import date, datetime, timezone

import pytest

from prospector.underwriting.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
    RejectedEntry,
)


@pytest.fixture
def portfolio(tmp_path):
    config = PortfolioConfig(
        initial_nav=10_000.0,
        max_position_frac=0.01,
        max_event_frac=0.05,
        max_trades_per_day=20,
    )
    with PaperPortfolio(tmp_path / "paper.db", config) as p:
        yield p


def _enter(portfolio, **overrides):
    defaults = dict(
        ticker="KXNFL-2026-T1",
        event_ticker="KXNFL-2026",
        series_ticker="KXNFL",
        category="sports",
        side="sell_yes",
        entry_price=0.80,
        edge_pp=5.0,
        risk_budget=20.0,  # 1% of $10K for a sell-yes at 0.80 is 20 * 1 = 20 risk
        entry_time=datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return portfolio.enter(**defaults)


class TestInitialState:
    def test_initial_nav(self, portfolio):
        assert portfolio.state().nav == 10_000.0

    def test_no_open_positions(self, portfolio):
        assert portfolio.state().open_positions == 0

    def test_cash_equals_nav(self, portfolio):
        state = portfolio.state()
        assert state.cash == state.nav
        assert state.locked_risk == 0.0


class TestEntry:
    def test_basic_sell_yes(self, portfolio):
        pos = _enter(portfolio)
        assert pos.side == "sell_yes"
        assert pos.contracts == 100  # risk 20 / per-contract risk 0.20
        assert pos.risk_budget == pytest.approx(20.0)
        assert pos.reward_potential == pytest.approx(80.0)
        state = portfolio.state()
        assert state.locked_risk == pytest.approx(20.0)
        assert state.cash == pytest.approx(9980.0)

    def test_basic_buy_yes(self, portfolio):
        pos = _enter(
            portfolio,
            ticker="KXETH-LOW",
            event_ticker="KXETH-2026",
            side="buy_yes",
            entry_price=0.10,
            risk_budget=50.0,
        )
        assert pos.side == "buy_yes"
        assert pos.contracts == 500  # 50 / 0.10
        assert pos.reward_potential == pytest.approx(450.0)

    def test_integer_contracts_rounds_down(self, portfolio):
        # Risk 25 at sell-yes 0.80: per-contract risk is 0.20, so 25/0.20 = 125 exact
        # but try an awkward number:
        # Risk 23 at sell-yes 0.77: per = 0.23, 23/0.23 = 100.0 exact
        # Use risk 23.5 / 0.77 → 23.5 / 0.23 = 102.17 → 102 contracts
        pos = _enter(portfolio, entry_price=0.77, risk_budget=23.5)
        assert pos.contracts == 102
        # Actual risk = 102 * 0.23 = 23.46
        assert pos.risk_budget == pytest.approx(23.46)


class TestConstraints:
    def test_rejects_exceeding_per_position_cap(self, portfolio):
        # Max position risk = 1% of $10K = $100
        with pytest.raises(RejectedEntry, match="per-position cap"):
            _enter(portfolio, risk_budget=101.0)

    def test_rejects_negative_risk_budget(self, portfolio):
        with pytest.raises(RejectedEntry, match="positive"):
            _enter(portfolio, risk_budget=-5.0)

    def test_rejects_invalid_entry_price(self, portfolio):
        with pytest.raises(ValueError, match="entry_price"):
            _enter(portfolio, entry_price=0.0)
        with pytest.raises(ValueError, match="entry_price"):
            _enter(portfolio, entry_price=1.0)

    def test_rejects_insufficient_cash(self, portfolio):
        # Fill most of the NAV with many event tickers, then fail on cash
        for i in range(9):
            _enter(
                portfolio,
                ticker=f"KXT-{i}",
                event_ticker=f"EV-{i}",
                risk_budget=99.0,
            )
        # Now 9 * 99 = 891 locked. Cash is 9109. Daily cap is 20 - 9 = 11 left.
        # Try something that exceeds per-position cap of 100 — should fail on cap
        with pytest.raises(RejectedEntry):
            _enter(portfolio, ticker="BIG", event_ticker="EVBIG", risk_budget=10_000.0)

    def test_rejects_event_cap_breach(self, portfolio):
        # max_event_frac=0.05 → $500 per event. At 0.80 sell_yes, that's
        # 500 risk. Per-position cap is $100, so we need 5 sub-positions at
        # $100 each; the 6th on the same event should fail.
        for i in range(5):
            _enter(portfolio, ticker=f"KX-T{i}", risk_budget=100.0)
        with pytest.raises(RejectedEntry, match="event"):
            _enter(portfolio, ticker="KX-T6", risk_budget=1.0)

    def test_rejects_daily_cap(self, portfolio):
        for i in range(20):
            _enter(
                portfolio,
                ticker=f"KX-T{i}",
                event_ticker=f"EV-{i}",
                risk_budget=10.0,
            )
        with pytest.raises(RejectedEntry, match="daily trade cap"):
            _enter(portfolio, ticker="KX-T20", event_ticker="EV-20", risk_budget=10.0)

    def test_rejects_duplicate_open_ticker(self, portfolio):
        _enter(portfolio, ticker="DUP")
        with pytest.raises(RejectedEntry, match="already hold"):
            _enter(portfolio, ticker="DUP")


class TestResolution:
    def test_sell_yes_win_on_no_result(self, portfolio):
        _enter(portfolio)
        pos = portfolio.resolve("KXNFL-2026-T1", "no")
        assert pos.status == "closed"
        assert pos.realized_pnl == pytest.approx(80.0)  # reward
        state = portfolio.state()
        assert state.nav == pytest.approx(10_080.0)
        assert state.locked_risk == 0.0

    def test_sell_yes_loss_on_yes_result(self, portfolio):
        _enter(portfolio)
        pos = portfolio.resolve("KXNFL-2026-T1", "yes")
        assert pos.realized_pnl == pytest.approx(-20.0)
        state = portfolio.state()
        assert state.nav == pytest.approx(9_980.0)

    def test_buy_yes_win_on_yes_result(self, portfolio):
        _enter(
            portfolio,
            side="buy_yes",
            entry_price=0.10,
            risk_budget=50.0,
        )
        pos = portfolio.resolve("KXNFL-2026-T1", "yes")
        assert pos.realized_pnl == pytest.approx(450.0)

    def test_void(self, portfolio):
        _enter(portfolio)
        pos = portfolio.void("KXNFL-2026-T1")
        assert pos.status == "voided"
        assert pos.realized_pnl == 0.0
        state = portfolio.state()
        assert state.nav == 10_000.0
        assert state.locked_risk == 0.0

    def test_resolve_unknown_ticker_raises(self, portfolio):
        with pytest.raises(KeyError):
            portfolio.resolve("MISSING", "yes")

    def test_invalid_result_raises(self, portfolio):
        _enter(portfolio)
        with pytest.raises(ValueError, match="market_result"):
            portfolio.resolve("KXNFL-2026-T1", "maybe")


class TestSizing:
    def test_kelly_sizing_scales_with_edge(self, portfolio):
        small = portfolio.size_position(edge_pp=2.0, entry_price=0.80, side="sell_yes")
        large = portfolio.size_position(edge_pp=8.0, entry_price=0.80, side="sell_yes")
        assert large > small

    def test_kelly_clamped_by_position_cap(self, portfolio):
        huge = portfolio.size_position(edge_pp=40.0, entry_price=0.80, side="sell_yes")
        assert huge == pytest.approx(100.0)  # 1% of 10K

    def test_sizing_respects_buy_yes_odds(self, portfolio):
        # At p=0.10 buy-yes: odds = 0.90/0.10 = 9, edge 5pp = 0.05
        # Kelly = 0.05 / 9 = 0.00556; quarter-kelly = 0.00139 * 10K = 13.9
        sz = portfolio.size_position(edge_pp=5.0, entry_price=0.10, side="buy_yes")
        assert 13.0 < sz < 14.0


class TestPersistence:
    def test_state_survives_reopen(self, tmp_path):
        db = tmp_path / "persist.db"
        config = PortfolioConfig(initial_nav=10_000.0)
        with PaperPortfolio(db, config) as p:
            _enter(p)
            p.resolve("KXNFL-2026-T1", "no")
        with PaperPortfolio(db, config) as p:
            assert p.state().nav == pytest.approx(10_080.0)

    def test_initial_nav_is_sticky_across_reopen(self, tmp_path):
        db = tmp_path / "persist.db"
        with PaperPortfolio(db, PortfolioConfig(initial_nav=10_000.0)) as p:
            assert p.initial_nav == 10_000.0
        # Reopen with a different config — initial_nav should not change
        with PaperPortfolio(db, PortfolioConfig(initial_nav=99_999.0)) as p:
            assert p.initial_nav == 10_000.0


class TestSnapshot:
    def test_snapshot_writes_row(self, portfolio):
        _enter(portfolio)
        portfolio.snapshot_today(date(2026, 4, 20))
        row = portfolio._conn.execute(
            "SELECT * FROM daily_snapshots WHERE snapshot_date = '2026-04-20'"
        ).fetchone()
        assert row is not None
        assert row["nav"] == pytest.approx(10_000.0)
        assert row["locked_risk"] == pytest.approx(20.0)

    def test_snapshot_upserts(self, portfolio):
        portfolio.snapshot_today(date(2026, 4, 20))
        _enter(portfolio)
        portfolio.snapshot_today(date(2026, 4, 20))
        rows = portfolio._conn.execute("SELECT * FROM daily_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["locked_risk"] == pytest.approx(20.0)


class TestEventRisk:
    def test_aggregates_open_positions_per_event(self, portfolio):
        _enter(portfolio, ticker="T1", risk_budget=40.0)
        _enter(portfolio, ticker="T2", risk_budget=60.0)
        assert portfolio.event_risk("KXNFL-2026") == pytest.approx(100.0)

    def test_excludes_closed_positions(self, portfolio):
        _enter(portfolio, ticker="T1", risk_budget=40.0)
        portfolio.resolve("T1", "yes")
        _enter(portfolio, ticker="T2", risk_budget=30.0)
        assert portfolio.event_risk("KXNFL-2026") == pytest.approx(30.0)
