"""CLI bundle for the Hyperliquid side of data pipeline M2.

Runs in sequence:
  1. Funding-rate history backfill for BTC / ETH / SOL (hourly ticks).
  2. 1m OHLCV for the same coins (adds to existing intervals under data/ohlcv/).

Both writers are idempotent and resumable — safe to re-run daily.

Usage:
    python scripts/backfill_hyperliquid.py
    python scripts/backfill_hyperliquid.py --coins BTC ETH --lookback-days 365
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from prospector.data.download import download_all as download_candles_all
from prospector.data.download_funding import download_funding_all

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_COINS = ["BTC", "ETH", "SOL"]
# 1m unblocks #4 Phase 1 re-run; hourly unblocks the vol-surface refit;
# daily is a cheap-to-keep reference.
M2_INTERVALS = ["1m", "1h", "1d"]
DEFAULT_LOOKBACK_DAYS = 730


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    parser.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help="Days of history on a fresh download (default: 730)",
    )
    parser.add_argument(
        "--intervals", nargs="+", default=M2_INTERVALS,
        help="OHLCV intervals (default: 1m 1h 1d)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    print("[1/2] funding-rate history...")
    download_funding_all(coins=args.coins, lookback_days=args.lookback_days)

    perp_coins = [f"{c}-PERP" for c in args.coins]
    print(f"[2/2] OHLCV candles ({', '.join(args.intervals)})...")
    download_candles_all(
        coins=perp_coins,
        intervals=args.intervals,
        lookback_days=args.lookback_days,
    )


if __name__ == "__main__":
    main()
