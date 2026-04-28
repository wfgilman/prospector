"""SQLite-backed paper portfolio for the elder triple-screen perp book.

State model:
    nav         = initial_nav + sum(net_pnl over closed positions)
    locked_risk = sum(risk_budget over open positions)
    cash        = nav - locked_risk

A position's `risk_budget` is the dollars-at-risk if the stop fires:
    units × |entry_price - stop_price|
which is `risk_per_trade × nav` clipped by `max_position_frac × nav`.

Closing the position records:
    gross_pnl       direction-aware (units × (exit - entry) for LONG)
    fees            taker_fee × notional × 2 (round-trip)
    funding_cost    integrated from Hyperliquid funding history
                    (LONG pays when rate > 0; SHORT receives)
    net_pnl         gross_pnl − fees − funding_cost

We snapshot mid prices for every coin we hold a position in on each
tick, into `mid_snapshots`, so we can compute a CLV-equivalent later.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from prospector.templates.base import Direction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long','short')),
    units REAL NOT NULL CHECK (units > 0),
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    stop_price REAL NOT NULL CHECK (stop_price > 0),
    target_price REAL NOT NULL CHECK (target_price > 0),
    risk_budget REAL NOT NULL CHECK (risk_budget > 0),
    entry_bar_index INTEGER NOT NULL,
    entry_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','closed')),
    exit_price REAL,
    exit_bar_index INTEGER,
    exit_time TEXT,
    exit_reason TEXT,                  -- 'target' | 'stop' | 'end_of_data' | 'forced'
    gross_pnl REAL,
    fees_paid REAL,
    funding_cost REAL,
    net_pnl REAL
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_open_coin
    ON positions(coin) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS daily_snapshots (
    snapshot_date TEXT PRIMARY KEY,
    nav REAL NOT NULL,
    cash REAL NOT NULL,
    locked_risk REAL NOT NULL,
    open_positions INTEGER NOT NULL,
    trades_today INTEGER NOT NULL,
    realized_pnl_today REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mid_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    mid_price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mid_coin_time
    ON mid_snapshots(coin, snapshot_time);
"""


@dataclass(frozen=True)
class PortfolioConfig:
    initial_nav: float = 10_000.0
    risk_per_trade: float = 0.02            # Iron Triangle 2%
    max_position_frac: float = 0.05         # 5% NAV cap per position
    taker_fee: float = 0.00035              # Hyperliquid taker fee
    slippage_per_side: float = 0.0005       # 0.05% per side


@dataclass
class OpenPosition:
    id: int
    coin: str
    direction: Direction
    units: float
    entry_price: float
    stop_price: float
    target_price: float
    risk_budget: float
    entry_bar_index: int
    entry_time: str


@dataclass
class ClosedPosition:
    coin: str
    direction: Direction
    entry_price: float
    exit_price: float
    units: float
    exit_reason: str
    gross_pnl: float
    fees_paid: float
    funding_cost: float
    net_pnl: float


class PaperPortfolio:
    """Thin wrapper around the SQLite store enforcing position-lifecycle rules."""

    def __init__(self, db_path: Path, config: PortfolioConfig) -> None:
        self.db_path = db_path
        self.config = config
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(_SCHEMA)
            row = con.execute(
                "SELECT value FROM meta WHERE key='initial_nav'"
            ).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('initial_nav', ?)",
                    (str(self.config.initial_nav),),
                )

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def nav(self) -> float:
        """initial_nav + realized net P&L from closed positions."""
        with self._connect() as con:
            row = con.execute(
                "SELECT COALESCE(SUM(net_pnl), 0) FROM positions WHERE status='closed'"
            ).fetchone()
            realized = float(row[0])
        return self.config.initial_nav + realized

    def locked_risk(self) -> float:
        with self._connect() as con:
            row = con.execute(
                "SELECT COALESCE(SUM(risk_budget), 0) FROM positions WHERE status='open'"
            ).fetchone()
        return float(row[0])

    def cash(self) -> float:
        return self.nav() - self.locked_risk()

    def open_positions(self) -> list[OpenPosition]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, coin, direction, units, entry_price, stop_price, "
                "target_price, risk_budget, entry_bar_index, entry_time "
                "FROM positions WHERE status='open' ORDER BY id"
            ).fetchall()
        return [
            OpenPosition(
                id=r["id"], coin=r["coin"],
                direction=Direction(r["direction"]),
                units=r["units"], entry_price=r["entry_price"],
                stop_price=r["stop_price"], target_price=r["target_price"],
                risk_budget=r["risk_budget"],
                entry_bar_index=r["entry_bar_index"],
                entry_time=r["entry_time"],
            )
            for r in rows
        ]

    def has_open_position(self, coin: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM positions WHERE coin=? AND status='open' LIMIT 1",
                (coin,),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def size_position(self, entry: float, stop: float) -> tuple[float, float]:
        """
        Iron Triangle: risk_per_trade × NAV clipped by max_position_frac × NAV.

        Returns (units, risk_budget). Caller decides direction.
        """
        nav = self.nav()
        risk_dollars = min(
            self.config.risk_per_trade * nav,
            self.config.max_position_frac * nav,
        )
        per_unit_risk = abs(entry - stop)
        if per_unit_risk <= 0:
            return 0.0, 0.0
        units = risk_dollars / per_unit_risk
        return units, risk_dollars

    # ------------------------------------------------------------------
    # Open / close lifecycle
    # ------------------------------------------------------------------

    def open_position(
        self,
        coin: str,
        direction: Direction,
        units: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
        risk_budget: float,
        entry_bar_index: int,
        entry_time: datetime,
    ) -> int:
        if self.has_open_position(coin):
            raise ValueError(f"{coin}: already has an open position")
        if units <= 0:
            raise ValueError("units must be > 0")
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO positions (
                    coin, direction, units, entry_price, stop_price,
                    target_price, risk_budget, entry_bar_index, entry_time, status
                ) VALUES (?,?,?,?,?,?,?,?,?, 'open')
                """,
                (
                    coin, direction.value, units, entry_price, stop_price,
                    target_price, risk_budget, entry_bar_index,
                    entry_time.isoformat(),
                ),
            )
        return int(cur.lastrowid)

    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_bar_index: int,
        exit_time: datetime,
        exit_reason: str,
        funding_cost: float,
    ) -> ClosedPosition:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM positions WHERE id=? AND status='open'",
                (position_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"position {position_id} is not open")
            direction = Direction(row["direction"])
            units = row["units"]
            entry_price = row["entry_price"]
            sign = 1.0 if direction == Direction.LONG else -1.0
            gross_pnl = sign * units * (exit_price - entry_price)
            notional_round_trip = units * (entry_price + exit_price)
            fees = notional_round_trip * (
                self.config.taker_fee + self.config.slippage_per_side
            )
            net_pnl = gross_pnl - fees - funding_cost
            con.execute(
                """
                UPDATE positions SET status='closed',
                    exit_price=?, exit_bar_index=?, exit_time=?,
                    exit_reason=?, gross_pnl=?, fees_paid=?,
                    funding_cost=?, net_pnl=?
                 WHERE id=?
                """,
                (
                    exit_price, exit_bar_index, exit_time.isoformat(),
                    exit_reason, gross_pnl, fees, funding_cost, net_pnl,
                    position_id,
                ),
            )
        return ClosedPosition(
            coin=row["coin"], direction=direction,
            entry_price=entry_price, exit_price=exit_price,
            units=units, exit_reason=exit_reason,
            gross_pnl=gross_pnl, fees_paid=fees,
            funding_cost=funding_cost, net_pnl=net_pnl,
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def record_mid_snapshot(self, coin: str, mid_price: float, when: datetime) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO mid_snapshots(coin, snapshot_time, mid_price) "
                "VALUES (?, ?, ?)",
                (coin, when.isoformat(), mid_price),
            )

    def upsert_daily_snapshot(self, when: date | None = None) -> None:
        d = (when or datetime.now(timezone.utc).date()).isoformat()
        with self._connect() as con:
            nav_row = con.execute(
                "SELECT COALESCE(SUM(net_pnl), 0) FROM positions WHERE status='closed'"
            ).fetchone()
            realized = float(nav_row[0])
            nav = self.config.initial_nav + realized
            locked = float(con.execute(
                "SELECT COALESCE(SUM(risk_budget), 0) FROM positions WHERE status='open'"
            ).fetchone()[0])
            n_open = int(con.execute(
                "SELECT COUNT(*) FROM positions WHERE status='open'"
            ).fetchone()[0])
            today_realized = float(con.execute(
                "SELECT COALESCE(SUM(net_pnl), 0) FROM positions "
                "WHERE status='closed' AND substr(exit_time,1,10)=?",
                (d,),
            ).fetchone()[0])
            today_count = int(con.execute(
                "SELECT COUNT(*) FROM positions WHERE substr(entry_time,1,10)=?",
                (d,),
            ).fetchone()[0])
            con.execute(
                "INSERT OR REPLACE INTO daily_snapshots VALUES (?,?,?,?,?,?,?)",
                (d, nav, nav - locked, locked, n_open, today_count, today_realized),
            )
