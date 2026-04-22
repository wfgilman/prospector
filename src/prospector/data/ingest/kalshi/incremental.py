"""Kalshi incremental pull driver.

Designed to run on a daily (or more frequent) cron. Since the backfill
module already handles per-ticker watermarking, the incremental path
simply:
  1. Refreshes event lists for the configured series (catches newly-
     listed events).
  2. For tickers with a watermark, fetches trades after `last_trade_time`
     and appends. Tickers without a watermark fall through to the same
     backfill path (which will do a full pull).
  3. For markets, takes a fresh snapshot per day (the `pulled_at` column
     partitions by day, so daily snapshots are preserved).

The incremental run is the normal operating mode after the initial
backfill; it never overwrites historical partitions.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from prospector.data.ingest.kalshi import watermark, writer
from prospector.kalshi.client import KalshiClient

logger = logging.getLogger(__name__)


def pull_incremental(
    client: KalshiClient,
    series_tickers: list[str],
    root: Path,
    *,
    rate_limit_sleep_s: float = 0.3,
) -> dict:
    """For each series: refresh events, then for every ticker with a
    watermark pull trades since `last_trade_time`. Returns a summary dict.

    New tickers (no watermark yet) are not backfilled here — call the
    backfill driver for those. Rationale: incremental runs should have
    bounded duration; a new high-volume ticker's full history could take
    hours and shouldn't block the daily cron."""
    pulled_at = datetime.now(timezone.utc)
    state = watermark.load(root)
    summary: dict = {
        "pulled_at": pulled_at.isoformat(),
        "by_series": {},
    }

    for series in series_tickers:
        events = list(client.iter_events(
            status="open,closed,settled",
            series_ticker=series,
        ))
        writer.write_events(events, root, pulled_at)
        watermark.update_events_pulled(state, series, pulled_at)

        markets = list(client.iter_markets(
            status="open", series_ticker=series,
        ))
        mdf = writer.markets_to_frame(markets, pulled_at=pulled_at)
        writer.write_markets(mdf, root)
        ticker_to_event = {m.ticker: m.event_ticker for m in markets}

        new_trades = 0
        tickers_updated = 0
        for m in markets:
            last_time = watermark.last_trade_time(state, m.ticker)
            min_ts = None
            if last_time is not None:
                # Kalshi API takes seconds-since-epoch.
                min_ts = int(last_time.timestamp())
            # Skip tickers we've never seen here — backfill owns initial pulls.
            if min_ts is None:
                continue
            trades = list(client.iter_trades(ticker=m.ticker, min_ts=min_ts))
            time.sleep(rate_limit_sleep_s)
            if not trades:
                continue
            # Drop the trade that equals last_trade_id (boundary inclusion).
            last_id = (
                state.get("trades_by_ticker", {})
                     .get(m.ticker, {})
                     .get("last_trade_id")
            )
            if last_id:
                trades = [t for t in trades if t.trade_id != last_id]
            if not trades:
                continue
            tdf = writer.trades_to_frame(trades, ticker_to_event)
            writer.write_trades(tdf, root)
            tickers_updated += 1
            new_trades += len(trades)

            latest = max(trades, key=lambda t: t.created_time)
            watermark.update_trades(
                state, m.ticker,
                last_trade_id=latest.trade_id,
                last_trade_time=latest.created_time,
                pulled_at=pulled_at,
            )
            watermark.save(root, state)

        summary["by_series"][series] = {
            "events": len(events),
            "markets": len(markets),
            "tickers_updated": tickers_updated,
            "new_trades": new_trades,
        }
        logger.info(
            "%s incremental: %d events, %d markets, %d tickers updated, %d new trades",
            series, len(events), len(markets), tickers_updated, new_trades,
        )

    watermark.save(root, state)
    return summary
