"""
Run elder_bayesian_search across volatility cohorts.

Reads `/tmp/cohorts.json` produced by `coin_universe_profile.py`, then
for each (template, cohort) combination runs a Bayesian search at the
locked hyperparameters with the cohort's coin list as the security
axis. All results land in a single SQLite DB, with the cohort label
persisted in `config_json["cohort"]`.

Usage:
    python scripts/elder_cohort_search.py --reset
    python scripts/elder_cohort_search.py --templates triple_screen impulse_system
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rich.console import Console

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from elder_bayesian_search import (  # noqa: E402
    _AXIS_BUILDERS,
    init_db,
    run_search,
)

DEFAULT_DB = REPO_ROOT / "data" / "prospector_bayesian.db"
DEFAULT_COHORTS = Path("/tmp/cohorts.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cohorts-file", type=Path, default=DEFAULT_COHORTS)
    parser.add_argument(
        "--templates", nargs="+", default=list(_AXIS_BUILDERS.keys()),
        help="Templates to run (default: all 6)",
    )
    parser.add_argument(
        "--cohorts", nargs="+", default=None,
        help="Cohort labels to run (default: all in cohorts.json)",
    )
    parser.add_argument("--n-init", type=int, default=20)
    parser.add_argument("--n-total", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    console = Console()

    cohorts_data: dict[str, list[str]] = json.loads(args.cohorts_file.read_text())
    cohort_names = args.cohorts if args.cohorts else list(cohorts_data.keys())

    if args.reset and args.db.exists():
        console.print(f"[yellow]resetting[/yellow] {args.db}")
        args.db.unlink()
    init_db(args.db)

    grand_total = len(args.templates) * len(cohort_names)
    grand_count = 0
    grand_started = time.time()

    for cohort in cohort_names:
        if cohort not in cohorts_data:
            console.print(f"[red]cohort missing in file: {cohort}[/red]")
            continue
        coins = cohorts_data[cohort]
        for template in args.templates:
            grand_count += 1
            console.print(
                f"\n[bold]── grand {grand_count}/{grand_total} "
                f"({(time.time() - grand_started) / 60:.1f} min elapsed) ──[/bold]"
            )
            run_search(
                template=template,
                db_path=args.db,
                n_init=args.n_init,
                n_total=args.n_total,
                seed=args.seed,
                console=console,
                securities=coins,
                label=cohort,
            )

    console.print(
        f"\n[green]all done[/green] — total elapsed: "
        f"{(time.time() - grand_started) / 60:.1f} min"
    )


if __name__ == "__main__":
    main()
