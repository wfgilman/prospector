"""Build and persist a calibration snapshot to the on-disk store.

Rebuilds per-category PIT calibration from the HuggingFace Kalshi dataset
and writes a JSON snapshot to `data/calibration/store/`. The paper-trading
runner loads from this store at startup.

Usage:
    python scripts/refresh_calibration_store.py
    python scripts/refresh_calibration_store.py --min-volume 25
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from prospector.underwriting.calibration import (
    CalibrationStore,
    build_calibration_from_duckdb,
)
from prospector.underwriting.categorize import category_sql

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "kalshi_hf"
DEFAULT_STORE_DIR = REPO_ROOT / "data" / "calibration" / "store"


def build_pit_tables(
    con: duckdb.DuckDBPyConnection,
    data_dir: Path,
    min_volume: int,
) -> tuple[str, str]:
    """Populate `pit_final` and return (window_start, window_end) ISO dates."""
    con.execute(
        f"""
        CREATE OR REPLACE TABLE markets AS
        SELECT
            ticker,
            event_ticker,
            result,
            volume,
            open_time,
            close_time,
            open_time + (close_time - open_time) / 2 AS pit_time,
            {category_sql()} AS category
        FROM '{data_dir}/markets-*.parquet'
        WHERE result IN ('yes', 'no')
          AND volume >= {min_volume}
          AND close_time > open_time
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM '{data_dir}/trades-*.parquet' t
        SEMI JOIN markets m ON t.ticker = m.ticker
        ORDER BY t.ticker, t.created_time
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE pit_prices AS
        SELECT m.ticker, m.event_ticker, m.result, m.volume,
               m.pit_time, m.category,
               t.yes_price AS pit_price,
               t.created_time AS trade_time
        FROM markets m
        ASOF JOIN trades t
            ON m.ticker = t.ticker
           AND m.pit_time >= t.created_time
        """
    )
    # Fallback for markets with no pre-PIT trade
    con.execute(
        """
        UPDATE pit_prices
        SET pit_price = t.yes_price, trade_time = t.created_time
        FROM (
            SELECT m.ticker, MIN(t.created_time) AS first_after
            FROM markets m
            JOIN trades t ON m.ticker = t.ticker AND t.created_time > m.pit_time
            WHERE m.ticker IN (SELECT ticker FROM pit_prices WHERE pit_price IS NULL)
            GROUP BY m.ticker
        ) pp
        JOIN trades t ON pp.ticker = t.ticker AND pp.first_after = t.created_time
        WHERE pit_prices.ticker = pp.ticker
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE pit_final AS
        SELECT p.*,
               m.open_time,
               m.close_time,
               ABS(EXTRACT(EPOCH FROM (p.trade_time - p.pit_time)))
                   / NULLIF(EXTRACT(EPOCH FROM (m.close_time - m.open_time)), 0) AS time_offset_frac
        FROM pit_prices p
        JOIN markets m ON p.ticker = m.ticker
        WHERE p.pit_price IS NOT NULL
          AND ABS(EXTRACT(EPOCH FROM (p.trade_time - p.pit_time)))
               / NULLIF(EXTRACT(EPOCH FROM (m.close_time - m.open_time)), 0) <= 0.25
        """
    )
    bounds = con.execute(
        "SELECT MIN(close_time)::DATE, MAX(close_time)::DATE FROM pit_final"
    ).fetchone()
    return (str(bounds[0]), str(bounds[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh calibration snapshot.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--store-dir", type=Path, default=DEFAULT_STORE_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    args = parser.parse_args()

    if not (args.data_dir / "markets-0000.parquet").exists():
        raise FileNotFoundError(f"Markets parquet not found in {args.data_dir}")
    if not (args.data_dir / "trades-0000.parquet").exists():
        raise FileNotFoundError(f"Trades parquet not found in {args.data_dir}")

    con = duckdb.connect()
    print("Building PIT tables...")
    window_start, window_end = build_pit_tables(con, args.data_dir, args.min_volume)

    print(f"Aggregating calibration over {window_start} -> {window_end}")
    calibration = build_calibration_from_duckdb(
        con,
        data_window_start=window_start,
        data_window_end=window_end,
        min_volume=args.min_volume,
        built_at=datetime.now(timezone.utc),
    )
    store = CalibrationStore(args.store_dir)
    path = store.save(calibration)
    print(f"Saved calibration to {path}")

    for cat, bins in calibration.curves.items():
        tradeable = [b for b in bins if b.side]
        print(
            f"  {cat:10s}: {len(bins):2d} bins, {len(tradeable)} tradeable "
            f"(total n={sum(b.n for b in bins):,})"
        )

    con.close()


if __name__ == "__main__":
    main()
