"""Typed data models for the Kalshi API responses we care about.

Kalshi migrated to `*_dollars` string fields in January 2026 and deprecated the
legacy integer-cents fields. We parse the dollar fields and fall back to the
cents form only if the dollar field is absent. All prices on our side are
represented as floats in [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OrderbookLevel:
    """One price level: price in [0, 1] and contract count."""

    price: float
    size: int


@dataclass(frozen=True)
class Orderbook:
    """Top-of-book view for a single market.

    `yes` is ordered best-to-worst from the YES-buyer perspective; same for `no`.
    Empty lists indicate no resting orders on that side.
    """

    ticker: str
    yes: list[OrderbookLevel]
    no: list[OrderbookLevel]

    @property
    def yes_best_bid(self) -> float | None:
        return self.yes[0].price if self.yes else None

    @property
    def no_best_bid(self) -> float | None:
        return self.no[0].price if self.no else None


@dataclass(frozen=True)
class Market:
    """A single Kalshi binary market.

    All price fields are floats in [0, 1]. `result` is one of "yes", "no",
    "", or a settlement-specific string once the market resolves.
    """

    ticker: str
    event_ticker: str
    series_ticker: str
    title: str
    status: str
    result: str
    open_time: datetime | None
    close_time: datetime | None
    expiration_time: datetime | None
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    last_price: float | None
    volume: int
    open_interest: int
    category: str
    raw: dict

    @property
    def is_open(self) -> bool:
        return self.status.lower() in ("active", "open", "initialized")

    @property
    def is_resolved(self) -> bool:
        return self.status.lower() in ("settled", "finalized")


@dataclass(frozen=True)
class Position:
    """A single open position in the trader's portfolio."""

    ticker: str
    contracts: int
    side: str
    average_price: float | None
    market_exposure: float
    realized_pnl: float


@dataclass(frozen=True)
class Trade:
    """A single executed trade on a Kalshi market.

    Prices are floats in [0, 1]. `taker_side` is the side (yes/no) that took
    liquidity. Matches the schema shape of Kalshi's `/markets/trades` response
    normalized to our canonical form (floats not cents; UTC datetimes)."""

    trade_id: str
    ticker: str
    count: int
    yes_price: float
    no_price: float
    taker_side: str
    created_time: datetime
