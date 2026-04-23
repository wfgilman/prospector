"""Kalshi historical backfill driver.

Walks closed/settled events for a configured set of series tickers, fetches
the full market ladder per event, then fetches every trade per market and
writes to date-partitioned parquet under `data/kalshi/`.

Idempotent: re-running the same backfill will produce the same output
(trade_id-deduped). Resumable: the watermark state tracks which tickers
have been fully backfilled, so interrupted runs pick up where they left
off on the next invocation.

Not run from Claude Code — requires user's Kalshi credentials (env vars
KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH) and makes live API calls.
Entry point: `scripts/backfill_kalshi.py`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from prospector.data.ingest.kalshi import watermark, writer
from prospector.kalshi.client import KalshiClient
from prospector.kalshi.models import Market


def _parse_event_close_time(event: dict) -> datetime | None:
    """Pull an event's resolution time from an /events response.

    Kalshi's `/events` payload does not embed market-level close_time, but
    does include `strike_date` (event resolution timestamp) and
    `last_updated_ts` as fallback. We use strike_date when present."""
    raw = event.get("strike_date") or event.get("last_updated_ts")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)


@dataclass
class BackfillPlan:
    """Which series to backfill, with optional ticker filters per series.

    Example:
        BackfillPlan(series_tickers=["KXBTC", "KXETH", "KXFED"])

    Kalshi's /events status param takes exactly one value, not a list.
    Default to 'settled' since historical-backfill consumers want resolved
    events. Callers that also want 'closed' events (past close_time,
    pending settlement) can pass status='closed' and run a second pass.
    """

    series_tickers: list[str]
    status: str = "settled"
    max_events_per_series: int | None = None   # mostly for pilot runs
    close_before: datetime | None = None       # only pull events closing before this
    rate_limit_sleep_s: float = 0.3            # pause between API calls
    skip_tickers_with_watermark: bool = True   # resumability


@dataclass
class BackfillResult:
    series_ticker: str
    events_seen: int
    markets_seen: int
    tickers_with_trades: int
    trades_written: int
    trades_partitions_touched: int
    elapsed_seconds: float


def _iter_event_markets(
    client: KalshiClient,
    event_ticker: str,
    *,
    use_historical: bool,
) -> Iterable[Market]:
    """Yield markets for a given event.

    Two paths:
      - Live: `/events/{event_ticker}` returns embedded markets. Only works
        within the retention window.
      - Historical: `/historical/markets?event_ticker=X` returns the full
        market ladder with richer metadata. Works regardless of age.

    Caller picks based on the event's strike_date vs. the historical
    cutoff (see `_pick_endpoint_mode`)."""
    if use_historical:
        yield from client.iter_historical_markets(event_ticker=event_ticker)
    else:
        _event, markets = client.fetch_event(event_ticker)
        yield from markets


def _parse_cutoff(raw: dict) -> datetime:
    """Parse the `/historical/cutoff` response into a UTC datetime.
    All three cutoff fields are identical in practice; we use
    `trades_created_ts` as the canonical boundary."""
    ts = raw.get("trades_created_ts") or raw.get("market_settled_ts")
    if not ts:
        raise KeyError("no cutoff timestamp in historical/cutoff response")
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _pick_endpoint_mode(
    strike_date: datetime | None, cutoff: datetime
) -> bool:
    """True = use /historical/* endpoints, False = use live endpoints."""
    if strike_date is None:
        return True  # conservative: unknown dates assumed historical
    return strike_date < cutoff


def backfill_series(
    client: KalshiClient,
    series_ticker: str,
    root: Path,
    *,
    status: str = "settled",
    max_events: int | None = None,
    close_before: datetime | None = None,
    rate_limit_sleep_s: float = 0.3,
    skip_with_watermark: bool = True,
    cutoff: datetime | None = None,
) -> BackfillResult:
    """Backfill settled (or configured-status) events for a single series.
    Writes to partitioned parquet under `root`. Returns counts.

    Per-event endpoint selection: events whose `strike_date` is before the
    historical cutoff are pulled via `/historical/*`; newer events via the
    live `/events/{ticker}` + `/markets/trades` path. The cutoff is fetched
    once per run (pass via `cutoff=` or will be fetched automatically)."""
    start = time.monotonic()
    state = watermark.load(root)
    pulled_at = datetime.now(timezone.utc)

    if cutoff is None:
        cutoff = _parse_cutoff(client.fetch_historical_cutoff())
    logger.info("using historical cutoff: %s", cutoff.isoformat())

    events = list(client.iter_events(status=status, series_ticker=series_ticker))
    if close_before is not None:
        before = close_before
        if before.tzinfo is None:
            before = before.replace(tzinfo=timezone.utc)
        filtered = []
        dropped_no_date = 0
        for ev in events:
            ct = _parse_event_close_time(ev)
            if ct is None:
                # Drop events we can't time-check rather than silently
                # admitting them (previous bug: kept all untimed events).
                dropped_no_date += 1
                continue
            if ct < before:
                filtered.append(ev)
        if dropped_no_date:
            logger.warning(
                "%s: %d events had no strike_date/last_updated_ts — "
                "dropped from close_before filter",
                series_ticker, dropped_no_date,
            )
        events = filtered
    if max_events is not None:
        events = events[:max_events]
    logger.info("%s: %d events", series_ticker, len(events))

    # Persist event metadata first (useful as-is and also if the run is cut short).
    writer.write_events(events, root, pulled_at)

    markets_seen = 0
    tickers_with_trades = 0
    trades_written = 0
    partitions_touched: set[str] = set()
    n_historical = 0
    n_live = 0

    for event in events:
        event_ticker = event.get("event_ticker", "")
        if not event_ticker:
            continue
        strike_date = _parse_event_close_time(event)
        use_hist = _pick_endpoint_mode(strike_date, cutoff)
        if use_hist:
            n_historical += 1
        else:
            n_live += 1

        markets = list(_iter_event_markets(
            client, event_ticker, use_historical=use_hist
        ))
        markets_seen += len(markets)
        if not markets:
            continue

        # Snapshot markets.
        mdf = writer.markets_to_frame(markets, pulled_at=pulled_at)
        writer.write_markets(mdf, root)

        ticker_to_event = {m.ticker: m.event_ticker for m in markets}

        # Pull trades per ticker.
        for m in markets:
            if (
                skip_with_watermark
                and watermark.last_trade_time(state, m.ticker) is not None
            ):
                continue
            if use_hist:
                trades = list(client.iter_historical_trades(ticker=m.ticker))
            else:
                trades = list(client.iter_trades(ticker=m.ticker))
            time.sleep(rate_limit_sleep_s)
            if not trades:
                continue
            tickers_with_trades += 1
            tdf = writer.trades_to_frame(trades, ticker_to_event)
            counts = writer.write_trades(tdf, root)
            partitions_touched.update(counts.keys())
            trades_written += len(trades)

            # Update watermark: most recent trade wins.
            last = max(trades, key=lambda t: t.created_time)
            watermark.update_trades(
                state, m.ticker,
                last_trade_id=last.trade_id,
                last_trade_time=last.created_time,
                pulled_at=pulled_at,
            )
            # Save state periodically so a crash doesn't lose much progress.
            watermark.save(root, state)

    logger.info(
        "%s: endpoint split — %d events via /historical/*, %d via live",
        series_ticker, n_historical, n_live,
    )

    watermark.update_events_pulled(state, series_ticker, pulled_at)
    watermark.save(root, state)

    return BackfillResult(
        series_ticker=series_ticker,
        events_seen=len(events),
        markets_seen=markets_seen,
        tickers_with_trades=tickers_with_trades,
        trades_written=trades_written,
        trades_partitions_touched=len(partitions_touched),
        elapsed_seconds=time.monotonic() - start,
    )


def run_plan(
    client: KalshiClient, plan: BackfillPlan, root: Path
) -> list[BackfillResult]:
    """Execute a BackfillPlan end-to-end. Returns per-series results."""
    # Fetch cutoff once and share across all series in this run.
    cutoff = _parse_cutoff(client.fetch_historical_cutoff())
    logger.info("run_plan using historical cutoff: %s", cutoff.isoformat())

    results: list[BackfillResult] = []
    for series in plan.series_tickers:
        logger.info("starting backfill for series %s", series)
        r = backfill_series(
            client, series, root,
            status=plan.status,
            max_events=plan.max_events_per_series,
            close_before=plan.close_before,
            rate_limit_sleep_s=plan.rate_limit_sleep_s,
            skip_with_watermark=plan.skip_tickers_with_watermark,
            cutoff=cutoff,
        )
        logger.info(
            "%s done: %d events, %d markets, %d tickers with trades, "
            "%d trades in %.1fs",
            r.series_ticker, r.events_seen, r.markets_seen,
            r.tickers_with_trades, r.trades_written, r.elapsed_seconds,
        )
        results.append(r)
    return results
