"""Partitioned parquet writers for Kalshi trades and markets.

Storage layout (all under `data/kalshi/`, UTC dates):
    trades/date=YYYY-MM-DD/part.parquet
    markets/date=YYYY-MM-DD/part.parquet
    events/date=YYYY-MM-DD/part.parquet

Idempotency:
    - Trades dedupe on `trade_id`. Re-running the same pull produces the same
      output regardless of ordering.
    - Markets dedupe on `(ticker, pulled_at_date)` so a second pull the same
      day for the same ticker replaces the earlier record. Across days we
      keep one row per ticker per day — gives a historical audit of every
      field (status, yes_bid, etc.) as it evolved.
    - Events dedupe on `(event_ticker, pulled_at_date)` for the same reason.

Atomic write:
    - Write to `<target>.tmp` in the same directory, then `os.rename` onto
      the final path. Consumers never see a half-written file.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from prospector.kalshi.models import Market, Trade

TRADES_SUBDIR = "trades"
MARKETS_SUBDIR = "markets"
EVENTS_SUBDIR = "events"


def _partition_dir(root: Path, subdir: str, date: str) -> Path:
    return root / subdir / f"date={date}"


def _partition_path(root: Path, subdir: str, date: str) -> Path:
    return _partition_dir(root, subdir, date) / "part.parquet"


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def trades_to_frame(trades: Iterable[Trade], ticker_to_event: dict[str, str]) -> pd.DataFrame:
    """Normalize a stream of Trade dataclasses into a canonical DataFrame.

    `ticker_to_event` maps Kalshi ticker -> event_ticker. Trades from the
    API carry only `ticker`, not `event_ticker`; the ingest driver passes in
    the mapping derived from the market pull. If a ticker is unknown, the
    event_ticker column is filled with an empty string (caller decides
    whether that's an error)."""
    rows = []
    for t in trades:
        row = asdict(t)
        row["event_ticker"] = ticker_to_event.get(t.ticker, "")
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "trade_id", "ticker", "event_ticker", "count",
                "yes_price", "no_price", "taker_side", "created_time",
            ]
        )
    df["created_time"] = pd.to_datetime(df["created_time"], utc=True)
    df = df[[
        "trade_id", "ticker", "event_ticker", "count",
        "yes_price", "no_price", "taker_side", "created_time",
    ]]
    return df


def write_trades(df: pd.DataFrame, root: Path) -> dict[str, int]:
    """Write a canonical trades frame into date-partitioned parquet.

    For each partition present in `df`, merges with the existing partition
    on `trade_id` (deduped) and atomically replaces. Returns a dict mapping
    YYYY-MM-DD -> final row count per partition."""
    if df.empty:
        return {}
    df = df.copy()
    df["date"] = df["created_time"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    counts: dict[str, int] = {}
    for date, group in df.groupby("date"):
        path = _partition_path(root, TRADES_SUBDIR, date)
        existing = pd.read_parquet(path) if path.exists() else None
        merged = group.drop(columns="date")
        if existing is not None and not existing.empty:
            merged = pd.concat([existing, merged], ignore_index=True)
        merged = merged.drop_duplicates(subset="trade_id").sort_values(
            ["created_time", "trade_id"]
        ).reset_index(drop=True)
        _atomic_write_parquet(merged, path)
        counts[date] = len(merged)
    return counts


def markets_to_frame(markets: Iterable[Market], pulled_at: datetime) -> pd.DataFrame:
    """Normalize Market dataclasses into a canonical DataFrame with a
    `pulled_at` timestamp marking when the snapshot was taken."""
    if pulled_at.tzinfo is None:
        pulled_at = pulled_at.replace(tzinfo=timezone.utc)
    rows = []
    for m in markets:
        rows.append({
            "ticker": m.ticker,
            "event_ticker": m.event_ticker,
            "series_ticker": m.series_ticker,
            "title": m.title,
            "status": m.status,
            "result": m.result,
            "open_time": m.open_time,
            "close_time": m.close_time,
            "expiration_time": m.expiration_time,
            "yes_bid": m.yes_bid,
            "yes_ask": m.yes_ask,
            "no_bid": m.no_bid,
            "no_ask": m.no_ask,
            "last_price": m.last_price,
            "volume": m.volume,
            "open_interest": m.open_interest,
            "category": m.category,
            "pulled_at": pulled_at,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("open_time", "close_time", "expiration_time", "pulled_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def write_markets(df: pd.DataFrame, root: Path) -> dict[str, int]:
    """Write markets snapshot into date-partitioned parquet, keyed by
    `pulled_at` date. Deduped on (ticker, date) so a second pull within the
    same day replaces the earlier snapshot."""
    if df.empty:
        return {}
    df = df.copy()
    df["date"] = df["pulled_at"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    counts: dict[str, int] = {}
    for date, group in df.groupby("date"):
        path = _partition_path(root, MARKETS_SUBDIR, date)
        existing = pd.read_parquet(path) if path.exists() else None
        merged = group.drop(columns="date")
        if existing is not None and not existing.empty:
            merged = pd.concat([existing, merged], ignore_index=True)
        # Keep latest row per ticker within the day.
        merged = merged.sort_values("pulled_at").drop_duplicates(
            subset="ticker", keep="last"
        ).reset_index(drop=True)
        _atomic_write_parquet(merged, path)
        counts[date] = len(merged)
    return counts


def write_events(events: Iterable[dict], root: Path, pulled_at: datetime) -> dict[str, int]:
    """Write the raw event metadata (returned as dicts from /events). We
    retain the full dict for schema flexibility — Kalshi adds event-level
    fields periodically and we don't want to drop data.

    Stored as parquet with one JSON-serialized `raw` column plus the most
    useful fields extracted."""
    if pulled_at.tzinfo is None:
        pulled_at = pulled_at.replace(tzinfo=timezone.utc)
    import json
    rows = []
    for ev in events:
        rows.append({
            "event_ticker": ev.get("event_ticker", ""),
            "series_ticker": ev.get("series_ticker", ""),
            "title": ev.get("title", "") or ev.get("sub_title", ""),
            "category": ev.get("category", ""),
            "status": ev.get("status", ""),
            "pulled_at": pulled_at,
            "raw_json": json.dumps(ev, default=str),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    date = pulled_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    path = _partition_path(root, EVENTS_SUBDIR, date)
    existing = pd.read_parquet(path) if path.exists() else None
    merged = df
    if existing is not None and not existing.empty:
        merged = pd.concat([existing, merged], ignore_index=True)
    merged = merged.sort_values("pulled_at").drop_duplicates(
        subset="event_ticker", keep="last"
    ).reset_index(drop=True)
    _atomic_write_parquet(merged, path)
    return {date: len(merged)}
