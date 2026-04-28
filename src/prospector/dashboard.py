"""Streamlit dashboard helpers.

Split out from ``scripts/dashboard.py`` so the Streamlit script stays thin
and the render logic stays unit-testable. The module has three layers:

1. *Loaders* — pure functions that read a strategy's portfolio DB or log
   directory and return dataclasses / dataframes. No Streamlit imports, so
   these can be exercised from tests and notebooks.
2. *Theme* — CSS + Altair config that commits the dashboard to a
   "quant-terminal" aesthetic (dark charcoal, serif display, mono numbers).
3. *Renderers* — schema-dispatched Streamlit views. One renderer per
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
    r"(?:shadow=(?P<shadow>\d+) )?"
    r"candidates=(?P<candidates>\d+) "
    r"resolved=(?P<resolved>\d+) voided=(?P<voided>\d+)\s*$"
)
_LOG_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s")

# Elder triple-screen daemon emits one of:
#   ``log.info("tick: %s", stats)`` (foreground loop)
#   ``log.info("once: %s", stats)`` (launchd one-shot path)
# where ``stats`` is a dict with closed/opened/skipped_open/open_after_tick/nav.
# Extract the integer counters; nav is reflected in the per-card stat.
_ELDER_TICK_RE = re.compile(
    r"(?:tick|once):\s*\{[^}]*'closed':\s*(?P<closed>\d+)[^}]*"
    r"'opened':\s*(?P<opened>\d+)[^}]*"
    r"'skipped_open':\s*(?P<skipped>\d+)[^}]*"
    r"'open_after_tick':\s*(?P<open_after>\d+)"
)


@dataclass(frozen=True)
class TickSummary:
    timestamp: datetime | None
    entered: int
    rejected: int
    shadow: int
    candidates: int
    resolved: int
    voided: int


def load_tick_history(log_dir: Path, limit: int = 50) -> list[TickSummary]:
    """Parse the last `limit` tick summaries across today's + yesterday's logs."""
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
                shadow_raw = tick_match["shadow"]
                ticks.append(
                    TickSummary(
                        timestamp=prev_ts,
                        entered=int(tick_match["entered"]),
                        rejected=int(tick_match["rejected"]),
                        shadow=int(shadow_raw) if shadow_raw is not None else 0,
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
    """Return positions as a DataFrame, optionally filtered by status."""
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
    df["expected_close_time"] = pd.to_datetime(
        df["expected_close_time"], utc=True
    )
    return df


def load_category_breakdown(db_path: Path) -> pd.DataFrame:
    """Per-category aggregates across open + closed positions.

    Columns:
        category, open_count, locked_risk, upside, avg_edge_pp,
        closed_count, wins, losses, realized_pnl, voided_count.

    Upside = sum of `reward_potential` on open positions (what the book
    gains if every open position wins). Realized P&L is only for *closed*
    positions (voids contribute 0). Empty result => empty DataFrame.
    """
    if not db_path.exists():
        return pd.DataFrame()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        df = pd.read_sql_query(
            """
            SELECT
                category,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
                COALESCE(
                    SUM(CASE WHEN status = 'open' THEN risk_budget END), 0
                ) AS locked_risk,
                COALESCE(
                    SUM(CASE WHEN status = 'open' THEN reward_potential END), 0
                ) AS upside,
                AVG(CASE WHEN status = 'open' THEN edge_pp END) AS avg_edge_pp,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_count,
                SUM(
                    CASE WHEN status = 'closed' AND realized_pnl > 0 THEN 1 ELSE 0 END
                ) AS wins,
                SUM(
                    CASE WHEN status = 'closed' AND realized_pnl <= 0 THEN 1 ELSE 0 END
                ) AS losses,
                COALESCE(
                    SUM(CASE WHEN status = 'closed' THEN realized_pnl END), 0
                ) AS realized_pnl,
                SUM(CASE WHEN status = 'voided' THEN 1 ELSE 0 END) AS voided_count
            FROM positions
            GROUP BY category
            ORDER BY locked_risk DESC
            """,
            conn,
        )
    return df


def build_pnl_series(db_path: Path) -> pd.DataFrame:
    """Cumulative realized P&L trajectory, anchored at 0 before the first close."""
    if not db_path.exists():
        return pd.DataFrame(columns=["time", "pnl"])
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        closed = pd.read_sql_query(
            "SELECT close_time, realized_pnl FROM positions "
            "WHERE status = 'closed' AND close_time IS NOT NULL "
            "ORDER BY close_time",
            conn,
        )
    if closed.empty:
        return pd.DataFrame(
            [{"time": datetime.now(timezone.utc), "pnl": 0.0}]
        )
    closed["close_time"] = pd.to_datetime(closed["close_time"], utc=True)
    closed["pnl"] = closed["realized_pnl"].cumsum()
    return closed.rename(columns={"close_time": "time"})[["time", "pnl"]]


# -- elder triple-screen (crypto_perp schema) loaders ----------------------
#
# The kalshi book stores `realized_pnl` and `close_time`; the elder book
# stores `net_pnl` (gross − fees − funding) and `exit_time`. Loaders below
# adapt the same dataclasses to the elder schema so the dashboard can
# present both books side-by-side.


def _load_summary_elder(db_path: Path) -> PortfolioSummary | None:
    if not db_path.exists():
        return None
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        initial = conn.execute(
            "SELECT value FROM meta WHERE key = 'initial_nav'"
        ).fetchone()
        initial_nav = float(initial["value"]) if initial else 0.0
        realized = conn.execute(
            "SELECT COALESCE(SUM(net_pnl), 0) AS r "
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


def _pnl_series_elder(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame(columns=["time", "pnl"])
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        closed = pd.read_sql_query(
            "SELECT exit_time, net_pnl FROM positions "
            "WHERE status = 'closed' AND exit_time IS NOT NULL "
            "ORDER BY exit_time",
            conn,
        )
    if closed.empty:
        return pd.DataFrame(
            [{"time": datetime.now(timezone.utc), "pnl": 0.0}]
        )
    closed["exit_time"] = pd.to_datetime(closed["exit_time"], utc=True)
    closed["pnl"] = closed["net_pnl"].cumsum()
    return closed.rename(columns={"exit_time": "time"})[["time", "pnl"]]


def _load_positions_elder(
    db_path: Path, status: str | None = None
) -> pd.DataFrame:
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
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    return df


def summary_for(entry: StrategyEntry) -> PortfolioSummary | None:
    """Schema-dispatched summary loader. Used by render_comparison."""
    if entry.schema == "kalshi_binary":
        return load_portfolio_summary(entry.portfolio_db)
    if entry.schema == "crypto_perp":
        return _load_summary_elder(entry.portfolio_db)
    raise ValueError(f"unknown schema: {entry.schema}")


def pnl_series_for(entry: StrategyEntry) -> pd.DataFrame:
    """Schema-dispatched cumulative-P&L series. Used by render_comparison."""
    if entry.schema == "kalshi_binary":
        return build_pnl_series(entry.portfolio_db)
    if entry.schema == "crypto_perp":
        return _pnl_series_elder(entry.portfolio_db)
    raise ValueError(f"unknown schema: {entry.schema}")


def load_elder_tick_history(
    log_dir: Path, limit: int = 50
) -> list[TickSummary]:
    """Parse the elder daemon's `tick: {...}` lines.

    Reuses :class:`TickSummary` for shape compatibility with the kalshi
    renderer: ``entered`` ← opened, ``rejected`` ← skipped_open,
    ``candidates`` ← open_after_tick, ``resolved`` ← closed. Voided/shadow
    are zero (the elder book has no voids and no shadow ledger today).
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
            tick_match = _ELDER_TICK_RE.search(line)
            if tick_match:
                ticks.append(
                    TickSummary(
                        timestamp=prev_ts,
                        entered=int(tick_match["opened"]),
                        rejected=int(tick_match["skipped"]),
                        shadow=0,
                        candidates=int(tick_match["open_after"]),
                        resolved=int(tick_match["closed"]),
                        voided=0,
                    )
                )
    return ticks[-limit:]


# -- theme ------------------------------------------------------------------

# Single accent palette referenced from both CSS and Altair. Keep these in
# one place so retheming is a three-line change.
_PALETTE = {
    "bg": "#0C0E13",
    "surface": "#151821",
    "surface_raised": "#1C2030",
    "border": "#2A2F40",
    "text": "#E8E6DB",
    "text_dim": "#8A8FA3",
    "accent": "#7CE495",   # phosphor green — positives, live state
    "warn": "#F5B841",      # amber — cap proximity, attention
    "loss": "#F87171",      # dusty red — losses, rejections
}

_THEME_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400&family=Geist:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {{
    --qt-bg: {_PALETTE["bg"]};
    --qt-surface: {_PALETTE["surface"]};
    --qt-surface-raised: {_PALETTE["surface_raised"]};
    --qt-border: {_PALETTE["border"]};
    --qt-text: {_PALETTE["text"]};
    --qt-text-dim: {_PALETTE["text_dim"]};
    --qt-accent: {_PALETTE["accent"]};
    --qt-warn: {_PALETTE["warn"]};
    --qt-loss: {_PALETTE["loss"]};
}}

html, body, [class*="st-"], .stApp, .stMarkdown, button, input, textarea {{
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--qt-text);
}}

.stApp {{
    background:
        radial-gradient(circle at 10% -10%, rgba(124, 228, 149, 0.05), transparent 50%),
        radial-gradient(circle at 90% 110%, rgba(124, 228, 149, 0.03), transparent 50%),
        var(--qt-bg);
}}

/* Section headers — editorial serif with optical sizing */
.qt-eyebrow {{
    font-family: 'Geist', sans-serif;
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--qt-text-dim);
    margin: 0;
}}
/* Numbers — tabular mono, everywhere */
.qt-mono, .qt-num {{
    font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1, "zero" 1;
}}

/* Unified strategy stat card */
.qt-stat-card {{
    background: linear-gradient(180deg, var(--qt-surface) 0%, var(--qt-bg) 100%);
    border: 1px solid var(--qt-border);
    border-radius: 4px;
    padding: 0.9rem 1.25rem;
    position: relative;
    overflow: hidden;
}}
.qt-stat-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(
        90deg, transparent, var(--qt-accent) 50%, transparent
    );
    opacity: 0.5;
}}
.qt-stat-card-head {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 0.6rem;
}}
.qt-stat-card-name {{
    font-family: 'Fraunces', serif;
    font-variation-settings: 'opsz' 48, 'wght' 500;
    font-size: 1.05rem;
    color: var(--qt-text);
    letter-spacing: -0.01em;
}}
.qt-stat-card-tick {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.7rem;
    color: var(--qt-text-dim);
}}
.qt-stat-card-row {{
    display: flex;
    align-items: flex-start;
    gap: 1.75rem;
    flex-wrap: wrap;
}}
.qt-stat-card-item {{
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
}}
.qt-stat-card-item.primary {{
    padding-right: 1.75rem;
    border-right: 1px solid var(--qt-border);
}}
.qt-stat-card-nav {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 1.7rem;
    font-weight: 500;
    line-height: 1.05;
    letter-spacing: -0.02em;
    color: var(--qt-text);
}}
.qt-stat-card-delta {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.8rem;
}}
.qt-stat-card-delta.up {{ color: var(--qt-accent); }}
.qt-stat-card-delta.down {{ color: var(--qt-loss); }}
.qt-stat-card-delta.flat {{ color: var(--qt-text-dim); }}

/* KPI tiles */
.qt-kpi {{
    background: var(--qt-surface);
    border: 1px solid var(--qt-border);
    border-radius: 4px;
    padding: 0.9rem 1.1rem;
    height: 100%;
}}
.qt-kpi-label {{
    font-size: 0.65rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--qt-text-dim);
    margin-bottom: 0.4rem;
}}
.qt-kpi-value {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 1.4rem;
    font-weight: 500;
    color: var(--qt-text);
    line-height: 1.1;
}}
.qt-kpi-sub {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.75rem;
    color: var(--qt-text-dim);
    margin-top: 0.25rem;
}}

/* Category panels */
.qt-cat {{
    border: 1px solid var(--qt-border);
    border-radius: 4px;
    background: var(--qt-surface);
    margin-bottom: 1.25rem;
    overflow: hidden;
}}
.qt-cat-head {{
    padding: 1rem 1.25rem;
    display: flex;
    align-items: baseline;
    gap: 1.5rem;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--qt-border);
    background: var(--qt-surface-raised);
}}
.qt-cat-name {{
    font-family: 'Fraunces', serif;
    font-variation-settings: 'opsz' 48, 'wght' 600;
    font-size: 1.3rem;
    color: var(--qt-text);
    letter-spacing: -0.01em;
}}
.qt-cat-stat {{
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}}
.qt-cat-stat-label {{
    font-size: 0.6rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--qt-text-dim);
}}
.qt-cat-stat-value {{
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 0.95rem;
    color: var(--qt-text);
}}
.qt-cat-stat-value.up {{ color: var(--qt-accent); }}
.qt-cat-stat-value.down {{ color: var(--qt-loss); }}
.qt-cat-stat-value.flat {{ color: var(--qt-text-dim); }}

/* Scrubbed dataframe edges to match card borders */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--qt-border);
    border-radius: 4px;
    overflow: hidden;
}}
[data-testid="stDataFrame"] * {{
    font-family: 'JetBrains Mono', monospace !important;
    font-variant-numeric: tabular-nums;
    font-size: 0.82rem;
}}

/* Tighter default spacing; this is a monitoring tool, not a marketing page */
.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1400px;
}}
hr {{
    border-color: var(--qt-border);
    margin: 2rem 0;
}}

/* Streamlit metric — fall back where we still use it */
[data-testid="stMetric"] {{
    background: var(--qt-surface);
    border: 1px solid var(--qt-border);
    border-radius: 4px;
    padding: 0.75rem 1rem;
}}
[data-testid="stMetricLabel"] p {{
    font-size: 0.65rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--qt-text-dim);
}}
[data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-variant-numeric: tabular-nums;
    color: var(--qt-text);
}}
</style>
"""


def _altair_theme() -> dict:
    """Return an Altair theme dict matching the page palette."""
    return {
        "config": {
            "background": _PALETTE["surface"],
            "view": {"stroke": "transparent"},
            "axis": {
                "domainColor": _PALETTE["border"],
                "gridColor": _PALETTE["border"],
                "gridOpacity": 0.4,
                "tickColor": _PALETTE["border"],
                "labelColor": _PALETTE["text_dim"],
                "labelFont": "JetBrains Mono",
                "labelFontSize": 10,
                "titleColor": _PALETTE["text_dim"],
                "titleFont": "Geist",
                "titleFontWeight": 500,
                "titleFontSize": 10,
            },
            "legend": {
                "labelColor": _PALETTE["text_dim"],
                "titleColor": _PALETTE["text_dim"],
                "labelFont": "Geist",
                "titleFont": "Geist",
            },
            "title": {
                "color": _PALETTE["text"],
                "font": "Fraunces",
                "fontSize": 14,
                "fontWeight": 500,
                "anchor": "start",
            },
            "range": {
                "category": [
                    _PALETTE["accent"],
                    _PALETTE["warn"],
                    _PALETTE["loss"],
                    "#8B9AD6",
                    "#C77DFF",
                ],
            },
        }
    }


def inject_theme() -> None:
    """Write the CSS block once per Streamlit rerun.

    Streamlit reruns the whole script top-to-bottom on every interaction,
    so calling this from each render is fine — browsers dedupe the
    Google Fonts request.

    Public because the entry script (``scripts/dashboard.py``) has to
    call it once per rerun before any markup is emitted; the renderer
    helpers below assume the stylesheet is already on the page.
    """
    import streamlit as st

    st.markdown(_THEME_CSS, unsafe_allow_html=True)


# -- renderers --------------------------------------------------------------


def render_strategy(entry: StrategyEntry) -> None:
    """Dispatch to the renderer matching the strategy's position schema."""
    if entry.schema == "kalshi_binary":
        _render_kalshi_binary(entry)
    elif entry.schema == "crypto_perp":
        _render_crypto_perp(entry)
    else:
        import streamlit as st

        st.warning(
            f"No renderer for schema {entry.schema!r}. "
            "Add one to prospector.dashboard."
        )


def render_comparison(entries: list[StrategyEntry]) -> None:
    """Side-by-side comparison view across enabled strategies.

    Renders one column per strategy with the same compact stat card used
    on individual tabs, then an overlaid cumulative-P&L chart. Strategies
    whose portfolio DB doesn't exist yet are surfaced as "no data" tiles
    so the eyeballed comparison stays stable across cold starts.

    Caller is responsible for only invoking this when there are 2+ entries.
    """
    import altair as alt
    import streamlit as st

    alt.themes.register("quant_terminal", _altair_theme)
    alt.themes.enable("quant_terminal")

    summaries = [(e, summary_for(e)) for e in entries]

    cols = st.columns(len(summaries))
    for col, (entry, summary) in zip(cols, summaries):
        with col:
            if summary is None:
                _render_empty_stat_card(entry)
            else:
                _render_stat_card(entry, summary)

    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="qt-eyebrow">P&amp;L trajectory · overlaid</div>',
        unsafe_allow_html=True,
    )

    overlays = []
    for entry, _ in summaries:
        df = pnl_series_for(entry)
        if df.empty:
            continue
        df = df.copy()
        df["strategy"] = entry.display_name
        overlays.append(df)

    if not overlays:
        st.caption("No realized P&L on either book yet.")
    else:
        plot_df = pd.concat(overlays, ignore_index=True)
        # If any strategy only has the placeholder (single now-row at 0),
        # the chart still renders but as a flat dot — fine.
        line = (
            alt.Chart(plot_df)
            .mark_line(interpolate="monotone", strokeWidth=1.75)
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("pnl:Q", title="Cumulative realized P&L ($)"),
                color=alt.Color("strategy:N", title=None,
                                legend=alt.Legend(orient="top")),
            )
        )
        zero_rule = (
            alt.Chart(pd.DataFrame({"y": [0]}))
            .mark_rule(color=_PALETTE["border"], strokeDash=[2, 3])
            .encode(y="y:Q")
        )
        st.altair_chart(
            (line + zero_rule).properties(height=220),
            width="stretch",
        )

    # Compact KPI delta table — easier to read at-a-glance than reading
    # both cards. Skips when only one strategy has data.
    populated = [(e, s) for e, s in summaries if s is not None]
    if len(populated) >= 2:
        st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown(
            '<div class="qt-eyebrow">Side-by-side KPIs</div>',
            unsafe_allow_html=True,
        )
        kpi_df = pd.DataFrame(
            [
                {
                    "strategy": e.display_name,
                    "NAV": f"${s.nav:,.2f}",
                    "P&L": f"${s.realized_pnl:+,.2f}",
                    "ROI %": (
                        f"{(s.nav - s.initial_nav) / s.initial_nav * 100:+.2f}%"
                        if s.initial_nav else "—"
                    ),
                    "Open": s.open_positions,
                    "Locked": f"${s.locked_risk:,.2f}",
                    "Today": s.trades_today,
                }
                for e, s in populated
            ]
        )
        st.dataframe(kpi_df, width="stretch", hide_index=True)


def _render_empty_stat_card(entry: StrategyEntry) -> None:
    """Placeholder card for a strategy whose DB doesn't exist yet.

    Lets the comparison columns stay aligned even when the insurance book
    hasn't ticked once. The first paper-trade tick creates the DB.
    """
    import streamlit as st

    st.markdown(
        f"""
        <div class="qt-stat-card">
            <div class="qt-stat-card-head">
                <div class="qt-stat-card-name">{entry.display_name}</div>
                <div class="qt-stat-card-tick">awaiting first tick</div>
            </div>
            <div class="qt-stat-card-row">
                <div class="qt-stat-card-item primary">
                    <div class="qt-kpi-label">NAV</div>
                    <div class="qt-stat-card-nav">—</div>
                    <div class="qt-stat-card-delta flat">no data yet</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">DB path</div>
                    <div class="qt-kpi-value qt-mono"
                         style="font-size:0.7rem; word-break:break-all;">
                        {entry.portfolio_db}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_kalshi_binary(entry: StrategyEntry) -> None:
    import altair as alt
    import streamlit as st

    alt.themes.register("quant_terminal", _altair_theme)
    alt.themes.enable("quant_terminal")

    summary = load_portfolio_summary(entry.portfolio_db)
    if summary is None:
        st.info(f"Portfolio DB not found at {entry.portfolio_db}.")
        return

    _render_stat_card(entry, summary)
    _render_pnl(entry.portfolio_db)
    _render_category_sections(entry.portfolio_db)
    _render_positions_tabs(entry.portfolio_db, entry.log_dir)


def _render_crypto_perp(entry: StrategyEntry) -> None:
    """Renderer for the elder triple-screen perp book.

    Elder positions don't have categories or expected-close times, so the
    by-category section is dropped and the positions tabs use the elder
    column set (coin, direction, exit_reason, gross/fees/funding/net P&L).
    """
    import altair as alt
    import streamlit as st

    alt.themes.register("quant_terminal", _altair_theme)
    alt.themes.enable("quant_terminal")

    summary = _load_summary_elder(entry.portfolio_db)
    if summary is None:
        st.info(
            f"Portfolio DB not found at {entry.portfolio_db}. "
            "First tick fires at the next 4h boundary."
        )
        return

    _render_stat_card_elder(entry, summary)
    _render_pnl_elder(entry.portfolio_db)
    _render_positions_tabs_elder(entry.portfolio_db, entry.log_dir)


def _render_stat_card_elder(
    entry: StrategyEntry, summary: PortfolioSummary
) -> None:
    """Stat card matching the kalshi layout but reading the elder log."""
    import streamlit as st

    delta = summary.nav - summary.initial_nav
    roi = delta / summary.initial_nav * 100 if summary.initial_nav else 0.0
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "◆")

    realized_cls = (
        "up" if summary.realized_pnl > 0
        else ("down" if summary.realized_pnl < 0 else "flat")
    )
    locked_pct = (
        summary.locked_risk / summary.nav * 100 if summary.nav else 0.0
    )

    ticks = load_elder_tick_history(entry.log_dir, limit=1)
    last = ticks[-1] if ticks else None
    last_tick_str = (
        last.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        if last and last.timestamp
        else "—"
    )

    st.markdown(
        f"""
        <div class="qt-stat-card">
            <div class="qt-stat-card-head">
                <div class="qt-stat-card-name">{entry.display_name}</div>
                <div class="qt-stat-card-tick">Last tick · {last_tick_str}</div>
            </div>
            <div class="qt-stat-card-row">
                <div class="qt-stat-card-item primary">
                    <div class="qt-kpi-label">NAV</div>
                    <div class="qt-stat-card-nav">${summary.nav:,.2f}</div>
                    <div class="qt-stat-card-delta {direction}">
                        {arrow} {delta:+,.2f} · {roi:+.2f}%
                    </div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Seed</div>
                    <div class="qt-kpi-value">${summary.initial_nav:,.0f}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Net P&amp;L</div>
                    <div class="qt-kpi-value {realized_cls}">${summary.realized_pnl:+,.2f}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Locked Risk</div>
                    <div class="qt-kpi-value">${summary.locked_risk:,.2f}</div>
                    <div class="qt-kpi-sub">{locked_pct:.2f}% of NAV</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Open</div>
                    <div class="qt-kpi-value">{summary.open_positions}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Trades Today</div>
                    <div class="qt-kpi-value">{summary.trades_today}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_pnl_elder(db_path: Path) -> None:
    import altair as alt
    import streamlit as st

    pnl_df = _pnl_series_elder(db_path)
    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="qt-eyebrow">Net P&amp;L trajectory</div>',
        unsafe_allow_html=True,
    )
    if len(pnl_df) >= 2:
        plot_df = pnl_df.copy()
        plot_df["pos"] = plot_df["pnl"].clip(lower=0)
        plot_df["neg"] = plot_df["pnl"].clip(upper=0)
        area_pos = (
            alt.Chart(plot_df)
            .mark_area(
                opacity=0.3,
                color=_PALETTE["accent"],
                interpolate="monotone",
                line={"color": _PALETTE["accent"], "strokeWidth": 1.75},
            )
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("pos:Q", title="Net P&L ($)"),
            )
        )
        area_neg = (
            alt.Chart(plot_df)
            .mark_area(
                opacity=0.3,
                color=_PALETTE["loss"],
                interpolate="monotone",
                line={"color": _PALETTE["loss"], "strokeWidth": 1.75},
            )
            .encode(x="time:T", y=alt.Y("neg:Q"))
        )
        zero_rule = (
            alt.Chart(pd.DataFrame({"y": [0]}))
            .mark_rule(color=_PALETTE["border"], strokeDash=[2, 3])
            .encode(y="y:Q")
        )
        st.altair_chart(
            (area_pos + area_neg + zero_rule).properties(height=180),
            width="stretch",
        )
    else:
        st.caption("Trajectory will render after the first stop/target hit.")


def _render_positions_tabs_elder(db_path: Path, log_dir: Path) -> None:
    import streamlit as st

    st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
    tab_open, tab_closed, tab_ticks = st.tabs(
        ["Open positions", "Closed positions", "Recent ticks"]
    )
    with tab_open:
        _render_open_positions_elder(db_path)
    with tab_closed:
        _render_closed_positions_elder(db_path)
    with tab_ticks:
        _render_tick_stream_elder(log_dir)


def _render_open_positions_elder(db_path: Path) -> None:
    import streamlit as st

    open_df = _load_positions_elder(db_path, status="open")
    if open_df.empty:
        st.caption("No open positions.")
        return

    display_cols = [
        "coin",
        "direction",
        "units",
        "entry_price",
        "stop_price",
        "target_price",
        "risk_budget",
        "entry_time",
    ]
    display_df = open_df[display_cols].copy()
    display_df["entry_time"] = display_df["entry_time"].dt.strftime(
        "%m-%d %H:%M"
    )
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "units": st.column_config.NumberColumn(format="%.4f"),
            "entry_price": st.column_config.NumberColumn(format="%.4f"),
            "stop_price": st.column_config.NumberColumn(format="%.4f"),
            "target_price": st.column_config.NumberColumn(format="%.4f"),
            "risk_budget": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


def _render_closed_positions_elder(db_path: Path) -> None:
    import streamlit as st

    closed_df = _load_positions_elder(db_path, status="closed")
    if closed_df.empty:
        st.caption("No closed positions yet.")
        return

    total_pnl = float(closed_df["net_pnl"].sum())
    total_fees = float(closed_df["fees_paid"].sum())
    total_funding = float(closed_df["funding_cost"].sum())
    wins = int((closed_df["net_pnl"] > 0).sum())
    losses = int((closed_df["net_pnl"] <= 0).sum())
    pnl_cls = "up" if total_pnl > 0 else ("down" if total_pnl < 0 else "flat")
    st.markdown(
        f"""
        <div style="display:flex; gap:2rem; margin-bottom:0.75rem; flex-wrap:wrap;">
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Closed</div>
                <div class="qt-cat-stat-value">{len(closed_df)}</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Record</div>
                <div class="qt-cat-stat-value">{wins}W / {losses}L</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Net P&amp;L</div>
                <div class="qt-cat-stat-value {pnl_cls}">${total_pnl:+,.2f}</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Fees</div>
                <div class="qt-cat-stat-value">${total_fees:,.2f}</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Funding</div>
                <div class="qt-cat-stat-value">${total_funding:+,.2f}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    display_cols = [
        "coin",
        "direction",
        "units",
        "entry_price",
        "exit_price",
        "exit_reason",
        "entry_time",
        "exit_time",
        "gross_pnl",
        "fees_paid",
        "funding_cost",
        "net_pnl",
    ]
    display_df = closed_df[display_cols].copy()
    display_df = display_df.sort_values("exit_time", ascending=False)
    display_df["entry_time"] = display_df["entry_time"].dt.strftime("%m-%d %H:%M")
    display_df["exit_time"] = display_df["exit_time"].dt.strftime("%m-%d %H:%M")
    st.dataframe(
        display_df.style.format(
            {
                "units": "{:.4f}",
                "entry_price": "{:.4f}",
                "exit_price": "{:.4f}",
                "gross_pnl": "${:+,.2f}",
                "fees_paid": "${:,.2f}",
                "funding_cost": "${:+,.2f}",
                "net_pnl": "${:+,.2f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def _render_tick_stream_elder(log_dir: Path) -> None:
    import streamlit as st

    ticks = load_elder_tick_history(log_dir, limit=20)
    if not ticks:
        st.caption(f"No tick log entries under {log_dir}.")
        return
    tick_df = pd.DataFrame(
        [
            {
                "time": (
                    t.timestamp.strftime("%m-%d %H:%M UTC")
                    if t.timestamp
                    else "—"
                ),
                "closed": t.resolved,
                "opened": t.entered,
                "skipped": t.rejected,
                "open_after": t.candidates,
            }
            for t in ticks[::-1]
        ]
    )
    st.dataframe(tick_df, width="stretch", hide_index=True)


def _render_stat_card(entry: StrategyEntry, summary: PortfolioSummary) -> None:
    """Single compact card collapsing hero + KPIs + freshness into one row."""
    import streamlit as st

    delta = summary.nav - summary.initial_nav
    roi = delta / summary.initial_nav * 100 if summary.initial_nav else 0.0
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "◆")

    realized_cls = (
        "up" if summary.realized_pnl > 0
        else ("down" if summary.realized_pnl < 0 else "flat")
    )
    locked_pct = (
        summary.locked_risk / summary.nav * 100 if summary.nav else 0.0
    )

    ticks = load_tick_history(entry.log_dir, limit=1)
    last = ticks[-1] if ticks else None
    last_tick_str = (
        last.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        if last and last.timestamp
        else "—"
    )

    st.markdown(
        f"""
        <div class="qt-stat-card">
            <div class="qt-stat-card-head">
                <div class="qt-stat-card-name">{entry.display_name}</div>
                <div class="qt-stat-card-tick">Last tick · {last_tick_str}</div>
            </div>
            <div class="qt-stat-card-row">
                <div class="qt-stat-card-item primary">
                    <div class="qt-kpi-label">NAV</div>
                    <div class="qt-stat-card-nav">${summary.nav:,.2f}</div>
                    <div class="qt-stat-card-delta {direction}">
                        {arrow} {delta:+,.2f} · {roi:+.2f}%
                    </div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Seed</div>
                    <div class="qt-kpi-value">${summary.initial_nav:,.0f}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Realized P&amp;L</div>
                    <div class="qt-kpi-value {realized_cls}">${summary.realized_pnl:+,.2f}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Locked Risk</div>
                    <div class="qt-kpi-value">${summary.locked_risk:,.2f}</div>
                    <div class="qt-kpi-sub">{locked_pct:.2f}% of NAV</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Open</div>
                    <div class="qt-kpi-value">{summary.open_positions}</div>
                </div>
                <div class="qt-stat-card-item">
                    <div class="qt-kpi-label">Trades Today</div>
                    <div class="qt-kpi-value">{summary.trades_today}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_pnl(db_path: Path) -> None:
    import altair as alt
    import streamlit as st

    pnl_df = build_pnl_series(db_path)
    st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="qt-eyebrow">P&amp;L trajectory</div>',
        unsafe_allow_html=True,
    )
    if len(pnl_df) >= 2:
        # Clip into two series so each filled area stays on its own side
        # of y=0. Altair's `mark_area(line=...)` draws an outline along the
        # top edge, which gives us per-sign line coloring for free.
        plot_df = pnl_df.copy()
        plot_df["pos"] = plot_df["pnl"].clip(lower=0)
        plot_df["neg"] = plot_df["pnl"].clip(upper=0)
        area_pos = (
            alt.Chart(plot_df)
            .mark_area(
                opacity=0.3,
                color=_PALETTE["accent"],
                interpolate="monotone",
                line={"color": _PALETTE["accent"], "strokeWidth": 1.75},
            )
            .encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("pos:Q", title="Realized P&L ($)"),
            )
        )
        area_neg = (
            alt.Chart(plot_df)
            .mark_area(
                opacity=0.3,
                color=_PALETTE["loss"],
                interpolate="monotone",
                line={"color": _PALETTE["loss"], "strokeWidth": 1.75},
            )
            .encode(x="time:T", y=alt.Y("neg:Q"))
        )
        zero_rule = (
            alt.Chart(pd.DataFrame({"y": [0]}))
            .mark_rule(color=_PALETTE["border"], strokeDash=[2, 3])
            .encode(y="y:Q")
        )
        st.altair_chart(
            (area_pos + area_neg + zero_rule).properties(height=180),
            width="stretch",
        )
    else:
        st.caption("Trajectory will render after the first resolution.")


def _render_category_sections(db_path: Path) -> None:
    import streamlit as st

    st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="qt-eyebrow">By category</div>',
        unsafe_allow_html=True,
    )

    breakdown = load_category_breakdown(db_path)
    if breakdown.empty:
        st.caption("No category activity.")
        return

    for _, row in breakdown.iterrows():
        if row["open_count"] == 0 and row["closed_count"] == 0:
            continue
        _render_category_head(row)


def _render_category_head(row: pd.Series) -> None:
    import streamlit as st

    cat = row["category"]
    pnl = float(row["realized_pnl"])
    pnl_cls = "up" if pnl > 0 else ("down" if pnl < 0 else "flat")
    wins, losses = int(row["wins"]), int(row["losses"])
    record = f"{wins}W / {losses}L" if (wins + losses) > 0 else "—"
    avg_edge = row["avg_edge_pp"]
    avg_edge_str = f"+{avg_edge:.2f}pp" if pd.notna(avg_edge) else "—"

    st.markdown(
        f"""
        <div class="qt-cat">
            <div class="qt-cat-head">
                <div class="qt-cat-name">{cat.upper()}</div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Open</div>
                    <div class="qt-cat-stat-value">{int(row["open_count"])}</div>
                </div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Locked Risk</div>
                    <div class="qt-cat-stat-value">${row["locked_risk"]:,.2f}</div>
                </div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Upside</div>
                    <div class="qt-cat-stat-value up">${row["upside"]:,.2f}</div>
                </div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Avg Edge</div>
                    <div class="qt-cat-stat-value">{avg_edge_str}</div>
                </div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Resolved</div>
                    <div class="qt-cat-stat-value">{record}</div>
                </div>
                <div class="qt-cat-stat">
                    <div class="qt-cat-stat-label">Realized P&amp;L</div>
                    <div class="qt-cat-stat-value {pnl_cls}">${pnl:+,.2f}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _hours_to_expiry(
    expected_close: pd.Series, now: datetime
) -> pd.Series:
    """Return hours until ``expected_close`` as a float Series.

    Kept numeric (rather than pre-formatted) so ``st.dataframe`` can sort
    the column by duration instead of lexicographically by string. NaT
    inputs propagate to NaN so Streamlit renders them as blank and sorts
    them to the end.
    """
    expected = pd.to_datetime(expected_close, utc=True)
    delta = expected - pd.Timestamp(now)
    return delta.dt.total_seconds() / 3600.0


def _render_positions_tabs(db_path: Path, log_dir: Path) -> None:
    import streamlit as st

    st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
    tab_open, tab_closed, tab_ticks = st.tabs(
        ["Open positions", "Closed positions", "Recent ticks"]
    )
    with tab_open:
        _render_open_positions(db_path)
    with tab_closed:
        _render_closed_positions(db_path)
    with tab_ticks:
        _render_tick_stream(log_dir)


def _render_open_positions(db_path: Path) -> None:
    import streamlit as st

    open_df = load_positions(db_path, status="open")
    if open_df.empty:
        st.caption("No open positions.")
        return

    display_cols = [
        "ticker",
        "category",
        "side",
        "entry_price",
        "edge_pp",
        "risk_budget",
        "reward_potential",
        "contracts",
        "entry_time",
        "expected_close_time",
    ]
    display_df = open_df[display_cols].copy()
    display_df["entry_time"] = display_df["entry_time"].dt.strftime("%m-%d %H:%M")
    now = datetime.now(timezone.utc)
    # Keep expiry as a numeric column so Streamlit sorts by duration, not
    # by a preformatted string. NumberColumn's printf format appends the
    # unit suffix so the display still reads like "3.2 h".
    display_df["hours_to_expiry"] = _hours_to_expiry(
        display_df["expected_close_time"], now
    )
    display_df = display_df.drop(columns=["expected_close_time"])
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "entry_price": st.column_config.NumberColumn(format="%.3f"),
            "edge_pp": st.column_config.NumberColumn(format="%+.1f"),
            "risk_budget": st.column_config.NumberColumn(format="$%.2f"),
            "reward_potential": st.column_config.NumberColumn(format="$%.2f"),
            "hours_to_expiry": st.column_config.NumberColumn(
                "time to expiry", format="%.1f h"
            ),
        },
    )


def _render_closed_positions(db_path: Path) -> None:
    import streamlit as st

    closed_df = load_positions(db_path, status="closed")
    if closed_df.empty:
        st.caption("No closed positions yet.")
        return

    total_pnl = float(closed_df["realized_pnl"].sum())
    wins = int((closed_df["realized_pnl"] > 0).sum())
    losses = int((closed_df["realized_pnl"] <= 0).sum())
    pnl_cls = "up" if total_pnl > 0 else ("down" if total_pnl < 0 else "flat")
    st.markdown(
        f"""
        <div style="display:flex; gap:2rem; margin-bottom:0.75rem;">
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Closed</div>
                <div class="qt-cat-stat-value">{len(closed_df)}</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Record</div>
                <div class="qt-cat-stat-value">{wins}W / {losses}L</div>
            </div>
            <div class="qt-cat-stat">
                <div class="qt-cat-stat-label">Total Realized P&amp;L</div>
                <div class="qt-cat-stat-value {pnl_cls}">${total_pnl:+,.2f}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    display_cols = [
        "ticker",
        "category",
        "side",
        "entry_price",
        "close_price",
        "contracts",
        "entry_time",
        "close_time",
        "market_result",
        "realized_pnl",
    ]
    display_df = closed_df[display_cols].copy()
    display_df = display_df.sort_values("close_time", ascending=False)
    display_df["entry_time"] = display_df["entry_time"].dt.strftime("%m-%d %H:%M")
    display_df["close_time"] = display_df["close_time"].dt.strftime("%m-%d %H:%M")
    st.dataframe(
        display_df.style.format(
            {
                "entry_price": "{:.3f}",
                "close_price": "{:.3f}",
                "realized_pnl": "${:+,.2f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def _render_tick_stream(log_dir: Path) -> None:
    import streamlit as st

    ticks = load_tick_history(log_dir, limit=20)
    if not ticks:
        st.caption(f"No tick log entries under {log_dir}.")
        return
    tick_df = pd.DataFrame(
        [
            {
                "time": (
                    t.timestamp.strftime("%m-%d %H:%M UTC")
                    if t.timestamp
                    else "—"
                ),
                "candidates": t.candidates,
                "entered": t.entered,
                "rejected": t.rejected,
                "shadow": t.shadow,
                "resolved": t.resolved,
                "voided": t.voided,
            }
            for t in ticks[::-1]
        ]
    )
    st.dataframe(tick_df, width="stretch", hide_index=True)
