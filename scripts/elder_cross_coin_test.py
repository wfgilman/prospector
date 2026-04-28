"""
Cross-coin generalization test for surviving cohort configs.

Given a (template, cohort) pair, takes the top-N walk-forward-surviving
configs and applies each one's parameters to every other coin in the
same cohort. Reports per-config how many cohort coins also score, and
walk-forward's per-coin retention.

This catches the case where the optimizer settles on a single coin's
idiosyncrasy while presenting as cohort-level edge.

Usage:
    python scripts/elder_cross_coin_test.py --template triple_screen --cohort vol_q3 --top 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from walk_forward_top_configs import (  # noqa: E402
    TopConfig,
    _run_config,
    load_top_configs,
)

DEFAULT_DB = REPO_ROOT / "data" / "prospector_bayesian.db"
DEFAULT_COHORTS = Path("/tmp/cohorts.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--template", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--cohorts-file", type=Path, default=DEFAULT_COHORTS,
    )
    args = parser.parse_args()

    console = Console()

    cohorts = json.loads(args.cohorts_file.read_text())
    cohort_coins = cohorts[args.cohort]
    console.print(
        f"[bold]cross-coin generalization[/bold]\n"
        f"  template={args.template} cohort={args.cohort} "
        f"|cohort|={len(cohort_coins)}\n"
    )

    configs = load_top_configs(args.db, args.top, template=args.template, cohort=args.cohort)
    if not configs:
        console.print("[red]no scored configs in this cell[/red]")
        return

    table = Table(
        title=f"Top {len(configs)} configs × {len(cohort_coins)} cohort coins",
        show_header=True, header_style="bold magenta",
    )
    table.add_column("rank")
    table.add_column("run_id", justify="right")
    table.add_column("tuned coin")
    table.add_column("in-sample", justify="right")
    table.add_column("coins scored", justify="right")
    table.add_column("coins consistent", justify="right")
    table.add_column("median retention", justify="right")
    table.add_column("max retention", justify="right")

    for rank, cfg in enumerate(configs, 1):
        original_coin = cfg.securities[0]
        n_scored_coins = 0
        n_consistent = 0
        retentions: list[float] = []
        for coin in cohort_coins:
            test_cfg = TopConfig(
                run_id=cfg.run_id,
                template=cfg.template,
                params=cfg.params,
                securities=[coin],
                in_sample_score=cfg.in_sample_score,
                n_trades=cfg.n_trades,
            )
            try:
                wf = _run_config(test_cfg, args.folds)
            except FileNotFoundError:
                continue
            except Exception:
                continue
            if not wf.per_security:
                continue
            sec = wf.per_security[0]
            if sec.in_sample_status != "scored" or sec.in_sample_score is None:
                continue
            n_scored_coins += 1
            n_folds_scored = sum(1 for st in sec.fold_statuses if st == "scored")
            # "Consistent" here means ≥ folds_pass AND ≥70% retention.
            # Using folds//2 + 1 + 1 = >= ceil(folds*0.8) for 5-fold → 4
            folds_pass = max(args.folds - 1, 1)  # 4 for 5-fold, 2 for 3-fold
            if sec.in_sample_score > 0 and sec.mean_scored is not None:
                ret = sec.mean_scored / sec.in_sample_score
                retentions.append(ret)
                if n_folds_scored >= folds_pass and ret >= 0.70:
                    n_consistent += 1
        if retentions:
            retentions.sort()
            med = retentions[len(retentions) // 2]
            mx = retentions[-1]
        else:
            med = mx = float("nan")

        table.add_row(
            str(rank),
            str(cfg.run_id),
            original_coin.replace("_PERP", ""),
            f"{cfg.in_sample_score:.1f}",
            f"{n_scored_coins}/{len(cohort_coins)}",
            f"{n_consistent}/{len(cohort_coins)}",
            f"{med:.0%}" if retentions else "-",
            f"{mx:.0%}" if retentions else "-",
        )

    console.print(table)


if __name__ == "__main__":
    main()
