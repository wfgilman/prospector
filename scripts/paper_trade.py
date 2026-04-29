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
from prospector.strategies.pm_underwriting.calibration import CalibrationStore
from prospector.strategies.pm_underwriting.portfolio import PaperPortfolio, PortfolioConfig
from prospector.strategies.pm_underwriting.runner import RunnerConfig, run_forever, run_once
from prospector.strategies.pm_underwriting.sizing import load_sigma_table

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALIBRATION_DIR = REPO_ROOT / "data" / "calibration" / "store"
DEFAULT_PORTFOLIO_DB = REPO_ROOT / "data" / "paper" / "pm_underwriting" / "portfolio.db"
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
        "--min-frac-of-life",
        type=float,
        default=0.25,
        help=(
            "Reject markets where (now - open_time)/(close_time - open_time) "
            "is below this fraction. The calibration is fit on PIT prices "
            "at frac=0.5 with a 25%%-of-life offset window, and the "
            "longshot bias plateaus in [0.25, 0.55] before decaying. "
            "Set to 0 to disable."
        ),
    )
    p.add_argument(
        "--max-frac-of-life",
        type=float,
        default=0.55,
        help=(
            "Reject markets past this fraction of life. Past 0.55, prices "
            "rapidly converge to the resolved outcome (information "
            "aggregation), eroding the calibration's claimed edge. "
            "Set to 1 to disable."
        ),
    )
    p.add_argument(
        "--categories",
        nargs="*",
        default=None,
        help=(
            'Filter to these categories (e.g. "sports crypto"). Default '
            'is to scan all categories — the frac-of-life gate handles '
            'correctness; non-tradeable categories drop out via the '
            'edge floor naturally. Pass "all" or omit for all categories.'
        ),
    )
    p.add_argument(
        "--entry-price-min",
        type=float,
        default=0.0,
        help=(
            "Lower bound on entry price (inclusive). Defaults to 0.0 = no "
            "filter (lottery book). Set to e.g. 0.55 for the insurance book "
            "to scope to favorites at moderate prices."
        ),
    )
    p.add_argument(
        "--entry-price-max",
        type=float,
        default=1.0,
        help=(
            "Upper bound on entry price (inclusive). Defaults to 1.0 = no "
            "filter. Set to e.g. 0.75 for the insurance book."
        ),
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

    if args.categories is None or args.categories == ["all"]:
        categories = None
    else:
        categories = tuple(args.categories)
    # Shadow ledger lives next to the portfolio DB (parent of DB file).
    shadow_root = args.portfolio_db.parent
    runner_cfg = RunnerConfig(
        min_edge_pp=args.min_edge_pp,
        categories=categories,
        min_frac_of_life=args.min_frac_of_life or None,
        max_frac_of_life=(
            args.max_frac_of_life if args.max_frac_of_life < 1 else None
        ),
        shadow_ledger_root=shadow_root,
        entry_price_min=args.entry_price_min,
        entry_price_max=args.entry_price_max,
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
                f"shadow={report.shadow_rejected} "
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
