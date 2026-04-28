"""Entry point for the elder triple-screen paper-trading daemon.

Runs `run_once` ticks against the locked vol_q4 cohort. Designed to be
invoked under launchd (one-shot per tick) or as a foreground loop.

Usage:
    # one-shot tick (recommended under launchd at the 4h boundary)
    python scripts/paper_trade_elder.py --once

    # foreground loop with 4h cadence
    python scripts/paper_trade_elder.py --interval 14400

    # custom cohort file / label
    python scripts/paper_trade_elder.py --once \\
        --cohorts-file /Users/.../data/cohorts/vol_q4.json --cohort vol_q4

The daemon refreshes Hyperliquid OHLCV at each tick, sweeps open
positions for stop/target hits, and opens new positions when the
locked triple-screen config fires on the just-printed bar.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from prospector.strategies.elder_triple_screen.portfolio import (
    PaperPortfolio,
    PortfolioConfig,
)
from prospector.strategies.elder_triple_screen.runner import (
    RunnerConfig,
    cohort_universe_from,
    run_forever,
    run_once,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORTFOLIO_DB = REPO_ROOT / "data" / "paper" / "elder_triple_screen" / "portfolio.db"
DEFAULT_COHORTS = REPO_ROOT / "data" / "cohorts" / "vol_quintiles_2026-04-28.json"
FALLBACK_COHORTS = Path("/tmp/cohorts.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Elder triple-screen paper daemon.")
    p.add_argument("--once", action="store_true", help="Run one tick and exit.")
    p.add_argument(
        "--interval", type=float, default=4 * 3600,
        help="Seconds between ticks in foreground mode (default: 4h)",
    )
    p.add_argument("--portfolio-db", type=Path, default=DEFAULT_PORTFOLIO_DB)
    p.add_argument("--initial-nav", type=float, default=10_000.0)
    p.add_argument("--risk-per-trade", type=float, default=0.02)
    p.add_argument("--max-position-frac", type=float, default=0.05)
    p.add_argument("--max-positions", type=int, default=10)
    p.add_argument(
        "--cohorts-file", type=Path, default=DEFAULT_COHORTS,
        help="Cohort universe JSON (falls back to /tmp/cohorts.json)",
    )
    p.add_argument("--cohort", type=str, default="vol_q4")
    p.add_argument(
        "--no-refresh", action="store_true",
        help="Skip the Hyperliquid OHLCV refresh (useful for tests)",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("paper_trade_elder")

    cohorts_file = args.cohorts_file
    if not cohorts_file.exists():
        if FALLBACK_COHORTS.exists():
            log.warning(
                "cohort file %s missing; falling back to %s",
                cohorts_file, FALLBACK_COHORTS,
            )
            cohorts_file = FALLBACK_COHORTS
        else:
            log.error("no cohort file found at %s or %s", cohorts_file, FALLBACK_COHORTS)
            return 2

    universe = cohort_universe_from(cohorts_file, args.cohort)
    log.info("cohort=%s |U|=%d", args.cohort, len(universe))

    portfolio = PaperPortfolio(
        db_path=args.portfolio_db,
        config=PortfolioConfig(
            initial_nav=args.initial_nav,
            risk_per_trade=args.risk_per_trade,
            max_position_frac=args.max_position_frac,
        ),
    )
    runner_cfg = RunnerConfig(
        universe=universe,
        refresh_data=not args.no_refresh,
        max_positions=args.max_positions,
    )

    if args.once:
        stats = run_once(portfolio, runner_cfg)
        log.info("once: %s", stats)
    else:
        run_forever(portfolio, runner_cfg, interval_seconds=args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
