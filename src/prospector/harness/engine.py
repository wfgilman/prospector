"""
Backtest Harness — NAV Simulation Engine

Accepts pre-generated Signal objects from a strategy template and a matching
OHLCV DataFrame, then simulates execution with realistic constraints:

  - Iron Triangle position sizing: risk_per_trade % of current NAV per trade
  - Conservative exit logic: stop checked before target on same bar (no cherry-picking)
  - Transaction costs: taker fee + slippage on both legs
  - NAV ceiling: prevents unrealistic compounding above nav_ceiling
  - Catastrophic floor: terminates with score=-1000 if NAV falls below nav_catastrophic
  - Monthly drawdown circuit breaker: halts trading once monthly loss >= max_monthly_risk
  - Hard gates: rejects runs with < 20 trades or profit_factor <= 1.3

The harness is intentionally separate from template logic. Templates produce
signals; the harness simulates what happens when you act on them.

Entry fill confirmation:
  LONG signals: fill if bar[bar_index].high >= signal.entry (handles buy-stops)
  SHORT signals: fill if bar[bar_index].low <= signal.entry (handles sell-stops)
  For false_breakout signals where entry = bar close, this is always true.
  For triple_screen buy-stop signals, this filters fills the price never reached.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from prospector.templates.base import MIN_REWARD_RISK, Direction, Signal, validate_ohlcv

# ---------------------------------------------------------------------------
# Default execution parameters (not tunable by the LLM)
# ---------------------------------------------------------------------------

NAV_INITIAL: float = 10_000.0
NAV_CEILING: float = 20_000.0
NAV_CATASTROPHIC: float = 5_000.0
RISK_PER_TRADE: float = 0.02        # 2% of current NAV per trade
MAX_MONTHLY_RISK: float = 0.06      # 6% monthly drawdown cap
TAKER_FEE: float = 0.00035          # 0.035% Hyperliquid taker fee
SLIPPAGE_PER_SIDE: float = 0.0005   # 0.05% per side (conservative estimate)


@dataclass(frozen=True)
class BacktestConfig:
    """Execution parameters for the NAV simulation. Override in tests as needed."""

    nav_initial: float = NAV_INITIAL
    nav_ceiling: float = NAV_CEILING
    nav_catastrophic: float = NAV_CATASTROPHIC
    risk_per_trade: float = RISK_PER_TRADE
    max_monthly_risk: float = MAX_MONTHLY_RISK
    taker_fee: float = TAKER_FEE
    slippage_per_side: float = SLIPPAGE_PER_SIDE


DEFAULT_CONFIG = BacktestConfig()

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    """Outcome of a single executed signal."""

    signal: Signal           # Original signal that triggered the trade
    entry_bar: int           # Row index in df where fill was confirmed
    exit_bar: int            # Row index in df where position was closed
    exit_reason: str         # "target" | "stop" | "end_of_data"
    entry_price: float       # Signal's intended entry price
    exit_price: float        # Actual exit price (stop/target/close)
    units: float             # Position size in base asset units
    gross_pnl: float         # P&L before transaction costs
    transaction_cost: float  # Total round-trip cost (entry + exit legs)
    net_pnl: float           # gross_pnl - transaction_cost
    nav_before: float        # Effective NAV used for sizing (capped at nav_ceiling)
    nav_after: float         # NAV after trade settles (capped at nav_ceiling)
    hold_bars: int           # exit_bar - entry_bar


@dataclass
class BacktestResult:
    """Full output of a backtest run."""

    # Run outcome
    status: str                     # "scored" | "rejected" | "catastrophic"
    rejection_reason: str | None    # None for "scored" status
    score: float                    # Primary score, or nan (rejected) or -1000 (catastrophic)

    # Core metrics
    n_trades: int
    pct_return: float               # (final_nav - initial_nav) / initial_nav
    max_drawdown: float             # (peak - trough) / peak across NAV series

    # Diagnostic metrics (logged to ledger, visible in sliding window)
    profit_factor: float            # gross_profit / gross_loss (inf if no losses)
    win_rate: float
    sharpe_ratio: float             # Per-trade Sharpe, annualized by bar duration
    avg_trade_pnl: float
    avg_hold_bars: float
    total_return: float             # final_nav - initial_nav (dollars)
    monthly_returns: dict = field(default_factory=dict)    # "YYYY-MM" → net P&L
    longest_drawdown_bars: int = 0  # Bars from peak to deepest drawdown point

    # Trade log
    trades: list = field(default_factory=list)

    # NAV trajectory bookmarks
    nav_final: float = 0.0
    nav_peak: float = 0.0

    # Circuit breaker info
    catastrophic_hit: bool = False
    halted_months: list = field(default_factory=list)  # Months where 6% cap fired


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_score(pct_return: float, max_drawdown: float, n_trades: int) -> float:
    """
    Primary scoring formula.

    score = pct_return × 200 − dd_penalty − sample_penalty

    dd_penalty  = 0 if max_drawdown ≤ 0.20
                = ((max_drawdown − 0.20) / 0.10)² × 200  otherwise (quadratic)
    sample_penalty = 0 if n_trades ≥ 20
                   = (20 − n_trades) × 10  otherwise

    The quadratic drawdown penalty encodes that deep drawdowns are
    disproportionately costly (a 40% drawdown requires a 67% recovery).
    """
    dd_penalty = 0.0
    if max_drawdown > 0.20:
        dd_penalty = ((max_drawdown - 0.20) / 0.10) ** 2 * 200.0

    sample_penalty = 0.0
    if n_trades < 20:
        sample_penalty = float(20 - n_trades) * 10.0

    return pct_return * 200.0 - dd_penalty - sample_penalty


def run_backtest(
    signals: list[Signal],
    df: pd.DataFrame,
    config: BacktestConfig = DEFAULT_CONFIG,
) -> BacktestResult:
    """
    Simulate execution of a list of signals against OHLCV data.

    Args:
        signals: Signal objects from a strategy template. May be in any order;
                 sorted ascending by bar_index before processing.
        df:      OHLCV DataFrame used to generate the signals. Bar indices in
                 Signal objects are positional row indices into this DataFrame.
        config:  Execution parameters. Use BacktestConfig() with field overrides
                 in tests to set nav_initial, zero out fees, etc.

    Returns:
        BacktestResult with status, score, and full trade log.

    Notes:
        - At most one open position at a time (no overlapping fills).
        - Exits are checked from bar_index+1 onward; entry bar is never the exit bar.
        - Stop checked before target on every bar (conservative / anti-cherry-picking).
        - An open position at end of data is closed at the final bar's close.
    """
    validate_ohlcv(df)

    sorted_sigs = sorted(signals, key=lambda s: s.bar_index)

    nav = config.nav_initial
    nav_peak = nav
    trades: list[TradeRecord] = []
    last_exit_bar: int = -1
    halted_months: list[str] = []

    # Monthly circuit breaker state
    current_month: str | None = None
    month_start_nav: float = nav
    month_halted: bool = False

    def _month_key(bar_idx: int) -> str:
        return df["timestamp"].iloc[bar_idx].strftime("%Y-%m")

    for sig in sorted_sigs:
        if sig.bar_index >= len(df):
            continue  # Signal out of DataFrame bounds — skip

        # Defense in depth: R:R gate (templates should enforce this, but verify)
        if sig.reward_risk_ratio < MIN_REWARD_RISK:
            continue

        # Monthly circuit breaker: detect month transitions and check cap
        month = _month_key(sig.bar_index)
        if month != current_month:
            if month_halted and current_month is not None:
                halted_months.append(current_month)
            current_month = month
            month_start_nav = nav
            month_halted = False

        if month_halted:
            continue

        if month_start_nav > 0:
            monthly_loss_pct = (month_start_nav - nav) / month_start_nav
            if monthly_loss_pct >= config.max_monthly_risk:
                month_halted = True
                continue

        # No overlapping positions: skip if bar fires during an open trade
        if sig.bar_index <= last_exit_bar:
            continue

        # Entry fill confirmation: check that bar reached the entry price
        entry_bar_high = float(df["high"].iloc[sig.bar_index])
        entry_bar_low = float(df["low"].iloc[sig.bar_index])
        if sig.direction == Direction.LONG:
            if entry_bar_high < sig.entry:
                continue  # Buy-stop never triggered
        else:
            if entry_bar_low > sig.entry:
                continue  # Sell-stop never triggered

        # Position sizing: risk exactly risk_per_trade % of current NAV
        price_risk = abs(sig.entry - sig.stop)
        if price_risk < 1e-8:
            continue  # Stop essentially at entry — degenerate signal

        effective_nav = min(nav, config.nav_ceiling)
        risk_dollars = effective_nav * config.risk_per_trade
        units = risk_dollars / price_risk
        position_value = units * sig.entry

        if position_value > effective_nav:
            # Should be rare with 2% risk, but guard against it
            continue

        entry_cost = position_value * (config.taker_fee + config.slippage_per_side)

        # Scan forward for exit: stop or target, whichever comes first
        exit_bar = len(df) - 1
        exit_price = float(df["close"].iloc[-1])
        exit_reason = "end_of_data"

        for j in range(sig.bar_index + 1, len(df)):
            bar_high = float(df["high"].iloc[j])
            bar_low = float(df["low"].iloc[j])

            if sig.direction == Direction.LONG:
                # Stop checked before target: conservative (no cherry-picking)
                if bar_low <= sig.stop:
                    exit_bar, exit_price, exit_reason = j, sig.stop, "stop"
                    break
                if bar_high >= sig.target:
                    exit_bar, exit_price, exit_reason = j, sig.target, "target"
                    break
            else:  # SHORT
                if bar_high >= sig.stop:
                    exit_bar, exit_price, exit_reason = j, sig.stop, "stop"
                    break
                if bar_low <= sig.target:
                    exit_bar, exit_price, exit_reason = j, sig.target, "target"
                    break

        # Compute P&L
        if sig.direction == Direction.LONG:
            gross_pnl = (exit_price - sig.entry) * units
        else:
            gross_pnl = (sig.entry - exit_price) * units

        exit_value = units * exit_price
        exit_cost = exit_value * (config.taker_fee + config.slippage_per_side)
        total_cost = entry_cost + exit_cost
        net_pnl = gross_pnl - total_cost

        nav_before = effective_nav
        nav = min(nav + net_pnl, config.nav_ceiling)
        nav = max(nav, 0.0)

        if nav > nav_peak:
            nav_peak = nav

        last_exit_bar = exit_bar

        # Update monthly cap: check if this loss pushed us over the cap
        if month_start_nav > 0:
            monthly_loss_pct = (month_start_nav - nav) / month_start_nav
            if monthly_loss_pct >= config.max_monthly_risk:
                month_halted = True

        trades.append(TradeRecord(
            signal=sig,
            entry_bar=sig.bar_index,
            exit_bar=exit_bar,
            exit_reason=exit_reason,
            entry_price=sig.entry,
            exit_price=exit_price,
            units=units,
            gross_pnl=gross_pnl,
            transaction_cost=total_cost,
            net_pnl=net_pnl,
            nav_before=nav_before,
            nav_after=nav,
            hold_bars=exit_bar - sig.bar_index,
        ))

        # Catastrophic floor: terminate immediately
        if nav < config.nav_catastrophic:
            if month_halted and current_month is not None and current_month not in halted_months:
                halted_months.append(current_month)
            return _build_result(
                trades, nav, nav_peak, config, df, halted_months, catastrophic=True
            )

    # Finalize halted months tracking
    if month_halted and current_month is not None and current_month not in halted_months:
        halted_months.append(current_month)

    return _build_result(trades, nav, nav_peak, config, df, halted_months, catastrophic=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_result(
    trades: list[TradeRecord],
    nav: float,
    nav_peak: float,
    config: BacktestConfig,
    df: pd.DataFrame,
    halted_months: list[str],
    *,
    catastrophic: bool,
) -> BacktestResult:
    """Assemble a BacktestResult from the completed trade list."""
    n_trades = len(trades)

    # Derived metrics
    gross_profit = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
    gross_loss = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    pct_return = (nav - config.nav_initial) / config.nav_initial
    total_return = nav - config.nav_initial

    max_dd, longest_dd_bars = _compute_max_drawdown(trades, config.nav_initial)
    wins = sum(1 for t in trades if t.net_pnl > 0)
    win_rate = wins / n_trades if n_trades > 0 else 0.0
    sharpe = _compute_sharpe(trades, df)
    avg_pnl = sum(t.net_pnl for t in trades) / n_trades if n_trades > 0 else 0.0
    avg_hold = sum(t.hold_bars for t in trades) / n_trades if n_trades > 0 else 0.0
    monthly_returns = _compute_monthly_returns(trades, df)

    if catastrophic:
        return BacktestResult(
            status="catastrophic",
            rejection_reason="nav_below_catastrophic_floor",
            score=-1000.0,
            n_trades=n_trades,
            pct_return=pct_return,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            win_rate=win_rate,
            sharpe_ratio=sharpe,
            avg_trade_pnl=avg_pnl,
            avg_hold_bars=avg_hold,
            total_return=total_return,
            monthly_returns=monthly_returns,
            longest_drawdown_bars=longest_dd_bars,
            trades=trades,
            nav_final=nav,
            nav_peak=nav_peak,
            catastrophic_hit=True,
            halted_months=halted_months,
        )

    # Hard gate: minimum trades
    if n_trades < 20:
        return BacktestResult(
            status="rejected",
            rejection_reason=f"insufficient_trades: {n_trades} < 20",
            score=float("nan"),
            n_trades=n_trades,
            pct_return=pct_return,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            win_rate=win_rate,
            sharpe_ratio=sharpe,
            avg_trade_pnl=avg_pnl,
            avg_hold_bars=avg_hold,
            total_return=total_return,
            monthly_returns=monthly_returns,
            longest_drawdown_bars=longest_dd_bars,
            trades=trades,
            nav_final=nav,
            nav_peak=nav_peak,
            halted_months=halted_months,
        )

    # Hard gate: profit factor
    if profit_factor <= 1.3:
        return BacktestResult(
            status="rejected",
            rejection_reason=f"thin_edge: profit_factor={profit_factor:.2f} <= 1.3",
            score=float("nan"),
            n_trades=n_trades,
            pct_return=pct_return,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            win_rate=win_rate,
            sharpe_ratio=sharpe,
            avg_trade_pnl=avg_pnl,
            avg_hold_bars=avg_hold,
            total_return=total_return,
            monthly_returns=monthly_returns,
            longest_drawdown_bars=longest_dd_bars,
            trades=trades,
            nav_final=nav,
            nav_peak=nav_peak,
            halted_months=halted_months,
        )

    score = compute_score(pct_return, max_dd, n_trades)
    return BacktestResult(
        status="scored",
        rejection_reason=None,
        score=score,
        n_trades=n_trades,
        pct_return=pct_return,
        max_drawdown=max_dd,
        profit_factor=profit_factor,
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        avg_trade_pnl=avg_pnl,
        avg_hold_bars=avg_hold,
        total_return=total_return,
        monthly_returns=monthly_returns,
        longest_drawdown_bars=longest_dd_bars,
        trades=trades,
        nav_final=nav,
        nav_peak=nav_peak,
        halted_months=halted_months,
    )


def _compute_max_drawdown(
    trades: list[TradeRecord], nav_initial: float
) -> tuple[float, int]:
    """
    Return (max_drawdown, longest_drawdown_bars).

    Drawdown is measured from the NAV series: [nav_initial] + [t.nav_after for each trade].
    longest_drawdown_bars is the bar distance from the peak trade to the deepest trough.
    """
    if not trades:
        return 0.0, 0

    # Build (exit_bar, nav) points: start with initial point at bar 0
    nav_points = [(0, nav_initial)] + [(t.exit_bar, t.nav_after) for t in trades]

    peak_nav = nav_initial
    dd_start_bar = 0
    max_dd = 0.0
    longest_dd = 0

    for bar_idx, nav_val in nav_points:
        if nav_val >= peak_nav:
            peak_nav = nav_val
            dd_start_bar = bar_idx
        else:
            dd = (peak_nav - nav_val) / peak_nav
            if dd > max_dd:
                max_dd = dd
            duration = bar_idx - dd_start_bar
            if duration > longest_dd:
                longest_dd = duration

    return max_dd, longest_dd


def _compute_sharpe(trades: list[TradeRecord], df: pd.DataFrame) -> float:
    """
    Per-trade Sharpe ratio, annualized using the DataFrame's bar duration.

    Uses trade returns as net_pnl / nav_before. Annualization factor is
    sqrt(estimated_trades_per_year), derived from bars per year divided by
    the average hold duration. If std of returns is zero (all trades returned
    the same amount), returns 0.0.
    """
    if len(trades) < 2:
        return 0.0

    returns = [t.net_pnl / t.nav_before for t in trades if t.nav_before > 0]
    if len(returns) < 2:
        return 0.0

    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(var_r)

    if std_r < 1e-10:
        return 0.0

    # Estimate bars per year from median bar duration
    try:
        bar_sec = float(df["timestamp"].diff().median().total_seconds())
        bars_per_year = (365 * 24 * 3600) / bar_sec if bar_sec > 0 else 2190
    except Exception:
        bars_per_year = 2190  # Fallback: 4h bars (6 × 365)

    avg_hold = sum(t.hold_bars for t in trades) / len(trades)
    avg_hold = max(avg_hold, 1.0)
    trades_per_year = bars_per_year / avg_hold
    annualization = math.sqrt(trades_per_year)

    return mean_r / std_r * annualization


def _compute_monthly_returns(trades: list[TradeRecord], df: pd.DataFrame) -> dict:
    """
    Return dict mapping "YYYY-MM" → net P&L for that month.
    Keyed by the exit bar's timestamp (when P&L was realized).
    """
    monthly: dict[str, float] = {}
    for t in trades:
        if t.exit_bar < len(df):
            month = df["timestamp"].iloc[t.exit_bar].strftime("%Y-%m")
            monthly[month] = monthly.get(month, 0.0) + t.net_pnl
    return monthly
