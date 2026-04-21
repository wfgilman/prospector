"""Scan active Kalshi markets for calibration-driven edge.

For each open market:
  1. Classify the event_ticker into a category.
  2. Find the best executable price for each side from the orderbook.
  3. Look up the calibration bin for that price.
  4. If the bin's predicted side agrees with what we'd do at that price and the
     fee-adjusted edge clears our minimum, surface a Candidate.

The scanner itself is stateless — it reads live data from the client and the
calibration from the store. Capital and throughput decisions happen in the
portfolio / runner layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from prospector.kalshi import KalshiClient, Market, Orderbook
from prospector.underwriting.calibration import Calibration, CalibrationBin, fee_adjusted_edge
from prospector.underwriting.categorize import classify


@dataclass(frozen=True)
class Candidate:
    """A scanner result: one tradeable edge found in a live market."""

    market: Market
    category: str
    bin: CalibrationBin
    side: str                # "sell_yes" or "buy_yes"
    entry_price: float       # price we'd pay/receive per YES contract
    edge_pp: float           # fee-adjusted edge in percentage points
    contracts_at_top: int    # size available at the top level

    @property
    def risk_per_contract(self) -> float:
        """Dollars at risk per contract we put on."""
        if self.side == "sell_yes":
            return 1.0 - self.entry_price
        return self.entry_price

    @property
    def reward_per_contract(self) -> float:
        """Dollars collected per contract if we win."""
        if self.side == "sell_yes":
            return self.entry_price
        return 1.0 - self.entry_price


def _executable_prices(ob: Orderbook) -> tuple[float | None, float | None, int, int]:
    """Return (sell_yes_price, buy_yes_price, sell_yes_size, buy_yes_size).

    Kalshi's orderbook has no asks — every level is a bid. The yes-side lists
    people willing to buy YES, the no-side lists people willing to buy NO.
    Because yes + no = 1 on a binary market:
      - To SELL YES: match the best YES bid. Price = yes_bid.
      - To BUY YES:  match the best NO bid (sell them NO at their bid). Cost
        of equivalent YES exposure = 1 - no_bid.
    """
    if not ob.yes and not ob.no:
        return (None, None, 0, 0)
    sell_yes_price = ob.yes[0].price if ob.yes else None
    sell_yes_size = ob.yes[0].size if ob.yes else 0
    buy_yes_price = (1.0 - ob.no[0].price) if ob.no else None
    buy_yes_size = ob.no[0].size if ob.no else 0
    return (sell_yes_price, buy_yes_price, sell_yes_size, buy_yes_size)


def evaluate_market(
    market: Market,
    ob: Orderbook,
    calibration: Calibration,
    *,
    min_edge_pp: float,
) -> Candidate | None:
    """Return the best candidate from a market, or None if no edge.

    Called once per active market per scan cycle. If both sides show an edge
    (unusual; indicates calibration disagrees across price levels), we pick the
    larger one.
    """
    category = classify(market.event_ticker)
    sell_yes_price, buy_yes_price, sell_size, buy_size = _executable_prices(ob)

    candidates: list[Candidate] = []
    if sell_yes_price is not None and 0 < sell_yes_price < 1:
        c = _evaluate_side(
            market, category, sell_yes_price, "sell_yes", sell_size, calibration, min_edge_pp
        )
        if c is not None:
            candidates.append(c)
    if buy_yes_price is not None and 0 < buy_yes_price < 1:
        c = _evaluate_side(
            market, category, buy_yes_price, "buy_yes", buy_size, calibration, min_edge_pp
        )
        if c is not None:
            candidates.append(c)

    if not candidates:
        return None
    return max(candidates, key=lambda c: c.edge_pp)


def _evaluate_side(
    market: Market,
    category: str,
    entry_price: float,
    side: str,
    size: int,
    calibration: Calibration,
    min_edge_pp: float,
) -> Candidate | None:
    cal_bin = calibration.lookup(category, entry_price)
    if cal_bin is None or cal_bin.side != side:
        return None
    # Re-compute edge at the actual entry price (not the bin midpoint).
    edge = fee_adjusted_edge(entry_price, cal_bin.actual_rate)
    edge_pp = edge * 100
    if edge_pp < min_edge_pp:
        return None
    return Candidate(
        market=market,
        category=category,
        bin=cal_bin,
        side=side,
        entry_price=entry_price,
        edge_pp=edge_pp,
        contracts_at_top=size,
    )


def scan(
    client: KalshiClient,
    calibration: Calibration,
    *,
    categories: Iterable[str] | None = None,
    min_edge_pp: float = 5.0,
    orderbook_depth: int = 1,
) -> Iterator[Candidate]:
    """Yield Candidates for every active market with sufficient edge.

    When `categories` is set (e.g. `("sports", "crypto")`), iteration is
    event-first: we page `/events?status=open`, classify each event by its
    `event_ticker`, and only expand markets for kept events. This skips the
    long tail of political speculation and multi-game sub-markets that
    dominate `/markets?status=open` without carrying calibrated edge.

    Markets with no bid on either side are skipped — no executable price
    means no candidate. We don't gate on lifetime `volume`: live markets
    often have zero trades yet still quote actively, and `calibration.min_volume`
    is a dataset-quality floor for historical resolved markets, not a
    live-liquidity signal.
    """
    allowed = set(categories) if categories is not None else None
    for market in _iter_markets(client, allowed):
        if market.yes_bid is None and market.no_bid is None:
            continue
        try:
            ob = client.fetch_orderbook(market.ticker, depth=orderbook_depth)
        except Exception:
            continue
        candidate = evaluate_market(market, ob, calibration, min_edge_pp=min_edge_pp)
        if candidate is not None:
            yield candidate


def _iter_markets(
    client: KalshiClient, allowed: set[str] | None
) -> Iterator[Market]:
    """Yield markets worth evaluating.

    If `allowed` is None, paginate all open markets. Otherwise walk events
    first, skip events whose category isn't allowed, then expand only the
    survivors.
    """
    if allowed is None:
        yield from client.iter_markets(status="open")
        return
    for event in client.iter_events(status="open"):
        event_ticker = event.get("event_ticker")
        if not event_ticker or classify(event_ticker) not in allowed:
            continue
        try:
            yield from client.iter_markets(status="open", event_ticker=event_ticker)
        except Exception:
            continue
