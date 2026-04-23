"""CLI entry point for Kalshi historical backfill (M1).

Usage:
    python scripts/backfill_kalshi.py \
        --series KXBTC KXETH KXMVENFL FED KXFED \
        [--max-events 5]               # pilot mode: 5 events per series
        [--output data/kalshi]         # default
        [--no-skip]                    # ignore watermarks, force re-pull

Requires env vars:
    KALSHI_API_KEY_ID
    KALSHI_PRIVATE_KEY_PATH (or KALSHI_PRIVATE_KEY_PEM)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

from prospector.data.ingest.kalshi.backfill import BackfillPlan, run_plan
from prospector.kalshi.client import KalshiClient

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "kalshi"

load_dotenv(REPO_ROOT / ".env")

# Series for PM underwriting + the two R&D tracks (#10 vol surface, #4 Fed).
# Not exhaustive; user can override via --series.
DEFAULT_SERIES = [
    # Crypto range/threshold contracts (#10 + PM crypto longshots)
    "KXBTC", "KXBTCD", "KXETH", "KXETHD",
    # PM dominant series — sports parlays, NFL, NBA
    "KXMVENFL", "KXMVENBA", "KXMVESPORTS",
    # Fed rate contracts (#4 narrative spread)
    "FED", "KXFED", "KXFEDDECISION",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--series", nargs="+", default=DEFAULT_SERIES,
        help="Series tickers to backfill",
    )
    parser.add_argument(
        "--max-events", type=int, default=None,
        help="Cap events per series (pilot mode)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Output root directory (default: data/kalshi/)",
    )
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Re-pull tickers that already have a watermark",
    )
    parser.add_argument(
        "--status", default="settled,closed",
        help="Event status filter (default: settled,closed)",
    )
    parser.add_argument(
        "--rate-limit-sleep", type=float, default=0.3,
        help="Seconds to sleep between API calls (default: 0.3)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable INFO logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    plan = BackfillPlan(
        series_tickers=args.series,
        status=args.status,
        max_events_per_series=args.max_events,
        rate_limit_sleep_s=args.rate_limit_sleep,
        skip_tickers_with_watermark=not args.no_skip,
    )

    args.output.mkdir(parents=True, exist_ok=True)
    with KalshiClient() as client:
        results = run_plan(client, plan, args.output)

    # Print a summary table.
    print(
        f"\n{'series':<16}{'events':>8}{'markets':>10}"
        f"{'tickers_w_trades':>20}{'trades':>10}{'partitions':>12}"
        f"{'elapsed_s':>12}"
    )
    print("-" * 88)
    for r in results:
        print(
            f"{r.series_ticker:<16}{r.events_seen:>8}{r.markets_seen:>10}"
            f"{r.tickers_with_trades:>20}{r.trades_written:>10}"
            f"{r.trades_partitions_touched:>12}{r.elapsed_seconds:>12.1f}"
        )


if __name__ == "__main__":
    main()
