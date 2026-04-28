"""Stop / target exit detection for open elder triple-screen positions.

Each tick we walk the open positions, slice the OHLCV from the entry
bar forward, and check whether stop or target was hit. The harness's
exit logic (`engine.py`) inspires the rules here:

    LONG  : stop fires when bar.low <= stop_price
            target fires when bar.high >= target_price
            stop is checked BEFORE target on the same bar
            (anti-cherry-picking; matches run_backtest semantics)

    SHORT : stop fires when bar.high >= stop_price
            target fires when bar.low <= target_price

Funding cost over the hold window is integrated from the coin's
hourly funding-rate history at close time, using the existing
`prospector.harness.funding` module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from prospector.harness.engine import TradeRecord
from prospector.harness.funding import funding_cost as compute_funding_cost
from prospector.harness.funding import load_funding
from prospector.strategies.elder_triple_screen.portfolio import (
    ClosedPosition,
    OpenPosition,
    PaperPortfolio,
)
from prospector.strategies.elder_triple_screen.signal import load_ohlcv_pair
from prospector.templates.base import Direction, Signal


@dataclass
class ExitDecision:
    position: OpenPosition
    exit_bar_index: int
    exit_price: float
    exit_reason: str   # "target" | "stop"


def _check_exit(pos: OpenPosition, df: pd.DataFrame) -> ExitDecision | None:
    """Walk df from entry_bar+1 forward; first stop or target hit wins."""
    for i in range(pos.entry_bar_index + 1, len(df)):
        bar = df.iloc[i]
        if pos.direction == Direction.LONG:
            if bar["low"] <= pos.stop_price:
                return ExitDecision(pos, i, pos.stop_price, "stop")
            if bar["high"] >= pos.target_price:
                return ExitDecision(pos, i, pos.target_price, "target")
        else:
            if bar["high"] >= pos.stop_price:
                return ExitDecision(pos, i, pos.stop_price, "stop")
            if bar["low"] <= pos.target_price:
                return ExitDecision(pos, i, pos.target_price, "target")
    return None


def _funding_cost_for(
    pos: OpenPosition, decision: ExitDecision, df: pd.DataFrame,
) -> float:
    """Build a synthetic TradeRecord and run the existing funding integrator."""
    coin_root = pos.coin.replace("-PERP", "").replace("_PERP", "")
    try:
        funding_df = load_funding(coin_root)
    except FileNotFoundError:
        return 0.0
    if pos.direction == Direction.LONG:
        sig = Signal(
            bar_index=pos.entry_bar_index, direction=Direction.LONG,
            entry=pos.entry_price, stop=pos.stop_price, target=pos.target_price,
        )
    else:
        sig = Signal(
            bar_index=pos.entry_bar_index, direction=Direction.SHORT,
            entry=pos.entry_price, stop=pos.stop_price, target=pos.target_price,
        )
    trade = TradeRecord(
        signal=sig,
        entry_bar=pos.entry_bar_index,
        exit_bar=decision.exit_bar_index,
        exit_reason=decision.exit_reason,
        entry_price=pos.entry_price,
        exit_price=decision.exit_price,
        units=pos.units,
        gross_pnl=0.0,            # not used by funding_cost
        transaction_cost=0.0,
        net_pnl=0.0,
        nav_before=0.0,
        nav_after=0.0,
        hold_bars=decision.exit_bar_index - pos.entry_bar_index,
    )
    return compute_funding_cost(trade, df, funding_df)


def sweep(
    portfolio: PaperPortfolio,
    log: list[ClosedPosition] | None = None,
) -> list[ClosedPosition]:
    """Check every open position for stop/target hits; close the ones that hit."""
    closed: list[ClosedPosition] = []
    for pos in portfolio.open_positions():
        try:
            _, df_short = load_ohlcv_pair(pos.coin)
        except FileNotFoundError:
            continue
        decision = _check_exit(pos, df_short)
        if decision is None:
            # Still open — record a mid snapshot so we can compute CLV later.
            if not df_short.empty:
                latest = df_short.iloc[-1]
                portfolio.record_mid_snapshot(
                    pos.coin,
                    float(latest["close"]),
                    pd.Timestamp(latest["timestamp"]).to_pydatetime().replace(
                        tzinfo=timezone.utc
                    ) if not isinstance(latest["timestamp"], datetime)
                    else latest["timestamp"],
                )
            continue
        funding = _funding_cost_for(pos, decision, df_short)
        exit_time = pd.Timestamp(df_short["timestamp"].iloc[decision.exit_bar_index])
        if exit_time.tzinfo is None:
            exit_time = exit_time.tz_localize("UTC")
        cp = portfolio.close_position(
            position_id=pos.id,
            exit_price=decision.exit_price,
            exit_bar_index=decision.exit_bar_index,
            exit_time=exit_time.to_pydatetime(),
            exit_reason=decision.exit_reason,
            funding_cost=funding,
        )
        closed.append(cp)
        if log is not None:
            log.append(cp)
    return closed
