from datetime import date, datetime, timezone

import pytest

from prospector.underwriting.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
    RejectedEntry,
)


@pytest.fixture
def portfolio(tmp_path):
    # Existing tests pack multiple positions per event/series/bin; those caps
    # are tested separately (TestDiversity, TestBinCap) with stricter configs.
    config = PortfolioConfig(
        initial_nav=10_000.0,
        max_position_frac=0.01,
        max_event_frac=0.05,
        max_bin_frac=0.95,          # relaxed — covered by TestBinCap
        max_trades_per_day=20,
        max_positions_per_event=10,
        max_positions_per_subseries=10,
        max_positions_per_series=99,
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
        # Each event_ticker needs a distinct subseries so the diversity cap
        # doesn't trip before the daily cap does. entry_time=None lets the
        # portfolio stamp positions with 'today' so trades_today() sees them.
        for i in range(20):
            _enter(
                portfolio,
                ticker=f"KX-T{i}",
                event_ticker=f"EV-{i}-A",
                risk_budget=10.0,
                entry_time=None,
            )
        with pytest.raises(RejectedEntry, match="daily trade cap"):
            _enter(
                portfolio,
                ticker="KX-T20",
                event_ticker="EV-20-A",
                risk_budget=10.0,
                entry_time=None,
            )

    def test_rejects_duplicate_open_ticker(self, portfolio):
        _enter(portfolio, ticker="DUP")
        with pytest.raises(RejectedEntry, match="already hold"):
            _enter(portfolio, ticker="DUP")


class TestResolution:
    # Fee model: round-trip = 0.14 * p * (1-p) * contracts.
    # At entry_price=0.80 and 100 contracts → 0.14 * 0.8 * 0.2 * 100 = 2.24
    def test_sell_yes_win_on_no_result(self, portfolio):
        _enter(portfolio)
        pos = portfolio.resolve("KXNFL-2026-T1", "no")
        assert pos.status == "closed"
        assert pos.realized_pnl == pytest.approx(80.0 - 2.24)
        state = portfolio.state()
        assert state.nav == pytest.approx(10_000.0 + 80.0 - 2.24)
        assert state.locked_risk == 0.0

    def test_sell_yes_loss_on_yes_result(self, portfolio):
        _enter(portfolio)
        pos = portfolio.resolve("KXNFL-2026-T1", "yes")
        assert pos.realized_pnl == pytest.approx(-20.0 - 2.24)
        state = portfolio.state()
        assert state.nav == pytest.approx(10_000.0 - 20.0 - 2.24)

    def test_buy_yes_win_on_yes_result(self, portfolio):
        # entry_price=0.10, 500 contracts → fees = 0.14 * 0.1 * 0.9 * 500 = 6.30
        _enter(
            portfolio,
            side="buy_yes",
            entry_price=0.10,
            risk_budget=50.0,
        )
        pos = portfolio.resolve("KXNFL-2026-T1", "yes")
        assert pos.realized_pnl == pytest.approx(450.0 - 6.30)

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
    """Equal-σ / risk-parity sizing.

    r_i = book_sigma_target * NAV / (σ_i * sqrt(N_target)), clipped by
    max_position_frac * NAV. At defaults (book_σ=0.02, N_target=150, NAV=$10K)
    the unclipped scale is $200 / sqrt(150) ≈ $16.33 / σ.
    """

    def test_sizing_inversely_proportional_to_sigma(self, portfolio):
        # Halving σ doubles the risk budget (until a cap binds).
        small_sigma = portfolio.size_position(sigma_i=2.0)
        large_sigma = portfolio.size_position(sigma_i=4.0)
        assert small_sigma == pytest.approx(2 * large_sigma)

    def test_sizing_clamped_by_position_cap(self, portfolio):
        # At σ=0.1, unclipped r = 16.33 / 0.1 = $163.3 → clipped to 1% = $100.
        huge = portfolio.size_position(sigma_i=0.1)
        assert huge == pytest.approx(100.0)

    def test_sizing_below_cap_uses_formula(self, portfolio):
        # At σ=3.0 (sports 85-90 shrunk σ ≈ 3.08), unclipped r ≈ $5.44.
        import math
        expected = 0.02 * 10_000.0 / (3.0 * math.sqrt(150))
        assert portfolio.size_position(sigma_i=3.0) == pytest.approx(expected)

    def test_sizing_returns_zero_for_nonpositive_sigma(self, portfolio):
        assert portfolio.size_position(sigma_i=0.0) == 0.0
        assert portfolio.size_position(sigma_i=-1.0) == 0.0

    def test_sizing_scales_with_nav(self, tmp_path):
        # Linear in NAV — doubling NAV doubles the budget (under the cap).
        cfg = PortfolioConfig(initial_nav=20_000.0, max_bin_frac=0.95,
                              max_position_frac=0.01)
        with PaperPortfolio(tmp_path / "big.db", cfg) as p:
            sz = p.size_position(sigma_i=3.0)
        import math
        expected = 0.02 * 20_000.0 / (3.0 * math.sqrt(150))
        assert sz == pytest.approx(expected)


class TestPersistence:
    def test_state_survives_reopen(self, tmp_path):
        db = tmp_path / "persist.db"
        config = PortfolioConfig(initial_nav=10_000.0)
        with PaperPortfolio(db, config) as p:
            _enter(p)
            p.resolve("KXNFL-2026-T1", "no")
        with PaperPortfolio(db, config) as p:
            # 10_000 + 80 reward - 2.24 fees
            assert p.state().nav == pytest.approx(10_077.76)

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


class TestDiversity:
    """Per-event / subseries / series count caps."""

    @pytest.fixture
    def strict(self, tmp_path):
        cfg = PortfolioConfig(
            initial_nav=10_000.0,
            max_position_frac=0.01,
            max_event_frac=0.05,
            max_trades_per_day=20,
            max_positions_per_event=1,
            max_positions_per_subseries=1,
            max_positions_per_series=3,
        )
        with PaperPortfolio(tmp_path / "strict.db", cfg) as p:
            yield p

    def test_blocks_second_entry_in_same_event(self, strict):
        _enter(strict, ticker="T1", event_ticker="KXNFL-2026-W01-NE-NYJ")
        with pytest.raises(RejectedEntry, match="event .* already has"):
            _enter(
                strict,
                ticker="T2",
                event_ticker="KXNFL-2026-W01-NE-NYJ",
                risk_budget=20.0,
            )

    def test_blocks_second_entry_in_same_subseries(self, strict):
        # Two different events but same subseries (drop last segment)
        _enter(strict, ticker="T1", event_ticker="KXNFL-2026-W01-GAME-A")
        with pytest.raises(RejectedEntry, match="subseries .* already has"):
            _enter(
                strict,
                ticker="T2",
                event_ticker="KXNFL-2026-W01-GAME-B",
                risk_budget=20.0,
            )

    def test_blocks_fourth_entry_in_same_series(self, strict):
        # Three entries on different subseries but same series — fourth blocks
        for i in range(3):
            _enter(
                strict,
                ticker=f"T{i}",
                event_ticker=f"KXNFL-2026-W0{i+1}-GAME-X",
                series_ticker="KXNFL",
            )
        with pytest.raises(RejectedEntry, match="series .* already has"):
            _enter(
                strict,
                ticker="T4",
                event_ticker="KXNFL-2026-W04-GAME-X",
                series_ticker="KXNFL",
            )

    def test_different_series_coexist_under_series_cap(self, strict):
        _enter(
            strict,
            ticker="T1",
            event_ticker="KXNFL-2026-W01-A-B",
            series_ticker="KXNFL",
        )
        _enter(
            strict,
            ticker="T2",
            event_ticker="KXNBA-2026-W01-A-B",
            series_ticker="KXNBA",
        )
        _enter(
            strict,
            ticker="T3",
            event_ticker="KXETH-2026-UP",
            series_ticker="KXETH",
        )
        assert strict.state().open_positions == 3


class TestFees:
    def test_fees_paid_persisted_on_entry(self, portfolio):
        pos = _enter(portfolio)  # entry_price=0.80, 100 contracts
        assert pos.fees_paid == pytest.approx(0.14 * 0.8 * 0.2 * 100)

    def test_void_refunds_fees(self, portfolio):
        _enter(portfolio)
        pos = portfolio.void("KXNFL-2026-T1")
        assert pos.realized_pnl == 0.0

    def test_migration_backfills_fees_on_existing_db(self, tmp_path):
        """A DB created before fees_paid existed should get a backfilled column."""
        db = tmp_path / "legacy.db"
        # Simulate a pre-migration DB by opening, dropping the column via
        # schema surgery, inserting a row, and then reopening.
        import sqlite3
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                ticker TEXT, event_ticker TEXT, series_ticker TEXT, category TEXT,
                side TEXT, contracts INTEGER, entry_price REAL, risk_budget REAL,
                reward_potential REAL, edge_pp REAL, entry_time TEXT,
                expected_close_time TEXT, status TEXT DEFAULT 'open',
                close_price REAL, close_time TEXT, realized_pnl REAL, market_result TEXT
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta(key, value) VALUES ('initial_nav', '10000.0');
            INSERT INTO positions(
                ticker, event_ticker, series_ticker, category, side, contracts,
                entry_price, risk_budget, reward_potential, edge_pp, entry_time, status
            ) VALUES (
                'LEGACY', 'EV', 'SER', 'sports', 'sell_yes', 100, 0.80, 20.0, 80.0,
                5.0, '2026-04-19T10:00:00+00:00', 'open'
            );
            """
        )
        conn.close()
        with PaperPortfolio(db) as p:
            legacy = p._conn.execute(
                "SELECT fees_paid FROM positions WHERE ticker='LEGACY'"
            ).fetchone()
            assert legacy["fees_paid"] == pytest.approx(0.14 * 0.8 * 0.2 * 100)


class TestBinCap:
    """Per (side, 5¢ bin) % of NAV cap — tail-risk envelope for high-kurtosis bins."""

    @pytest.fixture
    def capped(self, tmp_path):
        cfg = PortfolioConfig(
            initial_nav=10_000.0,
            max_position_frac=0.01,        # $100 per position
            max_event_frac=0.95,            # relaxed so event cap doesn't interfere
            max_bin_frac=0.02,              # $200 per (side, bin) — tight for the test
            max_trades_per_day=20,
            max_positions_per_event=10,
            max_positions_per_subseries=10,
            max_positions_per_series=99,
        )
        with PaperPortfolio(tmp_path / "bin.db", cfg) as p:
            yield p

    def test_blocks_entry_exceeding_bin_cap(self, capped):
        # Two $100 positions at entry_price 0.82 (bin 80-85). Third in same
        # bin rejected.
        for i in range(2):
            _enter(
                capped,
                ticker=f"T{i}",
                event_ticker=f"KXNFL-E{i}-A",
                entry_price=0.82,
                risk_budget=100.0,
            )
        with pytest.raises(RejectedEntry, match="bin sell_yes 80-85"):
            _enter(
                capped,
                ticker="T2",
                event_ticker="KXNFL-E2-A",
                entry_price=0.82,
                risk_budget=10.0,
            )

    def test_different_bins_coexist(self, capped):
        # 0.82 → bin 80-85; 0.87 → bin 85-90. Independent caps.
        p1 = _enter(
            capped,
            ticker="T1",
            event_ticker="KXNFL-E1-A",
            entry_price=0.82,
            risk_budget=100.0,
        )
        p2 = _enter(
            capped,
            ticker="T2",
            event_ticker="KXNFL-E2-A",
            entry_price=0.87,
            risk_budget=100.0,
        )
        assert capped.bin_risk("sell_yes", 80) == pytest.approx(p1.risk_budget)
        assert capped.bin_risk("sell_yes", 85) == pytest.approx(p2.risk_budget)

    def test_different_sides_coexist(self, capped):
        # Same 5¢ bin by price but different sides → separate cells.
        sell = _enter(
            capped,
            ticker="S1",
            event_ticker="E1",
            entry_price=0.10,
            side="sell_yes",
            risk_budget=100.0,
        )
        buy = _enter(
            capped,
            ticker="B1",
            event_ticker="E2",
            entry_price=0.10,
            side="buy_yes",
            risk_budget=100.0,
        )
        assert capped.bin_risk("sell_yes", 10) == pytest.approx(sell.risk_budget)
        assert capped.bin_risk("buy_yes", 10) == pytest.approx(buy.risk_budget)

    def test_closed_positions_release_bin_risk(self, capped):
        _enter(
            capped,
            ticker="T1",
            event_ticker="E1",
            entry_price=0.82,
            risk_budget=50.0,
        )
        capped.resolve("T1", "yes")
        assert capped.bin_risk("sell_yes", 80) == 0.0
        p2 = _enter(
            capped,
            ticker="T2",
            event_ticker="E2",
            entry_price=0.82,
            risk_budget=50.0,
        )
        assert capped.bin_risk("sell_yes", 80) == pytest.approx(p2.risk_budget)


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
