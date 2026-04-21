"""SQLite-backed paper portfolio for the underwriting strategy.

State model:
  - `nav`  = initial_nav + sum(realized_pnl over closed positions)
  - `cash` = nav - locked_risk
  - `locked_risk` = sum(risk_budget over open positions)

A "risk_budget" is the maximum dollars we could lose on a position. For a
sell-yes entry at price p, risk = (1 - p) * contracts; on the win path we
collect p * contracts. For a buy-yes entry, risk = p * contracts.

Fees are modeled as a round-trip Kalshi taker fee charged at entry
(KALSHI_ROUND_TRIP_FEE_FACTOR * p * (1-p) * contracts). We store it as
`fees_paid` on each position and deduct it from realized_pnl on resolution.
Void refunds fees, so realized_pnl stays 0.

Constraints enforced at entry time:
  - per-position:     risk_budget <= max_position_frac * nav
  - per-event $:      sum(risk_budget for event) + new_risk <= max_event_frac * nav
  - per-event count:  open_positions_in_event < max_positions_per_event
  - per-subseries:    open_positions_in_subseries < max_positions_per_subseries
  - per-series:       open_positions_in_series < max_positions_per_series
  - daily cap:        trades_today < max_trades_per_day
  - available cash:   risk_budget <= cash
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from prospector.underwriting.calibration import KALSHI_ROUND_TRIP_FEE_FACTOR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT,
    category TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('sell_yes','buy_yes')),
    contracts INTEGER NOT NULL CHECK (contracts > 0),
    entry_price REAL NOT NULL CHECK (entry_price > 0 AND entry_price < 1),
    risk_budget REAL NOT NULL CHECK (risk_budget > 0),
    reward_potential REAL NOT NULL CHECK (reward_potential > 0),
    edge_pp REAL NOT NULL,
    entry_time TEXT NOT NULL,
    expected_close_time TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','closed','voided')),
    close_price REAL,
    close_time TEXT,
    realized_pnl REAL,
    market_result TEXT,
    fees_paid REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_event ON positions(event_ticker, status);
CREATE INDEX IF NOT EXISTS idx_positions_entry_time ON positions(entry_time);
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_ticker
    ON positions(ticker) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS daily_snapshots (
    snapshot_date TEXT PRIMARY KEY,
    nav REAL NOT NULL,
    cash REAL NOT NULL,
    locked_risk REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    trades_today INTEGER NOT NULL,
    realized_pnl_today REAL NOT NULL
);
"""


@dataclass(frozen=True)
class PortfolioState:
    nav: float
    cash: float
    locked_risk: float
    open_positions: int


@dataclass(frozen=True)
class PaperPosition:
    id: int
    ticker: str
    event_ticker: str
    series_ticker: str | None
    category: str
    side: str
    contracts: int
    entry_price: float
    risk_budget: float
    reward_potential: float
    edge_pp: float
    entry_time: datetime
    expected_close_time: datetime | None
    status: str
    close_price: float | None
    close_time: datetime | None
    realized_pnl: float | None
    market_result: str | None
    fees_paid: float


class RejectedEntry(Exception):
    """Raised when a proposed entry violates a portfolio constraint."""


@dataclass(frozen=True)
class PortfolioConfig:
    initial_nav: float = 10_000.0
    max_position_frac: float = 0.01    # per-position cap: 1% of NAV at risk
    max_event_frac: float = 0.05       # per-event cap: 5% of NAV at risk
    max_trades_per_day: int = 20
    # Diversity: treating N positions on the same event/subseries/series as
    # N independent bets overstates diversification — they share signal.
    # Subseries = event_ticker with the trailing segment stripped (typically a
    # game/round grouping). Series = series_ticker (e.g. KXNFL).
    max_positions_per_event: int = 1
    max_positions_per_subseries: int = 1
    max_positions_per_series: int = 3


class PaperPortfolio:
    """SQLite-backed paper portfolio. One instance per database file."""

    def __init__(self, db_path: str | Path, config: PortfolioConfig | None = None):
        self.db_path = Path(db_path)
        self.config = config or PortfolioConfig()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._apply_migrations()
        self._ensure_initial_nav()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PaperPortfolio":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _apply_migrations(self) -> None:
        """Add columns introduced after the initial schema; backfill where useful.

        Using `CREATE TABLE IF NOT EXISTS` means the column list is only set for
        brand-new databases. For existing DBs (e.g. paper portfolios already
        running in production) we inspect `PRAGMA table_info` and add missing
        columns by hand.
        """
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(positions)")}
        if "fees_paid" not in cols:
            self._conn.execute(
                "ALTER TABLE positions ADD COLUMN fees_paid REAL NOT NULL DEFAULT 0"
            )
            # Backfill an estimate so open-position locked capital and future
            # closes use realistic fees. Closed rows keep their original
            # realized_pnl — we don't retroactively rewrite history.
            self._conn.execute(
                """UPDATE positions
                   SET fees_paid = ? * entry_price * (1 - entry_price) * contracts""",
                (KALSHI_ROUND_TRIP_FEE_FACTOR,),
            )
        # Older rows may have an empty/NULL series_ticker because the Kalshi
        # /markets endpoint doesn't always return it. Derive from event_ticker
        # so the series-level diversity cap applies to pre-migration positions.
        self._conn.execute(
            """UPDATE positions
               SET series_ticker = substr(event_ticker, 1, instr(event_ticker || '-', '-') - 1)
               WHERE (series_ticker IS NULL OR series_ticker = '')
                 AND event_ticker IS NOT NULL
                 AND event_ticker != ''"""
        )

    def _ensure_initial_nav(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'initial_nav'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('initial_nav', ?)",
                (str(self.config.initial_nav),),
            )

    @property
    def initial_nav(self) -> float:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'initial_nav'"
        ).fetchone()
        return float(row["value"])

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def state(self) -> PortfolioState:
        realized = self._conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS r FROM positions WHERE status = 'closed'"
        ).fetchone()["r"]
        locked = self._conn.execute(
            "SELECT COALESCE(SUM(risk_budget), 0) AS l FROM positions WHERE status = 'open'"
        ).fetchone()["l"]
        n_open = self._conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE status = 'open'"
        ).fetchone()["n"]
        nav = self.initial_nav + realized
        return PortfolioState(
            nav=nav,
            cash=nav - locked,
            locked_risk=locked,
            open_positions=n_open,
        )

    def trades_today(self, today: date | None = None) -> int:
        today = today or datetime.now(timezone.utc).date()
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE DATE(entry_time) = ?",
            (today.isoformat(),),
        ).fetchone()
        return int(row["n"])

    def event_risk(self, event_ticker: str) -> float:
        row = self._conn.execute(
            """SELECT COALESCE(SUM(risk_budget), 0) AS r
               FROM positions
               WHERE event_ticker = ? AND status = 'open'""",
            (event_ticker,),
        ).fetchone()
        return float(row["r"])

    def open_positions_in_event(self, event_ticker: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE event_ticker = ? AND status = 'open'",
            (event_ticker,),
        ).fetchone()
        return int(row["n"])

    def open_positions_in_subseries(self, subseries_prefix: str) -> int:
        """Count open positions whose event_ticker starts with the subseries prefix.

        We store the full event_ticker on each row, so we match by the prefix
        "subseries_prefix-" to ensure KXNFL-2026-W01 doesn't also match
        KXNFL-2026-W01B.
        """
        row = self._conn.execute(
            """SELECT COUNT(*) AS n FROM positions
               WHERE status = 'open'
                 AND (event_ticker = ? OR event_ticker LIKE ? || '-%')""",
            (subseries_prefix, subseries_prefix),
        ).fetchone()
        return int(row["n"])

    def open_positions_in_series(self, series_ticker: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM positions WHERE series_ticker = ? AND status = 'open'",
            (series_ticker,),
        ).fetchone()
        return int(row["n"])

    def has_open_position(self, ticker: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM positions WHERE ticker = ? AND status = 'open' LIMIT 1",
            (ticker,),
        ).fetchone()
        return row is not None

    def size_position(
        self,
        edge_pp: float,
        entry_price: float,
        side: str,
        kelly_fraction: float = 0.25,
    ) -> float:
        """Return dollars of risk budget for a position, clamped by
        `max_position_frac * nav`.

        Kelly derivation for a sell-yes bet at price P with actual YES rate q
        (positive edge means q < P). Letting p_win = 1 - q and net odds
        b = P/(1-P) (per $ at risk, we win P/(1-P) on the NO outcome), the
        classical Kelly formula f* = p_win - p_lose/b simplifies to:

            f* = (P - q) / P   = prob_edge / entry_price   (sell-yes)

        Symmetrically for buy-yes at P with q > P:

            f* = (q - P) / (1 - P) = prob_edge / (1 - entry_price)   (buy-yes)

        The input `edge_pp` is the *fee-adjusted* probability edge (from
        `fee_adjusted_edge`), expressed in percentage points. Earlier
        revisions of this function divided by `P/(1-P)` instead of `P`,
        which silently undersized high-price sell-yes bets by a factor of
        (1-P) — negligible at P=0.5, but 1/100 at P=0.99. That's why the
        pre-fix book sized longshots at pennies.
        """
        state = self.state()
        nav = state.nav
        edge = edge_pp / 100.0
        denom = entry_price if side == "sell_yes" else (1.0 - entry_price)
        if denom <= 0:
            return 0.0
        kelly = max(0.0, edge / denom)
        frac = min(kelly * kelly_fraction, self.config.max_position_frac)
        return frac * nav

    def enter(
        self,
        *,
        ticker: str,
        event_ticker: str,
        series_ticker: str | None,
        category: str,
        side: str,
        entry_price: float,
        edge_pp: float,
        risk_budget: float,
        expected_close_time: datetime | None = None,
        entry_time: datetime | None = None,
    ) -> PaperPosition:
        if side not in ("sell_yes", "buy_yes"):
            raise ValueError(f"side must be sell_yes or buy_yes, got {side!r}")
        if not 0 < entry_price < 1:
            raise ValueError(f"entry_price must be in (0, 1), got {entry_price}")
        if risk_budget <= 0:
            raise RejectedEntry(f"risk_budget must be positive, got {risk_budget}")

        state = self.state()
        if risk_budget > self.config.max_position_frac * state.nav + 1e-9:
            raise RejectedEntry(
                f"risk_budget {risk_budget:.2f} exceeds per-position cap "
                f"{self.config.max_position_frac * state.nav:.2f}"
            )
        if risk_budget > state.cash + 1e-9:
            raise RejectedEntry(
                f"insufficient cash: need {risk_budget:.2f}, have {state.cash:.2f}"
            )
        event_cap = self.config.max_event_frac * state.nav
        if self.event_risk(event_ticker) + risk_budget > event_cap + 1e-9:
            raise RejectedEntry(
                f"event {event_ticker} exposure would exceed cap {event_cap:.2f}"
            )
        if self.open_positions_in_event(event_ticker) >= self.config.max_positions_per_event:
            raise RejectedEntry(
                f"event {event_ticker} already has "
                f"{self.config.max_positions_per_event} open position(s)"
            )
        subseries = _subseries_of(event_ticker)
        if self.open_positions_in_subseries(subseries) >= self.config.max_positions_per_subseries:
            raise RejectedEntry(
                f"subseries {subseries} already has "
                f"{self.config.max_positions_per_subseries} open position(s)"
            )
        if series_ticker and (
            self.open_positions_in_series(series_ticker) >= self.config.max_positions_per_series
        ):
            raise RejectedEntry(
                f"series {series_ticker} already has "
                f"{self.config.max_positions_per_series} open position(s)"
            )
        if self.trades_today() >= self.config.max_trades_per_day:
            raise RejectedEntry(
                f"daily trade cap {self.config.max_trades_per_day} reached"
            )
        if self.has_open_position(ticker):
            raise RejectedEntry(f"already hold open position in {ticker}")

        per_risk = (1.0 - entry_price) if side == "sell_yes" else entry_price
        per_reward = entry_price if side == "sell_yes" else (1.0 - entry_price)
        contracts = max(1, int(risk_budget / per_risk))
        reward_potential = contracts * per_reward
        # Recompute actual risk from integer contracts for ledger accuracy.
        actual_risk = contracts * per_risk
        fees_paid = KALSHI_ROUND_TRIP_FEE_FACTOR * entry_price * (1.0 - entry_price) * contracts
        entry_time = entry_time or datetime.now(timezone.utc)

        with self._txn() as conn:
            cur = conn.execute(
                """INSERT INTO positions(
                    ticker, event_ticker, series_ticker, category, side,
                    contracts, entry_price, risk_budget, reward_potential,
                    edge_pp, entry_time, expected_close_time, fees_paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    event_ticker,
                    series_ticker,
                    category,
                    side,
                    contracts,
                    entry_price,
                    actual_risk,
                    reward_potential,
                    edge_pp,
                    entry_time.isoformat(),
                    expected_close_time.isoformat() if expected_close_time else None,
                    fees_paid,
                ),
            )
            pos_id = cur.lastrowid
        return self._fetch(pos_id)

    def resolve(
        self,
        ticker: str,
        market_result: str,
        close_time: datetime | None = None,
    ) -> PaperPosition:
        """Close an open position using a binary market resolution."""
        if market_result not in ("yes", "no"):
            raise ValueError(f"market_result must be 'yes' or 'no', got {market_result!r}")
        row = self._conn.execute(
            "SELECT * FROM positions WHERE ticker = ? AND status = 'open'",
            (ticker,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no open position for ticker {ticker!r}")
        side = row["side"]
        won = (side == "sell_yes" and market_result == "no") or (
            side == "buy_yes" and market_result == "yes"
        )
        gross = row["reward_potential"] if won else -row["risk_budget"]
        # Kalshi charges taker fees on entry; resolution is free. We model
        # the round-trip fee (paid up-front in `fees_paid`) as a realized loss
        # booked at resolution time so NAV tracks end-to-end P&L.
        pnl = gross - row["fees_paid"]
        close_price = 1.0 if market_result == "yes" else 0.0
        close_time = close_time or datetime.now(timezone.utc)
        with self._txn() as conn:
            conn.execute(
                """UPDATE positions
                   SET status = 'closed',
                       close_price = ?,
                       close_time = ?,
                       realized_pnl = ?,
                       market_result = ?
                   WHERE id = ?""",
                (
                    close_price,
                    close_time.isoformat(),
                    pnl,
                    market_result,
                    row["id"],
                ),
            )
        return self._fetch(row["id"])

    def void(self, ticker: str, close_time: datetime | None = None) -> PaperPosition:
        """Close a position with zero P&L (market was voided)."""
        row = self._conn.execute(
            "SELECT id FROM positions WHERE ticker = ? AND status = 'open'",
            (ticker,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no open position for ticker {ticker!r}")
        close_time = close_time or datetime.now(timezone.utc)
        with self._txn() as conn:
            conn.execute(
                """UPDATE positions
                   SET status = 'voided',
                       realized_pnl = 0.0,
                       close_time = ?
                   WHERE id = ?""",
                (close_time.isoformat(), row["id"]),
            )
        return self._fetch(row["id"])

    def open_positions(self) -> list[PaperPosition]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_time"
        ).fetchall()
        return [_row_to_position(r) for r in rows]

    def snapshot_today(self, today: date | None = None) -> None:
        today = today or datetime.now(timezone.utc).date()
        state = self.state()
        trades = self.trades_today(today)
        realized_today = self._conn.execute(
            """SELECT COALESCE(SUM(realized_pnl), 0) AS r
               FROM positions
               WHERE status = 'closed' AND DATE(close_time) = ?""",
            (today.isoformat(),),
        ).fetchone()["r"]
        with self._txn() as conn:
            conn.execute(
                """INSERT INTO daily_snapshots(
                    snapshot_date, nav, cash, locked_risk,
                    open_positions, trades_today, realized_pnl_today
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    nav = excluded.nav,
                    cash = excluded.cash,
                    locked_risk = excluded.locked_risk,
                    open_positions = excluded.open_positions,
                    trades_today = excluded.trades_today,
                    realized_pnl_today = excluded.realized_pnl_today""",
                (
                    today.isoformat(),
                    state.nav,
                    state.cash,
                    state.locked_risk,
                    state.open_positions,
                    trades,
                    float(realized_today),
                ),
            )

    def _fetch(self, pos_id: int) -> PaperPosition:
        row = self._conn.execute(
            "SELECT * FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()
        return _row_to_position(row)


def _subseries_of(event_ticker: str) -> str:
    """Return the event_ticker with its trailing segment stripped.

    Kalshi event_tickers often have the form SERIES-SEASON-ROUND-SLOT; stripping
    the final segment groups events that share the same round (e.g. all
    sub-markets of one NFL game). Used to cap correlated bets.
    """
    parts = event_ticker.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else event_ticker


def _row_to_position(row: sqlite3.Row) -> PaperPosition:
    return PaperPosition(
        id=row["id"],
        ticker=row["ticker"],
        event_ticker=row["event_ticker"],
        series_ticker=row["series_ticker"],
        category=row["category"],
        side=row["side"],
        contracts=row["contracts"],
        entry_price=row["entry_price"],
        risk_budget=row["risk_budget"],
        reward_potential=row["reward_potential"],
        edge_pp=row["edge_pp"],
        entry_time=datetime.fromisoformat(row["entry_time"]),
        expected_close_time=(
            datetime.fromisoformat(row["expected_close_time"])
            if row["expected_close_time"]
            else None
        ),
        status=row["status"],
        close_price=row["close_price"],
        close_time=(
            datetime.fromisoformat(row["close_time"]) if row["close_time"] else None
        ),
        realized_pnl=row["realized_pnl"],
        market_result=row["market_result"],
        fees_paid=row["fees_paid"],
    )
