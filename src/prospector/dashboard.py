"""Streamlit dashboard helpers.

Split out from ``scripts/dashboard.py`` so the Streamlit script stays thin
and the render logic stays unit-testable. The module has two layers:

1. *Loaders* — pure functions that read a strategy's portfolio DB or log
   directory and return dataclasses / dataframes. No Streamlit imports, so
   these can be exercised from tests and notebooks.
2. *Renderers* — schema-dispatched Streamlit views. One renderer per
   position schema (``kalshi_binary`` today; add a new renderer when a new
   schema ships).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from prospector.manifest import StrategyEntry

# -- log parsing ------------------------------------------------------------

# run_once prints one of these per tick to stdout (captured by the launchd
# wrapper into the dated log file). Anchor to start-of-line so we don't pick
# up substrings of exception tracebacks.
_TICK_RE = re.compile(
    r"^entered=(?P<entered>\d+) rejected=(?P<rejected>\d+) "
    r"candidates=(?P<candidates>\d+) "
    r"resolved=(?P<resolved>\d+) voided=(?P<voided>\d+)\s*$"
)
# Preceding log line format: ``YYYY-MM-DD HH:MM:SS,mmm LEVEL logger msg``.
# We read it off the line *before* the tick summary so each tick gets its
# wall-clock timestamp without relying on file mtime.
_LOG_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s")


@dataclass(frozen=True)
class TickSummary:
    timestamp: datetime | None
    entered: int
    rejected: int
    candidates: int
    resolved: int
    voided: int


def load_tick_history(log_dir: Path, limit: int = 50) -> list[TickSummary]:
    """Parse the last `limit` tick summaries across today's + yesterday's logs.

    Logs rotate daily (UTC) via the launchd wrapper, so two files are
    usually enough to cover recent activity without unbounded scanning.
    """
    if not log_dir.exists():
        return []
    files = sorted(log_dir.glob("paper_trade-*.log"))[-2:]
    ticks: list[TickSummary] = []
    for path in files:
        prev_ts: datetime | None = None
        for line in path.read_text(errors="replace").splitlines():
            ts_match = _LOG_TS_RE.match(line)
            if ts_match:
                try:
                    prev_ts = datetime.fromisoformat(ts_match["ts"]).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    prev_ts = None
                continue
            tick_match = _TICK_RE.match(line)
            if tick_match:
                ticks.append(
                    TickSummary(
                        timestamp=prev_ts,
                        entered=int(tick_match["entered"]),
                        rejected=int(tick_match["rejected"]),
                        candidates=int(tick_match["candidates"]),
                        resolved=int(tick_match["resolved"]),
                        voided=int(tick_match["voided"]),
                    )
                )
    return ticks[-limit:]


# -- portfolio loaders ------------------------------------------------------


@dataclass(frozen=True)
class PortfolioSummary:
    nav: float
    cash: float
    locked_risk: float
    open_positions: int
    trades_today: int
    realized_pnl: float
    initial_nav: float


def load_portfolio_summary(db_path: Path) -> PortfolioSummary | None:
    """Return a point-in-time summary or ``None`` if the DB doesn't exist yet."""
    if not db_path.exists():
        return None
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        initial = conn.execute(
            "SELECT value FROM meta WHERE key = 'initial_nav'"
        ).fetchone()
        initial_nav = float(initial["value"]) if initial else 0.0
        realized = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS r "
            "FROM positions WHERE status = 'closed'"
        ).fetchone()["r"]
        locked = conn.execute(
            "SELECT COALESCE(SUM(risk_budget), 0) AS r "
            "FROM positions WHERE status = 'open'"
        ).fetchone()["r"]
        n_open = conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'open'"
        ).fetchone()["n"]
        today = datetime.now(timezone.utc).date().isoformat()
        trades_today = conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE DATE(entry_time) = ?",
            (today,),
        ).fetchone()["n"]
    nav = initial_nav + float(realized)
    return PortfolioSummary(
        nav=nav,
        cash=nav - float(locked),
        locked_risk=float(locked),
        open_positions=int(n_open),
        trades_today=int(trades_today),
        realized_pnl=float(realized),
        initial_nav=initial_nav,
    )


def load_positions(db_path: Path, status: str | None = None) -> pd.DataFrame:
    """Return positions as a DataFrame, optionally filtered by status.

    Empty DataFrame if the DB is missing — callers can render a placeholder
    without special-casing.
    """
    if not db_path.exists():
        return pd.DataFrame()
    query = "SELECT * FROM positions"
    params: tuple = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY entry_time DESC"
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        return df
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    return df


def build_nav_series(db_path: Path) -> pd.DataFrame:
    """NAV trajectory derived from resolved positions + initial NAV.

    We could read from `daily_snapshots`, but snapshots aren't yet populated
    by the runner. Using resolved positions gives a continuous curve the
    moment the first trade resolves.
    """
    if not db_path.exists():
        return pd.DataFrame(columns=["time", "nav"])
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        meta = conn.execute(
            "SELECT value FROM meta WHERE key = 'initial_nav'"
        ).fetchone()
        initial_nav = float(meta[0]) if meta else 0.0
        closed = pd.read_sql_query(
            "SELECT close_time, realized_pnl FROM positions "
            "WHERE status = 'closed' AND close_time IS NOT NULL "
            "ORDER BY close_time",
            conn,
        )
    if closed.empty:
        # Anchor the chart at initial NAV so it renders something on fresh books.
        return pd.DataFrame(
            [{"time": datetime.now(timezone.utc), "nav": initial_nav}]
        )
    closed["close_time"] = pd.to_datetime(closed["close_time"], utc=True)
    closed["nav"] = initial_nav + closed["realized_pnl"].cumsum()
    return closed.rename(columns={"close_time": "time"})[["time", "nav"]]


# -- renderers --------------------------------------------------------------


def render_strategy(entry: StrategyEntry) -> None:
    """Dispatch to the renderer matching the strategy's position schema."""
    if entry.schema == "kalshi_binary":
        _render_kalshi_binary(entry)
    else:
        import streamlit as st

        st.warning(
            f"No renderer for schema {entry.schema!r}. "
            "Add one to prospector.dashboard."
        )


def _render_kalshi_binary(entry: StrategyEntry) -> None:
    import altair as alt
    import streamlit as st

    st.subheader(entry.display_name)

    summary = load_portfolio_summary(entry.portfolio_db)
    if summary is None:
        st.info(f"Portfolio DB not found at {entry.portfolio_db}.")
        return

    roi = (summary.nav - summary.initial_nav) / summary.initial_nav * 100
    cols = st.columns(6)
    cols[0].metric("NAV", f"${summary.nav:,.2f}", f"{roi:+.2f}%")
    cols[1].metric("Realized P&L", f"${summary.realized_pnl:,.2f}")
    cols[2].metric("Locked risk", f"${summary.locked_risk:,.2f}")
    cols[3].metric("Cash", f"${summary.cash:,.2f}")
    cols[4].metric("Open positions", summary.open_positions)
    cols[5].metric("Trades today", summary.trades_today)

    nav_df = build_nav_series(entry.portfolio_db)
    if len(nav_df) >= 2:
        chart = (
            alt.Chart(nav_df)
            .mark_line()
            .encode(x="time:T", y=alt.Y("nav:Q", title="NAV ($)"))
            .properties(height=200)
        )
        st.altair_chart(chart, width="stretch")
    else:
        st.caption("NAV trajectory renders once the first trade resolves.")

    open_df = load_positions(entry.portfolio_db, status="open")
    if not open_df.empty:
        display_cols = [
            "ticker",
            "event_ticker",
            "category",
            "side",
            "entry_price",
            "edge_pp",
            "risk_budget",
            "reward_potential",
            "contracts",
            "entry_time",
        ]
        st.markdown("**Open positions**")
        st.dataframe(
            open_df[display_cols].style.format(
                {
                    "entry_price": "{:.3f}",
                    "edge_pp": "{:+.1f}",
                    "risk_budget": "${:.2f}",
                    "reward_potential": "${:.2f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

        conc_df = open_df.copy()
        conc_df["bin_low"] = (conc_df["entry_price"] * 100 // 5 * 5).astype(int)
        by_bin = (
            conc_df.groupby(["side", "bin_low"], as_index=False)["risk_budget"]
            .sum()
            .rename(columns={"risk_budget": "risk"})
        )
        bin_cap = summary.nav * 0.15
        conc_chart = (
            alt.Chart(by_bin)
            .mark_bar()
            .encode(
                x=alt.X("bin_low:O", title="5¢ bin (low)"),
                y=alt.Y("risk:Q", title="Locked risk ($)"),
                color="side:N",
                tooltip=["side", "bin_low", "risk"],
            )
            .properties(height=200, title=f"Bin concentration (cap ≈ ${bin_cap:,.0f})")
        )
        st.altair_chart(conc_chart, width="stretch")
    else:
        st.caption("No open positions.")

    st.markdown("**Recent ticks**")
    ticks = load_tick_history(entry.log_dir, limit=20)
    if ticks:
        tick_df = pd.DataFrame(
            [
                {
                    "time": t.timestamp,
                    "entered": t.entered,
                    "rejected": t.rejected,
                    "candidates": t.candidates,
                    "resolved": t.resolved,
                    "voided": t.voided,
                }
                for t in ticks[::-1]
            ]
        )
        st.dataframe(tick_df, width="stretch", hide_index=True)
    else:
        st.caption(f"No tick log entries found under {entry.log_dir}.")
