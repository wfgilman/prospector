"""CLI entry point for Kalshi incremental pull (cron-friendly).

Runs a bounded-duration pull: refreshes events for the configured series,
appends new trades for tickers we've already watermarked, and snapshots
current open markets. Unknown tickers are *not* backfilled here; use
`scripts/backfill_kalshi.py` for initial pulls.

Usage:
    python scripts/pull_kalshi_incremental.py \
        --series KXBTC KXETH KXMVENFL FED KXFED \
        [--output data/kalshi]

Requires the same env vars as the backfill script.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from prospector.data.ingest.kalshi.incremental import pull_incremental
from prospector.kalshi.client import KalshiClient

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "kalshi"
DEFAULT_SERIES = [
    "KXBTC", "KXBTCD", "KXETH", "KXETHD",
    "KXMVENFL", "KXMVENBA", "KXMVESPORTS",
    "FED", "KXFED", "KXFEDDECISION",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", nargs="+", default=DEFAULT_SERIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--rate-limit-sleep", type=float, default=0.3,
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    args.output.mkdir(parents=True, exist_ok=True)
    with KalshiClient() as client:
        summary = pull_incremental(
            client, args.series, args.output,
            rate_limit_sleep_s=args.rate_limit_sleep,
        )

    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
