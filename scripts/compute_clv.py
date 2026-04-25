"""Closing-Line Value (CLV) instrumentation for the PM underwriting paper book.

Sports sharps use CLV — the signed gap between entry price and the market's
closing line — as a leading indicator of edge. The thesis: over enough bets,
realized P&L converges to what CLV predicts, but CLV stabilizes far sooner
because it's a price-based statistic (N ~ hundreds) rather than an outcome-
based one (N ~ thousands, with 9:1 payoff variance).

For a paper book that's 4 days old with ~80 trades at ~29% win rate, realized
P&L is essentially noise. CLV on the same 80 trades is already a meaningful
signal about whether the scanner is picking mispriced markets or not.

Definition (both sides normalize to "positive = we beat the line"):
    sell_yes entered at p: CLV_pp = (p - closing_line) * 100
    buy_yes  entered at p: CLV_pp = (closing_line - p) * 100

"closing line" = last trade yes_price in the window [close_time - LOOKBACK, close_time]
for resolved positions, or the last trade up to `as_of_time` for still-open ones.
If no trades in the window, fall back to the last trade on record for that ticker.
If still no trades, the position is skipped (no closing reference available).

Usage:
    python scripts/compute_clv.py                         # all statuses
    python scripts/compute_clv.py --status closed         # closed only
    python scripts/compute_clv.py --out clv.parquet       # save per-trade table

Outputs:
  - stdout: aggregate stats, by-side, by-price-bin, by-category, by-edge-pp
  - optional parquet dump for downstream analysis
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
TRADES_GLOB = REPO_ROOT / "data" / "kalshi" / "trades" / "date=*" / "part.parquet"
DEFAULT_PORTFOLIO_DB = (
    REPO_ROOT / "data" / "paper" / "pm_underwriting" / "portfolio.db"
)
# How far back of trade history to consider when looking for a closing line.
# Kalshi sports contracts trade actively for hours; 24h is conservative.
LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class Position:
    id: int
    ticker: str
    event_ticker: str
    category: str
    side: str
    entry_price: float
    edge_pp: float
    risk_budget: float
    status: str
    entry_time: datetime
    close_time: datetime | None
    realized_pnl: float | None


def load_positions(db_path: Path, status_filter: str | None) -> list[Position]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = """
        SELECT id, ticker, event_ticker, category, side, entry_price, edge_pp,
               risk_budget, status, entry_time, close_time, realized_pnl
        FROM positions
    """
    if status_filter:
        sql += " WHERE status = ?"
        rows = conn.execute(sql, (status_filter,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    conn.close()

    out: list[Position] = []
    for r in rows:
        out.append(
            Position(
                id=r["id"],
                ticker=r["ticker"],
                event_ticker=r["event_ticker"],
                category=r["category"],
                side=r["side"],
                entry_price=r["entry_price"],
                edge_pp=r["edge_pp"],
                risk_budget=r["risk_budget"],
                status=r["status"],
                entry_time=datetime.fromisoformat(r["entry_time"]),
                close_time=(
                    datetime.fromisoformat(r["close_time"]) if r["close_time"] else None
                ),
                realized_pnl=r["realized_pnl"],
            )
        )
    return out


def _closing_lines_from_snapshots(
    db_path: Path,
    positions: list[Position],
    as_of: datetime,
) -> dict[int, tuple[float, datetime, str] | None]:
    """Primary source: per-ticker snapshots written by the live monitor.

    Returns (yes_price, snapshot_time, "snapshot") tuples for any position
    whose ticker has at least one snapshot at or before window_end. yes_price
    is the bid/ask mid when both sides are populated, else last_price.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    out: dict[int, tuple[float, datetime, str] | None] = {p.id: None for p in positions}
    for p in positions:
        window_end = (p.close_time or as_of).isoformat()
        row = conn.execute(
            """SELECT yes_bid, yes_ask, last_price, snapshot_time
               FROM clv_snapshots
               WHERE ticker = ?
                 AND snapshot_time <= ?
               ORDER BY snapshot_time DESC
               LIMIT 1""",
            (p.ticker, window_end),
        ).fetchone()
        if row is None:
            continue
        price = _mid_from_row(row)
        if price is None:
            continue
        ts = datetime.fromisoformat(row["snapshot_time"])
        out[p.id] = (price, ts, "snapshot")
    conn.close()
    return out


def _mid_from_row(row: sqlite3.Row) -> float | None:
    bid, ask, last = row["yes_bid"], row["yes_ask"], row["last_price"]
    if bid is not None and ask is not None and 0 < bid < 1 and 0 < ask < 1 and ask >= bid:
        return (bid + ask) / 2.0
    if last is not None and 0 < last < 1:
        return last
    return None


def _closing_lines_from_trades(
    con: duckdb.DuckDBPyConnection,
    positions: list[Position],
    as_of: datetime,
) -> dict[int, tuple[float, datetime, str] | None]:
    """Fallback source: last trade in the unified Kalshi trade tree."""
    rows = [
        {
            "pos_id": p.id,
            "ticker": p.ticker,
            "window_end": (p.close_time or as_of),
        }
        for p in positions
    ]
    df = pd.DataFrame(rows)
    df["window_start"] = df["window_end"] - LOOKBACK
    con.register("pos_windows", df)
    con.execute(
        f"""
        CREATE OR REPLACE VIEW eligible_trades AS
        SELECT
            t.ticker,
            t.created_time,
            t.yes_price,
            w.pos_id,
            w.window_start,
            w.window_end,
            (t.created_time >= w.window_start AND t.created_time <= w.window_end) AS in_window
        FROM pos_windows w
        JOIN '{TRADES_GLOB}' t
          ON t.ticker = w.ticker
         AND t.created_time <= w.window_end
        """
    )
    rows_out = con.execute(
        """
        SELECT pos_id, yes_price, created_time
        FROM (
            SELECT
                pos_id, yes_price, created_time,
                ROW_NUMBER() OVER (
                    PARTITION BY pos_id
                    ORDER BY in_window DESC, created_time DESC
                ) AS rn
            FROM eligible_trades
        )
        WHERE rn = 1
        """
    ).fetchall()
    out: dict[int, tuple[float, datetime, str] | None] = {p.id: None for p in positions}
    for pos_id, yes_price, ts in rows_out:
        out[pos_id] = (float(yes_price), ts, "trade")
    return out


def compute_closing_lines(
    db_path: Path,
    con: duckdb.DuckDBPyConnection,
    positions: list[Position],
    as_of: datetime,
) -> dict[int, tuple[float, datetime, str] | None]:
    """Closing-line resolution with two sources:

    1. clv_snapshots table on the paper portfolio (written by the live monitor)
    2. unified Kalshi trade tree (historical fallback)

    Snapshots are preferred because they cover the actual paper-book universe;
    the trade tree is sparse for thin sports prop markets.
    """
    primary = _closing_lines_from_snapshots(db_path, positions, as_of)
    missing = [p for p in positions if primary.get(p.id) is None]
    if missing:
        secondary = _closing_lines_from_trades(con, missing, as_of)
        for pid, val in secondary.items():
            if val is not None:
                primary[pid] = val
    return primary


def compute_clv_pp(position: Position, closing_line: float) -> float:
    """Signed pp gap such that positive = we beat the line."""
    if position.side == "sell_yes":
        return (position.entry_price - closing_line) * 100.0
    # buy_yes
    return (closing_line - position.entry_price) * 100.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_PORTFOLIO_DB)
    ap.add_argument(
        "--status",
        choices=("open", "closed", "voided"),
        default=None,
        help="filter to one status (default: all except voided)",
    )
    ap.add_argument("--out", type=Path, default=None, help="optional parquet output")
    ap.add_argument(
        "--as-of",
        default=None,
        help="ISO timestamp to use as the right-edge for open positions (default: now)",
    )
    args = ap.parse_args()

    as_of = (
        datetime.fromisoformat(args.as_of).astimezone(timezone.utc)
        if args.as_of
        else datetime.now(timezone.utc)
    )

    positions = load_positions(args.db, args.status)
    # Voided positions aren't tradeable signals; drop unless explicitly requested.
    if args.status is None:
        positions = [p for p in positions if p.status != "voided"]
    if not positions:
        print("No positions to score.")
        return 0

    print(f"Scoring {len(positions)} positions from {args.db}")
    con = duckdb.connect()
    closing_lines = compute_closing_lines(args.db, con, positions, as_of)

    records: list[dict] = []
    for p in positions:
        cl = closing_lines.get(p.id)
        if cl is None:
            continue
        closing_line, line_time, source = cl
        clv_pp = compute_clv_pp(p, closing_line)
        records.append(
            {
                "pos_id": p.id,
                "ticker": p.ticker,
                "event_ticker": p.event_ticker,
                "category": p.category,
                "side": p.side,
                "status": p.status,
                "entry_price": p.entry_price,
                "entry_price_bin": (int(p.entry_price * 100) // 5) * 5,
                "closing_line": closing_line,
                "closing_line_time": line_time,
                "closing_line_source": source,
                "clv_pp": clv_pp,
                "edge_pp": p.edge_pp,
                "risk_budget": p.risk_budget,
                "realized_pnl": p.realized_pnl,
            }
        )

    if not records:
        print("No positions had any trade history; cannot compute CLV.")
        return 0

    df = pd.DataFrame(records)
    _report(df, skipped=len(positions) - len(df))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(args.out, index=False)
        print(f"\nWrote {len(df)} rows → {args.out}")
    return 0


def _report(df: pd.DataFrame, skipped: int) -> None:
    print()
    print("=" * 72)
    print(
        f"CLV summary — {len(df)} scored positions "
        f"({skipped} skipped: no closing-line trade available)"
    )
    print("=" * 72)
    _print_summary("Aggregate", df)

    print("\nBy status:")
    for status, sub in df.groupby("status"):
        _print_summary(f"  {status}", sub)

    print("\nBy side:")
    for side, sub in df.groupby("side"):
        _print_summary(f"  {side}", sub)

    print("\nBy category:")
    for cat, sub in df.groupby("category"):
        _print_summary(f"  {cat}", sub)

    print("\nBy entry-price bin (5¢):")
    for b, sub in df.groupby("entry_price_bin"):
        _print_summary(f"  {b:02d}-{b+5:02d}¢", sub)

    # Edge vs. CLV — is our edge_pp predictive?
    corr = df[["edge_pp", "clv_pp"]].corr().iloc[0, 1]
    print(f"\ncorr(edge_pp, clv_pp) = {corr:+.3f}  "
          "(ideal: strongly positive — high-edge picks should beat the line more)")


def _print_summary(label: str, sub: pd.DataFrame) -> None:
    if sub.empty:
        return
    n = len(sub)
    mean_pp = sub["clv_pp"].mean()
    median_pp = sub["clv_pp"].median()
    std_pp = sub["clv_pp"].std() if n > 1 else 0.0
    beat_rate = (sub["clv_pp"] > 0).mean() * 100
    print(
        f"{label:24s}  n={n:4d}  "
        f"mean={mean_pp:+6.2f}pp  median={median_pp:+6.2f}pp  "
        f"σ={std_pp:5.2f}pp  beat_line={beat_rate:5.1f}%"
    )


if __name__ == "__main__":
    raise SystemExit(main())
