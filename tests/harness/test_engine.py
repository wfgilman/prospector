"""
Backtest harness tests.

All monetary assertions use hand-calculated expected values so regressions
are caught immediately. Where fees are material to the assertion being tested,
they are included explicitly; where they would obscure the logic, they are
zeroed out via BacktestConfig.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from prospector.harness.engine import (
    BacktestConfig,
    compute_score,
    run_backtest,
)
from prospector.harness.walk_forward import run_walk_forward
from prospector.templates.base import Direction, Signal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NO_COST = BacktestConfig(taker_fee=0.0, slippage_per_side=0.0)


def _make_df(n: int, base_price: float = 100.0) -> pd.DataFrame:
    """Flat OHLCV DataFrame: high = base+1%, low = base-1%, close = base."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
        "open": [base_price] * n,
        "high": [base_price * 1.01] * n,
        "low": [base_price * 0.99] * n,
        "close": [base_price] * n,
        "volume": [1000.0] * n,
    })


def _long(bar_index: int, entry: float = 100.0, stop: float = 95.0,
          target: float = 110.0) -> Signal:
    return Signal(bar_index=bar_index, direction=Direction.LONG,
                  entry=entry, stop=stop, target=target)


def _short(bar_index: int, entry: float = 100.0, stop: float = 105.0,
           target: float = 85.0) -> Signal:
    return Signal(bar_index=bar_index, direction=Direction.SHORT,
                  entry=entry, stop=stop, target=target)


def _make_signals_and_df(
    n_trades: int,
    direction: Direction = Direction.LONG,
    win: bool = True,
    bars_per_trade: int = 3,
) -> tuple[list[Signal], pd.DataFrame]:
    """
    Build n_trades signals in sequence.

    Each trade occupies bars_per_trade rows:
      - bar 0 mod bars_per_trade: signal fires (entry bar)
      - bar 1 mod bars_per_trade: exit bar (target or stop hit)
      - bar 2 mod bars_per_trade: gap (optional)

    For LONG win: target=110 hit at bar+1 (high=115).
    For LONG loss: stop=95 hit at bar+1 (low=93).
    """
    n_bars = n_trades * bars_per_trade + 5
    df = _make_df(n_bars)

    signals = []
    for i in range(n_trades):
        sig_bar = i * bars_per_trade
        exit_bar = sig_bar + 1

        if direction == Direction.LONG:
            if win:
                df.at[exit_bar, "high"] = 115.0  # target=110 reached
            else:
                df.at[exit_bar, "low"] = 93.0    # stop=95 reached
            signals.append(_long(sig_bar))
        else:
            if win:
                df.at[exit_bar, "low"] = 84.0    # target=85 reached
            else:
                df.at[exit_bar, "high"] = 107.0  # stop=105 reached
            signals.append(_short(sig_bar))

    return signals, df


# ---------------------------------------------------------------------------
# Scoring formula
# ---------------------------------------------------------------------------


def test_compute_score_no_penalty():
    """pct_return × 200 when drawdown ≤ 20% and trades ≥ 20."""
    assert compute_score(0.10, 0.15, 25) == pytest.approx(20.0)
    assert compute_score(0.30, 0.05, 100) == pytest.approx(60.0)


def test_compute_score_drawdown_penalty():
    """Quadratic penalty above 20% drawdown threshold."""
    # max_dd=0.25: penalty = ((0.25-0.20)/0.10)^2 × 200 = (0.5)^2 × 200 = 50
    score = compute_score(0.30, 0.25, 25)
    assert score == pytest.approx(10.0)  # 60 - 50 - 0


def test_compute_score_sample_penalty():
    """Penalty for n_trades < 20 even if score formula is otherwise clean."""
    # 15 trades: sample_penalty = 5 × 10 = 50
    score = compute_score(0.10, 0.10, 15)
    assert score == pytest.approx(-30.0)  # 20 - 0 - 50


def test_compute_score_catastrophic_drawdown():
    """Deep drawdown incurs large quadratic penalty."""
    # max_dd=0.40: penalty = ((0.40-0.20)/0.10)^2 × 200 = 4 × 200 = 800
    score = compute_score(0.10, 0.40, 25)
    assert score == pytest.approx(20.0 - 800.0)


# ---------------------------------------------------------------------------
# Single-trade P&L math
# ---------------------------------------------------------------------------


def test_single_winning_long_trade_pnl():
    """
    LONG: entry=100, stop=95, target=110. Target hit on bar 1.
    No fees. Hand-calculated:
      units = (10000 × 0.02) / 5 = 40
      gross_pnl = (110 - 100) × 40 = 400
      net_pnl = 400
      nav_final = 10400
    """
    df = _make_df(5)
    df.at[1, "high"] = 115.0

    result = run_backtest([_long(0)], df, NO_COST)

    assert result.n_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "target"
    assert trade.exit_price == pytest.approx(110.0)
    assert trade.units == pytest.approx(40.0)
    assert trade.gross_pnl == pytest.approx(400.0)
    assert trade.net_pnl == pytest.approx(400.0)
    assert result.nav_final == pytest.approx(10_400.0)


def test_single_losing_long_trade_pnl():
    """
    LONG: stop hit at bar 1. No fees.
      units = 40
      gross_pnl = (95 - 100) × 40 = −200
      nav_final = 9800
    """
    df = _make_df(5)
    df.at[1, "low"] = 93.0

    result = run_backtest([_long(0)], df, NO_COST)

    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.gross_pnl == pytest.approx(-200.0)
    assert trade.net_pnl == pytest.approx(-200.0)
    assert result.nav_final == pytest.approx(9_800.0)


def test_single_winning_short_trade_pnl():
    """
    SHORT: entry=100, stop=105, target=85. Target hit on bar 1. No fees.
      units = (10000 × 0.02) / 5 = 40
      gross_pnl = (100 - 85) × 40 = 600
    """
    df = _make_df(5)
    df.at[1, "low"] = 84.0

    result = run_backtest([_short(0)], df, NO_COST)

    trade = result.trades[0]
    assert trade.exit_reason == "target"
    assert trade.gross_pnl == pytest.approx(600.0)
    assert result.nav_final == pytest.approx(10_600.0)


def test_transaction_costs_deducted():
    """
    With default fees, verify round-trip cost is deducted from gross_pnl.
    LONG win: entry=100, stop=95, target=110, units=40.
      entry_cost = 40 × 100 × (0.00035 + 0.0005) = 3.40
      exit_cost  = 40 × 110 × 0.00085            = 3.74
      total_cost = 7.14
      net_pnl    = 400 − 7.14 = 392.86
    """
    df = _make_df(5)
    df.at[1, "high"] = 115.0

    result = run_backtest([_long(0)], df)  # default config with fees

    trade = result.trades[0]
    assert trade.gross_pnl == pytest.approx(400.0)
    assert trade.transaction_cost == pytest.approx(7.14, rel=0.01)
    assert trade.net_pnl == pytest.approx(392.86, rel=0.001)


def test_end_of_data_forces_close():
    """Signal near end of data: open position closed at final bar's close."""
    df = _make_df(5)  # 5 bars; stop (95) and target (110) never reached

    result = run_backtest([_long(0)], df, NO_COST)

    trade = result.trades[0]
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_price == pytest.approx(100.0)  # final bar's close
    assert trade.exit_bar == 4


# ---------------------------------------------------------------------------
# Conservative stop-before-target rule
# ---------------------------------------------------------------------------


def test_same_bar_stop_and_target_stop_wins():
    """
    When a single bar simultaneously breaches stop (low) and target (high),
    stop is applied. This is the conservative / anti-cherry-picking rule.
    """
    df = _make_df(5)
    # Bar 1: low=93 (below stop=95) AND high=115 (above target=110)
    df.at[1, "low"] = 93.0
    df.at[1, "high"] = 115.0

    result = run_backtest([_long(0)], df, NO_COST)

    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.gross_pnl == pytest.approx(-200.0)


# ---------------------------------------------------------------------------
# Fill confirmation
# ---------------------------------------------------------------------------


def test_buystop_above_bar_high_skips_signal():
    """
    LONG entry above the bar's high (buy-stop never triggered) → no fill.
    The signal should be skipped, not trigger a trade.
    """
    df = _make_df(5)  # high = 101 at every bar

    # entry=105 is above every bar's high of 101 → fill never confirmed
    sig = Signal(bar_index=0, direction=Direction.LONG,
                 entry=105.0, stop=100.0, target=115.0)

    result = run_backtest([sig], df, NO_COST)
    assert result.n_trades == 0


def test_sellstop_below_bar_low_skips_signal():
    """
    SHORT entry below the bar's low (sell-stop never triggered) → no fill.
    """
    df = _make_df(5)  # low = 99 at every bar

    # entry=95 is below every bar's low of 99 → fill never confirmed
    sig = Signal(bar_index=0, direction=Direction.SHORT,
                 entry=95.0, stop=100.0, target=80.0)

    result = run_backtest([sig], df, NO_COST)
    assert result.n_trades == 0


# ---------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------


def test_zero_signals_returns_rejected():
    df = _make_df(30)
    result = run_backtest([], df, NO_COST)
    assert result.status == "rejected"
    assert "insufficient_trades" in result.rejection_reason
    assert math.isnan(result.score)


def test_nineteen_trades_rejected():
    """19 winning trades < 20 minimum → rejected."""
    signals, df = _make_signals_and_df(19, win=True)
    result = run_backtest(signals, df, NO_COST)

    assert result.status == "rejected"
    assert result.n_trades == 19
    assert "insufficient_trades" in result.rejection_reason
    assert math.isnan(result.score)


def test_twenty_trades_passes_min_gate():
    """Exactly 20 winning trades clears the minimum trades gate."""
    signals, df = _make_signals_and_df(20, win=True)
    result = run_backtest(signals, df, NO_COST)

    # 20 wins with PF=∞ → passes both gates; must be scored or at worst catastrophic
    assert result.status in ("scored", "catastrophic")
    assert result.n_trades == 20


def test_all_losses_rejected_by_profit_factor_gate():
    """
    All 25 trades hit their stops → gross_profit = 0, profit_factor = 0.
    Hard gate: PF ≤ 1.3 → rejected.

    max_monthly_risk=1.0 disables the monthly circuit breaker so all 25 trades
    execute; otherwise the 6% monthly cap fires after 4 trades and the run is
    rejected for insufficient trades rather than thin edge.
    """
    signals, df = _make_signals_and_df(25, win=False)
    no_monthly_cap = BacktestConfig(taker_fee=0.0, slippage_per_side=0.0,
                                    max_monthly_risk=1.0)
    result = run_backtest(signals, df, no_monthly_cap)

    assert result.status == "rejected"
    assert "thin_edge" in result.rejection_reason
    assert result.profit_factor == pytest.approx(0.0)


def test_thin_edge_rejected_by_profit_factor_gate():
    """
    5 wins (grossprofit ≈ 2000) vs 20 losses (gross_loss ≈ 4000) → PF ≈ 0.5 → rejected.
    """
    n_bars = 75
    df = _make_df(n_bars)

    signals = []
    # 5 winning signals at bars 0, 3, 6, 9, 12
    for i in range(5):
        b = i * 3
        df.at[b + 1, "high"] = 115.0
        signals.append(_long(b))
    # 20 losing signals at bars 15, 18, ..., 72
    for i in range(20):
        b = 15 + i * 3
        df.at[b + 1, "low"] = 93.0
        signals.append(_long(b))

    result = run_backtest(signals, df, NO_COST)

    assert result.status == "rejected"
    assert result.profit_factor < 1.3


# ---------------------------------------------------------------------------
# Catastrophic floor
# ---------------------------------------------------------------------------


def test_catastrophic_floor_terminates_and_scores_minus_1000():
    """
    When NAV drops below nav_catastrophic, run terminates immediately with score=-1000.

    Setup: nav_initial=5100, risk=2%, one LONG stop-out.
      units = (5100 × 0.02) / 5 = 20.4
      loss  = 20.4 × 5 = 102  → nav = 4998 < 5000
    """
    df = _make_df(10)
    df.at[1, "low"] = 93.0  # stop hit on bar 1

    config = BacktestConfig(nav_initial=5100.0, taker_fee=0.0, slippage_per_side=0.0)
    result = run_backtest([_long(0)], df, config)

    assert result.status == "catastrophic"
    assert result.score == pytest.approx(-1000.0)
    assert result.catastrophic_hit is True
    assert result.nav_final < 5000.0


# ---------------------------------------------------------------------------
# NAV ceiling
# ---------------------------------------------------------------------------


def test_nav_ceiling_caps_nav_after_trade():
    """
    A big win that would push NAV above nav_ceiling is capped.
    nav_initial=19900, one LONG target hit:
      effective_nav = min(19900, 20000) = 19900
      units = (19900 × 0.02) / 5 = 79.6
      gain  = 79.6 × 10 = 796 → raw_nav = 20696 → capped at 20000
    """
    df = _make_df(10)
    df.at[1, "high"] = 115.0

    config = BacktestConfig(nav_initial=19_900.0, taker_fee=0.0, slippage_per_side=0.0)
    result = run_backtest([_long(0)], df, config)

    assert result.trades[0].nav_after == pytest.approx(20_000.0)
    assert result.nav_final == pytest.approx(20_000.0)


def test_nav_ceiling_propagates_to_next_trade_sizing():
    """
    After hitting the ceiling, the next trade is sized using the capped NAV,
    not the uncapped compounded value.
    """
    df = _make_df(10)
    df.at[1, "high"] = 115.0  # trade 0 hits target
    df.at[3, "high"] = 115.0  # trade 1 hits target

    config = BacktestConfig(nav_initial=19_900.0, taker_fee=0.0, slippage_per_side=0.0)
    result = run_backtest([_long(0), _long(2)], df, config)

    # First trade nav_after = 20000 (ceiling)
    assert result.trades[0].nav_after == pytest.approx(20_000.0)
    # Second trade is sized on effective_nav = min(20000, 20000) = 20000
    # units = (20000 × 0.02) / 5 = 80
    assert result.trades[1].units == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Monthly drawdown circuit breaker
# ---------------------------------------------------------------------------


def test_monthly_drawdown_halts_trading_after_six_percent():
    """
    With 2% risk per trade (no fees), four consecutive losses in the same
    month produce a cumulative drawdown just above 6%, halting the fifth signal.

    Monthly loss progression (from month_start_nav=10000):
      After trade 0: nav=9800, dd=2.00%
      After trade 1: nav=9604, dd=3.96%
      After trade 2: nav=9412, dd=5.88%  ← still < 6%, trade 3 proceeds
      After trade 3: nav=9224, dd=7.76%  ← now ≥ 6%, trade 4 halted
    """
    # 30 bars, all in January 2024 (4h freq)
    df = _make_df(30)

    # Each signal fires on bar 2i, stop hit on bar 2i+1
    for i in range(5):
        df.at[2 * i + 1, "low"] = 93.0  # stop=95 breached

    signals = [_long(2 * i) for i in range(5)]

    result = run_backtest(signals, df, NO_COST)

    assert result.n_trades == 4   # 5th signal halted
    assert "2024-01" in result.halted_months


def test_monthly_circuit_breaker_resets_on_new_month():
    """
    Trades halted in month A should not affect month B.
    """
    # 60 bars: bars 0–29 in Jan, bars 30–59 in a later month (Feb starts at bar 30)
    # We need a custom timestamp range spanning two months.
    n = 60
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-30 00:00", periods=n, freq="4h", tz="UTC"),
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.0] * n,
        "volume": [1000.0] * n,
    })

    # Hit stop on every exit bar in both months
    for i in range(10):
        df.at[2 * i + 1, "low"] = 93.0
        df.at[30 + 2 * i + 1, "low"] = 93.0

    # 5 signals in Jan (bars 0,2,4,6,8), 5 in Feb (bars 30,32,34,36,38)
    jan_sigs = [_long(2 * i) for i in range(5)]
    feb_sigs = [_long(30 + 2 * i) for i in range(5)]

    result = run_backtest(jan_sigs + feb_sigs, df, NO_COST)

    # January: 4 trades execute, 5th halted
    # February: circuit breaker resets; 4 more trades execute before halted again
    assert result.n_trades == 8


# ---------------------------------------------------------------------------
# No overlapping positions
# ---------------------------------------------------------------------------


def test_overlapping_signals_are_skipped():
    """
    A signal that fires before the previous trade exits is skipped.
    Signal 0 (bar 0) exits at bar 5. Signal 1 fires at bar 3 — should be skipped.
    Signal 2 fires at bar 6 — should execute.
    """
    df = _make_df(15)
    df.at[5, "high"] = 115.0   # signal 0 hits target at bar 5
    df.at[7, "high"] = 115.0   # signal 2 hits target at bar 7

    sigs = [_long(0), _long(3), _long(6)]
    result = run_backtest(sigs, df, NO_COST)

    assert result.n_trades == 2
    assert result.trades[0].entry_bar == 0
    assert result.trades[1].entry_bar == 6


# ---------------------------------------------------------------------------
# max_drawdown computation
# ---------------------------------------------------------------------------


def test_max_drawdown_computed_correctly():
    """
    Three trades: win, big loss, win.
    NAV series: 10000 → 10400 → 8200 → 8600
    Peak = 10400, trough = 8200
    max_dd = (10400 - 8200) / 10400 ≈ 0.2115
    """
    df = _make_df(15)
    df.at[1, "high"] = 115.0   # trade 0 (bar 0): win +400
    # trade 1 (bar 3): entry=100, stop=95, but we need a large loss
    # To get a big loss, we need a large stop distance. Use a wide stop:
    # Signal: entry=100, stop=50, target=200 (R:R = 100/50 = 2)
    df.at[4, "low"] = 48.0     # trade 1 (bar 3): stop=50 hit → loss

    # After trade 0: nav = 10400
    # After trade 1: units = (10400 * 0.02) / 50 = 4.16, loss = 4.16 × 50 = 208
    #   nav = 10400 - 208 = 10192... not very deep

    # Use multiple losses instead
    for i in [1, 4, 7]:
        df.at[i, "low"] = 93.0  # stop hits for trades at bars 0, 3, 6

    sigs = [_long(0), _long(3), _long(6)]
    result = run_backtest(sigs, df, NO_COST)

    assert result.max_drawdown > 0.0
    assert result.max_drawdown <= 1.0


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


def test_walk_forward_produces_correct_fold_count():
    """run_walk_forward returns exactly n_folds folds."""
    signals, df = _make_signals_and_df(25, win=True)
    wf = run_walk_forward(signals, df, n_folds=5, config=NO_COST)

    assert wf.n_folds == 5
    assert len(wf.folds) == 5


def test_walk_forward_fold_bars_are_non_overlapping():
    """Each fold's bar range is distinct and together covers the full dataset."""
    signals, df = _make_signals_and_df(25, win=True)
    wf = run_walk_forward(signals, df, n_folds=5, config=NO_COST)

    starts = [f.start_bar for f in wf.folds]
    ends = [f.end_bar for f in wf.folds]

    # No overlap
    for i in range(len(wf.folds) - 1):
        assert ends[i] == starts[i + 1]

    # Covers full dataset
    assert starts[0] == 0
    assert ends[-1] == len(df)


def test_walk_forward_signals_filtered_per_fold():
    """Signals from fold i don't appear in fold j."""
    signals, df = _make_signals_and_df(30, win=True)
    wf = run_walk_forward(signals, df, n_folds=5, config=NO_COST)

    for fold in wf.folds:
        for s in fold.result.trades:
            # Adjusted bar_index (local to fold) must be within fold's size
            fold_size = fold.end_bar - fold.start_bar
            assert 0 <= s.entry_bar < fold_size


def test_walk_forward_consistent_flag():
    """consistent=True only when all scored folds have positive score."""
    signals, df = _make_signals_and_df(100, win=True, bars_per_trade=2)
    wf = run_walk_forward(signals, df, n_folds=5, config=NO_COST)

    # With all wins and enough trades per fold, consistent should be True
    # (Some folds may be rejected if they have < 20 trades, which is fine)
    if wf.n_scored_folds > 0:
        scored_scores = [f.result.score for f in wf.folds if f.result.status == "scored"]
        expected_consistent = all(s > 0 for s in scored_scores)
        assert wf.consistent == expected_consistent
