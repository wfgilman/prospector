"""Reconstruct Kalshi BTC-intraday strike ladder as a time series.

Week-1 spike for strategy #10 (Kalshi × Hyperliquid implied-distribution arb).
Hyperparameters are locked per deep-dive §5.0 — do not expose as CLI flags.

Output: parquet at `data/vol_surface/kalshi_ladder.parquet` keyed by
    (event_ticker, snapshot_ts, strike_mid) -> yes_mid_raw, yes_mid_renorm,
    bucket_lower, bucket_upper, trades_in_event.

The `yes_mid_renorm` column is the primary p_i input: raw yes_prices per
B-type bucket, re-normalized so the ladder sums to 1.0 per snapshot.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# --- Pre-registered hyperparameters (see §5.0) ---------------------------------
DATE_START = "2025-09-17"
DATE_END = "2026-04-22"
CONTRACT_PREFIX = "KXBTC-"
CONTRACT_TYPE = "B"                # B-type (range bucket) only; T-types deferred
SNAPSHOT_CADENCE_MIN = 15
MIN_TRADES_PER_EVENT = 500
# --------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
HF_DIR = REPO_ROOT / "data" / "kalshi_hf"
OUT_DIR = REPO_ROOT / "data" / "vol_surface"
OUT_PATH = OUT_DIR / "kalshi_ladder.parquet"

# Regex to extract bucket bounds from yes_sub_title like "$84,250 to 84,749.99".
# Group 1 = lower bound, group 2 = upper bound. Parsed in DuckDB SQL via regexp.
BUCKET_RE_SQL = r'\$([\d,]+(?:\.\d+)?)\s*to\s*([\d,]+(?:\.\d+)?)'


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    markets_glob = str(HF_DIR / "markets-*.parquet")
    trades_glob = str(HF_DIR / "trades-*.parquet")

    con = duckdb.connect()

    print("[1/4] filtering markets to BTC intraday B-type in date window...")
    con.execute(f"""
        CREATE TEMP TABLE events AS
        WITH parsed AS (
            SELECT
                ticker,
                event_ticker,
                yes_sub_title,
                open_time,
                close_time,
                regexp_extract(yes_sub_title, '{BUCKET_RE_SQL}', 1) AS lo_str,
                regexp_extract(yes_sub_title, '{BUCKET_RE_SQL}', 2) AS hi_str
            FROM read_parquet('{markets_glob}')
            WHERE event_ticker LIKE '{CONTRACT_PREFIX}%'
              AND ticker LIKE '%-{CONTRACT_TYPE}%'
              AND status = 'finalized'
              AND close_time >= TIMESTAMP '{DATE_START}'
              AND close_time <= TIMESTAMP '{DATE_END}'
        )
        SELECT
            ticker,
            event_ticker,
            yes_sub_title,
            open_time,
            close_time,
            CAST(replace(lo_str, ',', '') AS DOUBLE) AS bucket_lower,
            CAST(replace(hi_str, ',', '') AS DOUBLE) AS bucket_upper,
            (CAST(replace(lo_str, ',', '') AS DOUBLE)
             + CAST(replace(hi_str, ',', '') AS DOUBLE)) / 2.0 AS strike_mid
        FROM parsed
        WHERE lo_str <> '' AND hi_str <> ''
    """)
    n_events = con.execute(
        "SELECT COUNT(DISTINCT event_ticker) FROM events"
    ).fetchone()[0]
    n_tickers = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"      {n_events} events, {n_tickers} B-type tickers in window")

    print("[2/4] counting trades per event to apply min_trades filter...")
    con.execute(f"""
        CREATE TEMP TABLE trade_counts AS
        SELECT e.event_ticker, COUNT(*) AS n_trades
        FROM events e
        JOIN read_parquet('{trades_glob}') t ON t.ticker = e.ticker
        GROUP BY e.event_ticker
    """)
    con.execute(f"""
        CREATE TEMP TABLE live_events AS
        SELECT event_ticker FROM trade_counts
        WHERE n_trades >= {MIN_TRADES_PER_EVENT}
    """)
    n_live = con.execute("SELECT COUNT(*) FROM live_events").fetchone()[0]
    print(f"      {n_live} events pass min_trades={MIN_TRADES_PER_EVENT}")

    print("[3/4] generating snapshot grid and ASOF-joining last trade price...")
    # Build (event_ticker, ticker, snapshot_ts) grid, then ASOF-join the most
    # recent trade yes_price at or before snapshot_ts per ticker.
    con.execute(f"""
        CREATE TEMP TABLE snapshots AS
        SELECT
            e.event_ticker,
            e.ticker,
            e.bucket_lower,
            e.bucket_upper,
            e.strike_mid,
            e.open_time,
            e.close_time,
            gs AS snapshot_ts
        FROM events e
        JOIN live_events le USING (event_ticker)
        CROSS JOIN LATERAL (
            SELECT unnest(
                generate_series(
                    date_trunc('hour', e.open_time)
                        + INTERVAL '{SNAPSHOT_CADENCE_MIN}' MINUTE
                            * ceil(date_part('minute', e.open_time) / {SNAPSHOT_CADENCE_MIN}.0),
                    e.close_time,
                    INTERVAL '{SNAPSHOT_CADENCE_MIN}' MINUTE
                )
            ) AS gs
        )
    """)

    con.execute(f"""
        CREATE TEMP TABLE trades_btc AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM read_parquet('{trades_glob}') t
        JOIN (SELECT DISTINCT ticker FROM events) e USING (ticker)
    """)

    con.execute("""
        CREATE TEMP TABLE ladder_raw AS
        SELECT
            s.event_ticker,
            s.snapshot_ts,
            s.ticker,
            s.bucket_lower,
            s.bucket_upper,
            s.strike_mid,
            t.yes_price
        FROM snapshots s
        ASOF LEFT JOIN trades_btc t
            ON s.ticker = t.ticker
           AND s.snapshot_ts >= t.created_time
    """)

    dropped = con.execute("""
        SELECT COUNT(*) FROM ladder_raw WHERE yes_price IS NULL
    """).fetchone()[0]
    print(f"      ASOF join produced {dropped} rows with no prior trade (dropped)")

    print("[4/4] renormalizing per snapshot and writing parquet...")
    con.execute(f"""
        COPY (
            WITH clean AS (
                SELECT
                    event_ticker,
                    snapshot_ts,
                    ticker,
                    bucket_lower,
                    bucket_upper,
                    strike_mid,
                    yes_price / 100.0 AS p_raw
                FROM ladder_raw
                WHERE yes_price IS NOT NULL
            ),
            snap_sums AS (
                SELECT
                    event_ticker,
                    snapshot_ts,
                    SUM(p_raw) AS sum_p,
                    COUNT(*) AS n_strikes_in_snap
                FROM clean
                GROUP BY event_ticker, snapshot_ts
            ),
            event_max AS (
                SELECT event_ticker, MAX(n_strikes_in_snap) AS max_strikes_in_event
                FROM snap_sums
                GROUP BY event_ticker
            )
            SELECT
                c.event_ticker,
                c.snapshot_ts,
                c.ticker,
                c.bucket_lower,
                c.bucket_upper,
                c.strike_mid,
                c.p_raw AS yes_mid_raw,
                CASE WHEN s.sum_p > 0 THEN c.p_raw / s.sum_p ELSE NULL END
                    AS yes_mid_renorm,
                s.sum_p AS snapshot_sum_raw,
                s.n_strikes_in_snap,
                em.max_strikes_in_event,
                s.n_strikes_in_snap::DOUBLE / em.max_strikes_in_event
                    AS ladder_completeness
            FROM clean c
            JOIN snap_sums s USING (event_ticker, snapshot_ts)
            JOIN event_max em USING (event_ticker)
            WHERE s.sum_p > 0
            ORDER BY event_ticker, snapshot_ts, strike_mid
        ) TO '{OUT_PATH}' (FORMAT 'parquet')
    """)

    n_rows = con.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT event_ticker),
               COUNT(DISTINCT (event_ticker, snapshot_ts))
        FROM read_parquet('{OUT_PATH}')
    """).fetchone()
    print(
        f"\nwrote {OUT_PATH}\n"
        f"  rows: {n_rows[0]:,}\n"
        f"  events: {n_rows[1]:,}\n"
        f"  unique (event, snapshot) pairs: {n_rows[2]:,}"
    )


if __name__ == "__main__":
    main()
