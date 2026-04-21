"""Entry point for the paper-trading daemon.

Runs one or more `run_once` ticks wiring the Kalshi client, calibration
store, σ table, and paper portfolio together. Intended for invocation via
launchd or a simple `while true` shell wrapper during Phase 3.

Examples:
    # one-shot tick (recommended under launchd)
    python scripts/paper_trade.py --once

    # foreground loop
    python scripts/paper_trade.py --interval 900

    # override categories or minimum edge
    python scripts/paper_trade.py --once --categories sports --min-edge-pp 3.0

Sizing is equal-σ (risk-parity): each position's risk_budget is set so its
contribution to book σ equals `--book-sigma-target × NAV / √N_target`.
σ is looked up from `--sigma-table` by (category, side, 5¢ bin).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from prospector.kalshi import KalshiClient
from prospector.underwriting.calibration import CalibrationStore
from prospector.underwriting.portfolio import PaperPortfolio, PortfolioConfig
from prospector.underwriting.runner import RunnerConfig, run_forever, run_once
from prospector.underwriting.sizing import load_sigma_table

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALIBRATION_DIR = REPO_ROOT / "data" / "calibration" / "store"
DEFAULT_PORTFOLIO_DB = REPO_ROOT / "data" / "paper" / "portfolio.db"
DEFAULT_SIGMA_TABLE = REPO_ROOT / "data" / "calibration" / "sigma_table.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper-trading daemon for PM underwriting.")
    p.add_argument("--once", action="store_true", help="Run one tick and exit.")
    p.add_argument("--interval", type=float, default=900.0, help="Seconds between ticks.")
    p.add_argument("--calibration-dir", type=Path, default=DEFAULT_CALIBRATION_DIR)
    p.add_argument("--sigma-table", type=Path, default=DEFAULT_SIGMA_TABLE)
    p.add_argument("--portfolio-db", type=Path, default=DEFAULT_PORTFOLIO_DB)
    p.add_argument("--initial-nav", type=float, default=10_000.0)
    p.add_argument("--book-sigma-target", type=float, default=0.02)
    p.add_argument("--n-target", type=int, default=150)
    p.add_argument("--max-trades-per-day", type=int, default=20)
    p.add_argument("--max-position-frac", type=float, default=0.01)
    p.add_argument("--max-event-frac", type=float, default=0.05)
    p.add_argument("--max-bin-frac", type=float, default=0.15)
    p.add_argument("--min-edge-pp", type=float, default=5.0)
    p.add_argument(
        "--categories",
        nargs="*",
        default=["sports", "crypto"],
        help='Filter to these categories. Pass "all" to disable filtering.',
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    store = CalibrationStore(args.calibration_dir)
    calibration = store.load_current()
    sigma_table = load_sigma_table(args.sigma_table)

    categories = None if args.categories == ["all"] else tuple(args.categories)
    runner_cfg = RunnerConfig(
        min_edge_pp=args.min_edge_pp,
        categories=categories,
    )
    portfolio_cfg = PortfolioConfig(
        initial_nav=args.initial_nav,
        book_sigma_target=args.book_sigma_target,
        n_target=args.n_target,
        max_position_frac=args.max_position_frac,
        max_event_frac=args.max_event_frac,
        max_bin_frac=args.max_bin_frac,
        max_trades_per_day=args.max_trades_per_day,
    )

    with KalshiClient() as client, PaperPortfolio(args.portfolio_db, portfolio_cfg) as portfolio:
        if args.once:
            report = run_once(client, portfolio, calibration, sigma_table, runner_cfg)
            print(
                f"entered={report.entered} rejected={report.rejected} "
                f"candidates={report.candidates_seen} "
                f"resolved={report.monitor.resolved} voided={report.monitor.voided}"
            )
        else:
            run_forever(
                client,
                portfolio,
                calibration,
                sigma_table,
                runner_cfg,
                interval_seconds=args.interval,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
