"""
Aggregate per-(template, cohort) results from a Bayesian-search DB.

For each (template, cohort) cell:
    - search-side: max_score, scored_rate, top-10 mean
    - walk-forward (top-10 per cell): n configs surviving with
        ≥ folds_pass scored folds AND ≥ retention_pct retention
    - "passes criterion 2" boolean per cell
    - representative best config (in-sample peak + best holdout retention)

Default thresholds match docs/rd/candidates/15-…:
    folds_pass = 4 of 5  (or 3 of 3 in 3-fold mode)
    retention_pct = 0.70

Usage:
    python scripts/elder_cohort_report.py
    python scripts/elder_cohort_report.py --folds 3 --folds-pass 3
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from walk_forward_top_configs import (  # noqa: E402
    _run_config,
    load_top_configs,
)

DEFAULT_DB = REPO_ROOT / "data" / "prospector_bayesian.db"


@dataclass
class CellResult:
    template: str
    cohort: str
    n_total: int
    n_scored: int
    max_score: float | None
    top10_mean: float | None
    n_walk_forward: int           # configs walk-forwarded (top-10 or fewer if fewer scored)
    n_survived: int               # configs hitting both folds_pass AND retention_pct
    best_retention: float | None  # best (best_sec_mean / in_sample_score) across the cell
    best_run_id: int | None
    best_config_summary: str | None


def _cell_stats(
    db_path: Path, template: str, cohort: str,
) -> tuple[int, int, float | None, float | None]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT score, backtest_status FROM runs "
        "WHERE template = ? AND json_extract(config_json, '$.cohort') = ?",
        (template, cohort),
    ).fetchall()
    con.close()
    n_total = len(rows)
    scored = [s for s, st in rows if st == "scored" and s is not None]
    if not scored:
        return n_total, 0, None, None
    scored.sort(reverse=True)
    return (
        n_total,
        len(scored),
        float(scored[0]),
        sum(scored[:10]) / min(10, len(scored)),
    )


def evaluate_cell(
    db_path: Path,
    template: str,
    cohort: str,
    top_n: int,
    folds: int,
    folds_pass: int,
    retention_pct: float,
) -> CellResult:
    n_total, n_scored, max_score, top10_mean = _cell_stats(db_path, template, cohort)
    if n_scored == 0:
        return CellResult(
            template=template, cohort=cohort,
            n_total=n_total, n_scored=0,
            max_score=None, top10_mean=None,
            n_walk_forward=0, n_survived=0,
            best_retention=None, best_run_id=None, best_config_summary=None,
        )

    configs = load_top_configs(db_path, top_n, template=template, cohort=cohort)
    n_survived = 0
    best_retention: float | None = None
    best_run_id: int | None = None
    best_config_summary: str | None = None

    for cfg in configs:
        try:
            r = _run_config(cfg, folds)
        except Exception:
            continue
        # best-security-holdout retention = mean across that security's scored folds
        # divided by in-sample score
        for sec in r.per_security:
            if sec.mean_scored is None or sec.in_sample_score is None or sec.in_sample_score <= 0:
                continue
            n_scored_folds = sum(1 for st in sec.fold_statuses if st == "scored")
            retention = sec.mean_scored / sec.in_sample_score
            survives = (n_scored_folds >= folds_pass and retention >= retention_pct)
            if survives:
                n_survived += 1
            if best_retention is None or retention > best_retention:
                best_retention = retention
                best_run_id = cfg.run_id
                best_config_summary = (
                    f"#{cfg.run_id} {cfg.template} {sec.security} "
                    f"in-sample={sec.in_sample_score:.1f} "
                    f"holdout={sec.mean_scored:.1f} "
                    f"folds={n_scored_folds}/{folds}"
                )
            break

    return CellResult(
        template=template, cohort=cohort,
        n_total=n_total, n_scored=n_scored,
        max_score=max_score, top10_mean=top10_mean,
        n_walk_forward=len(configs), n_survived=n_survived,
        best_retention=best_retention,
        best_run_id=best_run_id,
        best_config_summary=best_config_summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--folds-pass", type=int, default=4,
        help="Min scored folds required to count as surviving (5-fold default: 4)",
    )
    parser.add_argument(
        "--retention", type=float, default=0.70,
        help="Min holdout retention (best_sec_mean / in_sample_score)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("/tmp/cohort_report.json"),
        help="Where to write the structured results",
    )
    args = parser.parse_args()

    console = Console()
    console.print(
        f"[bold]cohort report[/bold]  db=[cyan]{args.db}[/cyan]  "
        f"folds={args.folds}  folds_pass={args.folds_pass}  "
        f"retention≥{args.retention:.0%}"
    )

    # Discover (template, cohort) pairs in DB.
    con = sqlite3.connect(args.db)
    pairs = con.execute(
        "SELECT DISTINCT template, json_extract(config_json, '$.cohort') AS cohort "
        "FROM runs ORDER BY cohort, template"
    ).fetchall()
    con.close()
    pairs = [(t, c) for t, c in pairs if c is not None]
    console.print(f"  {len(pairs)} (template, cohort) cells to evaluate")

    results: list[CellResult] = []
    for tmpl, cohort in pairs:
        console.print(f"  evaluating  template=[cyan]{tmpl}[/cyan] cohort=[cyan]{cohort}[/cyan]")
        cell = evaluate_cell(
            args.db, tmpl, cohort, args.top,
            args.folds, args.folds_pass, args.retention,
        )
        results.append(cell)

    # Summary table.
    table = Table(
        title="(template, cohort) results matrix",
        show_header=True, header_style="bold magenta",
    )
    table.add_column("template")
    table.add_column("cohort")
    table.add_column("n", justify="right")
    table.add_column("scored", justify="right")
    table.add_column("max", justify="right")
    table.add_column("top-10", justify="right")
    table.add_column("WF surv", justify="right")
    table.add_column("best retention", justify="right")
    table.add_column("verdict")

    for r in results:
        verdict = (
            "[green]PASS[/green]" if r.n_survived >= 3
            else ("[yellow]partial[/yellow]" if r.n_survived >= 1 else "[red]fail[/red]")
        )
        if r.n_scored == 0:
            verdict = "[red]no scored[/red]"
        table.add_row(
            r.template, r.cohort,
            str(r.n_total),
            f"{r.n_scored} ({r.n_scored / max(1, r.n_total):.0%})",
            f"{r.max_score:.1f}" if r.max_score is not None else "-",
            f"{r.top10_mean:.1f}" if r.top10_mean is not None else "-",
            f"{r.n_survived}/{r.n_walk_forward}" if r.n_walk_forward else "-",
            f"{r.best_retention:.0%}" if r.best_retention is not None else "-",
            verdict,
        )
    console.print(table)

    # Highlight survivors.
    survivors = [r for r in results if r.n_survived >= 3]
    if survivors:
        console.print("\n[bold green]surviving cells[/bold green]:")
        for s in survivors:
            console.print(f"  {s.template}/{s.cohort} → {s.best_config_summary}")
    else:
        partial = [r for r in results if r.n_survived >= 1]
        if partial:
            console.print("\n[bold yellow]partial-survival cells[/bold yellow] (≥1 config but <3):")
            for s in partial:
                console.print(f"  {s.template}/{s.cohort} → {s.best_config_summary}")
        else:
            console.print("\n[bold red]no cell produced any walk-forward survivors[/bold red]")

    # Persist structured.
    args.out.write_text(json.dumps([
        {
            "template": r.template, "cohort": r.cohort,
            "n_total": r.n_total, "n_scored": r.n_scored,
            "max_score": r.max_score, "top10_mean": r.top10_mean,
            "n_walk_forward": r.n_walk_forward,
            "n_survived": r.n_survived,
            "best_retention": r.best_retention,
            "best_run_id": r.best_run_id,
            "best_config_summary": r.best_config_summary,
        }
        for r in results
    ], indent=2))
    console.print(f"\n[green]wrote {args.out}[/green]")


if __name__ == "__main__":
    main()
