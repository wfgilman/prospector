"""Migrate TrevorJS HF dataset into our in-house partitioned schema.

Reads:
    data/kalshi_hf/markets-*.parquet
    data/kalshi_hf/trades-*.parquet

Writes (merged with any existing /historical/* pulls, deduped on trade_id):
    data/kalshi/markets/date=YYYY-MM-DD/part.parquet
    data/kalshi/trades/date=YYYY-MM-DD/part.parquet

Schema transformations:
    Trades
      yes_price / no_price:  int cents → float [0, 1]
      event_ticker:          not present in HF; joined from markets table
    Markets
      yes_bid/ask/no_bid/ask/last_price: cents → float [0, 1]
      series_ticker:         derived from event_ticker prefix
      pulled_at:             mapped from TrevorJS created_time
      expiration_time:       NULL (not in HF)
      category:              '' (not in HF)

After migration, downstream scripts can read a single parquet tree and
get unified coverage from the TrevorJS snapshot's start (Jun 2021)
through any /historical/* incremental pulls. The /historical/* pipeline
and TrevorJS agree byte-for-byte on overlapping ranges (validated
2026-04-23 cross-check), so the dedup just keeps the common rows once.

Not idempotent on the markets side: a second run will add a new
"pulled_at" per-ticker-per-day row in addition to any existing one.
Trades are fully idempotent via trade_id dedup.

Usage:
    python scripts/migrate_trevorjs.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from prospector.data.ingest.kalshi import writer

REPO_ROOT = Path(__file__).resolve().parent.parent
HF_DIR = REPO_ROOT / "data" / "kalshi_hf"
OUT_DIR = REPO_ROOT / "data" / "kalshi"

log = logging.getLogger(__name__)


def _series_ticker_expr(col: str) -> str:
    """SQL expression that derives series_ticker from event_ticker by
    taking the prefix before the first '-'. Mirrors the fallback in
    `_parse_market`."""
    return (
        f"CASE WHEN position('-' in {col}) > 0 "
        f"THEN substring({col}, 1, position('-' in {col}) - 1) "
        f"ELSE {col} END"
    )


def migrate_markets(con: duckdb.DuckDBPyConnection, dry_run: bool) -> dict:
    """Transform + write markets. Returns {'rows_read': N, 'dates': M}."""
    glob = str(HF_DIR / "markets-*.parquet")
    log.info("reading markets from %s", glob)
    start = time.monotonic()
    df = con.execute(f"""
        SELECT
            ticker,
            event_ticker,
            {_series_ticker_expr('event_ticker')} AS series_ticker,
            title,
            coalesce(yes_sub_title, '') AS yes_sub_title,
            coalesce(no_sub_title, '')  AS no_sub_title,
            status,
            coalesce(result, '') AS result,
            open_time,
            close_time,
            CAST(NULL AS TIMESTAMP WITH TIME ZONE) AS expiration_time,
            yes_bid / 100.0 AS yes_bid,
            yes_ask / 100.0 AS yes_ask,
            no_bid / 100.0 AS no_bid,
            no_ask / 100.0 AS no_ask,
            last_price / 100.0 AS last_price,
            coalesce(volume, 0)     AS volume,
            coalesce(volume_24h, 0) AS volume_24h,
            coalesce(open_interest, 0) AS open_interest,
            '' AS category,
            created_time AS pulled_at
        FROM read_parquet('{glob}')
    """).df()
    log.info("markets: %d rows read in %.1fs", len(df), time.monotonic() - start)

    if dry_run:
        log.info("dry-run: skipping markets write")
        return {"rows_read": len(df), "dates": df["pulled_at"].dt.date.nunique()}

    # Normalize tz-awareness then partition by pulled_at's UTC date.
    df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    for col in ("open_time", "close_time", "expiration_time"):
        df[col] = pd.to_datetime(df[col], utc=True)
    counts = writer.write_markets(df, OUT_DIR)
    log.info("markets written: %d date partitions, %d total rows",
             len(counts), sum(counts.values()))
    return {"rows_read": len(df), "dates": len(counts)}


def migrate_trades(
    con: duckdb.DuckDBPyConnection, dry_run: bool
) -> dict:
    """Transform + write trades. Done per-HF-file to bound memory —
    each file has ~10M rows. Event_ticker is joined from HF's markets
    parquets (also available in our partitioned markets after
    migrate_markets, but HF is the authoritative source in this run)."""
    trade_files = sorted(HF_DIR.glob("trades-*.parquet"))
    log.info("trades: %d HF files to migrate", len(trade_files))

    # Build ticker → event_ticker map from HF markets (one row per ticker).
    markets_glob = str(HF_DIR / "markets-*.parquet")
    log.info("building ticker → event_ticker map from HF markets...")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ticker_event_map AS
        SELECT DISTINCT ticker, event_ticker
        FROM read_parquet('{markets_glob}')
    """)
    n_map = con.execute("SELECT COUNT(*) FROM ticker_event_map").fetchone()[0]
    log.info("map built: %d tickers", n_map)

    total_written = 0
    total_partitions: set[str] = set()
    t0 = time.monotonic()

    for i, f in enumerate(trade_files, 1):
        file_start = time.monotonic()
        df = con.execute(f"""
            SELECT
                t.trade_id,
                t.ticker,
                coalesce(m.event_ticker, '') AS event_ticker,
                t.count,
                t.yes_price / 100.0 AS yes_price,
                t.no_price / 100.0  AS no_price,
                t.taker_side,
                t.created_time
            FROM read_parquet('{f}') t
            LEFT JOIN ticker_event_map m USING (ticker)
        """).df()
        n_rows = len(df)
        unmapped = int((df["event_ticker"] == "").sum())
        log.info(
            "[%d/%d] %s: %d trades, %d unmapped (%.1f%%), read in %.1fs",
            i, len(trade_files), f.name, n_rows, unmapped,
            100 * unmapped / max(n_rows, 1),
            time.monotonic() - file_start,
        )
        if dry_run:
            total_written += n_rows
            continue

        df["created_time"] = pd.to_datetime(df["created_time"], utc=True)
        counts = writer.write_trades(df, OUT_DIR)
        total_partitions.update(counts.keys())
        total_written += n_rows
        log.info(
            "[%d/%d] %s: wrote %d partitions (cumulative: %d partitions)",
            i, len(trade_files), f.name, len(counts), len(total_partitions),
        )

    log.info(
        "trades complete: %d total rows processed, %d partitions, %.1fs wall",
        total_written, len(total_partitions), time.monotonic() - t0,
    )
    return {"rows_read": total_written, "partitions": len(total_partitions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Read + transform but do not write. Prints row counts only.",
    )
    parser.add_argument(
        "--markets-only", action="store_true",
        help="Migrate markets only (skip trades — useful when only "
             "the schema extension needs to propagate).",
    )
    parser.add_argument(
        "--trades-only", action="store_true",
        help="Migrate trades only (skip markets).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    con = duckdb.connect()

    if not args.trades_only:
        r_m = migrate_markets(con, dry_run=args.dry_run)
        print(f"markets: {r_m}")

    if not args.markets_only:
        r_t = migrate_trades(con, dry_run=args.dry_run)
        print(f"trades:  {r_t}")


if __name__ == "__main__":
    main()
