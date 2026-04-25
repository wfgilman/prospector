"""Poll Kalshi for resolution of open paper positions.

Iterates over the portfolio's open tickers, re-fetches each market, and:
  - on a binary result ("yes" / "no"): resolves the paper position with that P&L
  - on status "voided" (or empty result after settlement): voids the position
  - on still-open markets: leaves the position in place

Intended to be invoked on a schedule by the runner. Safe to call even with
zero open positions (it's a no-op in that case).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from prospector.kalshi import KalshiClient, KalshiError
from prospector.strategies.pm_underwriting.portfolio import PaperPortfolio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonitorReport:
    checked: int
    resolved: int
    voided: int
    still_open: int
    errors: int

    @property
    def total_closed(self) -> int:
        return self.resolved + self.voided


def sweep(client: KalshiClient, portfolio: PaperPortfolio) -> MonitorReport:
    """Check every open paper position and resolve/void as appropriate."""
    open_positions = portfolio.open_positions()
    resolved = voided = still_open = errors = 0
    for pos in open_positions:
        try:
            market = client.fetch_market(pos.ticker)
        except KalshiError:
            logger.warning("fetch_market failed for %s", pos.ticker)
            errors += 1
            continue
        # Always record a CLV snapshot (open or settled) — the latest snapshot
        # before resolution becomes the closing-line reference for this trade.
        portfolio.record_clv_snapshot(
            pos.ticker,
            yes_bid=market.yes_bid,
            yes_ask=market.yes_ask,
            last_price=market.last_price,
            market_status=market.status,
        )
        status = market.status.lower()
        result = market.result.lower()
        if status in ("settled", "finalized") and result in ("yes", "no"):
            portfolio.resolve(pos.ticker, result, close_time=market.close_time)
            resolved += 1
        elif status == "voided" or (status in ("settled", "finalized") and not result):
            portfolio.void(pos.ticker, close_time=market.close_time)
            voided += 1
        else:
            still_open += 1
    return MonitorReport(
        checked=len(open_positions),
        resolved=resolved,
        voided=voided,
        still_open=still_open,
        errors=errors,
    )
