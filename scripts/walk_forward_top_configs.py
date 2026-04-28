"""
Walk-forward validation for top-N configs from a Prospector ledger.

For each of the top-N scored configs (by full-sample score) in a ledger DB,
regenerate signals on the matching OHLCV data and re-score the config on
`n_folds` consecutive equal-size time windows using the existing
`run_walk_forward` harness. Report per-security and aggregate fold scores
side-by-side with the in-sample score.

Purpose: detect whether a high in-sample score reflects genuine edge that
holds across time, or a single lucky period (overfitting to the oracle
search).

Usage:
    python -m scripts.walk_forward_top_configs \
        --db data/prospector_oracle.db --top 10 --folds 5

The script only reads the ledger; it does not write back. Results print to
stdout as a table plus per-config fold breakdowns.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from prospector.harness.engine import run_backtest
from prospector.harness.walk_forward import run_walk_forward
from prospector.templates import (
    channel_fade,
    ema_divergence,
    false_breakout,
    impulse_system,
    kangaroo_tail,
    triple_screen,
)
from prospector.templates.base import Signal

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "data" / "ohlcv"


@dataclass
class TopConfig:
    run_id: int
    template: str
    params: dict
    securities: list[str]
    in_sample_score: float
    n_trades: int


def load_top_configs(db_path: Path, top_n: int, template: str | None = None) -> list[TopConfig]:
    """Read the top-N scored configs from a ledger DB. Optional template filter."""
    con = sqlite3.connect(db_path)
    if template is None:
        rows = con.execute(
            "SELECT run_id, template, config_json, securities_json, score, n_trades "
            "FROM runs WHERE validation_status = 'valid' AND backtest_status = 'scored' "
            "ORDER BY score DESC LIMIT ?",
            (top_n,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT run_id, template, config_json, securities_json, score, n_trades "
            "FROM runs WHERE validation_status = 'valid' AND backtest_status = 'scored' "
            "AND template = ? ORDER BY score DESC LIMIT ?",
            (template, top_n),
        ).fetchall()
    con.close()

    configs = []
    for run_id, template, cfg_json, secs_json, score, n in rows:
        cfg = json.loads(cfg_json)
        configs.append(TopConfig(
            run_id=run_id,
            template=template,
            params=cfg.get("params", {}),
            securities=json.loads(secs_json) if secs_json else [],
            in_sample_score=score,
            n_trades=n,
        ))
    return configs


def _coin(sec: str) -> str:
    return sec.replace("-", "_")


def _load_ohlcv(coin: str, tf: str) -> pd.DataFrame:
    path = _DATA_DIR / coin / f"{tf}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OHLCV data not found: {path}")
    return pd.read_parquet(path)


_SINGLE_TF_TEMPLATES = {
    "false_breakout": false_breakout,
    "impulse_system": impulse_system,
    "channel_fade": channel_fade,
    "kangaroo_tail": kangaroo_tail,
    "ema_divergence": ema_divergence,
}


def _generate_signals(template: str, params: dict, coin: str) -> tuple[list[Signal], pd.DataFrame]:
    """Return (signals, backtest_df). backtest_df is the frame fold splitting uses."""
    if template in _SINGLE_TF_TEMPLATES:
        df = _load_ohlcv(coin, params["timeframe"])
        return _SINGLE_TF_TEMPLATES[template].run(df, params), df
    if template == "triple_screen":
        df_long = _load_ohlcv(coin, params["long_tf"])
        df_short = _load_ohlcv(coin, params["short_tf"])
        return triple_screen.run(df_long, df_short, params), df_short
    raise ValueError(f"Template not supported: {template!r}")


@dataclass
class SecurityWalkForward:
    security: str
    in_sample_score: float | None
    in_sample_status: str
    in_sample_n_trades: int
    fold_scores: list[float]      # per-fold numeric (sentinels for non-scored)
    fold_statuses: list[str]      # "scored" | "rejected" | "catastrophic"
    mean_scored: float | None     # mean across scored folds only
    std_scored: float | None
    consistent: bool              # all scored folds > 0


@dataclass
class ConfigWalkForward:
    config: TopConfig
    per_security: list[SecurityWalkForward]


def _run_config(cfg: TopConfig, n_folds: int) -> ConfigWalkForward:
    per_sec = []
    for sec in cfg.securities:
        coin = _coin(sec)
        signals, df = _generate_signals(cfg.template, cfg.params, coin)

        # In-sample baseline: same backtest as the oracle ran.
        in_sample = run_backtest(signals, df)

        wf = run_walk_forward(signals, df, n_folds=n_folds)
        fold_scores = wf.fold_scores
        fold_statuses = [f.result.status for f in wf.folds]
        scored = [s for s, st in zip(fold_scores, fold_statuses) if st == "scored"]
        mean_s = statistics.fmean(scored) if scored else None
        std_s = statistics.pstdev(scored) if len(scored) >= 2 else None

        per_sec.append(SecurityWalkForward(
            security=sec,
            in_sample_score=in_sample.score if in_sample.status == "scored" else None,
            in_sample_status=in_sample.status,
            in_sample_n_trades=in_sample.n_trades,
            fold_scores=fold_scores,
            fold_statuses=fold_statuses,
            mean_scored=mean_s,
            std_scored=std_s,
            consistent=wf.consistent,
        ))
    return ConfigWalkForward(config=cfg, per_security=per_sec)


def _format_fold_cell(score: float, status: str) -> str:
    if status == "scored":
        return f"[green]{score:.1f}[/green]"
    if status == "rejected":
        return "[yellow]rej[/yellow]"
    if status == "catastrophic":
        return "[red]cat[/red]"
    return "?"


def render(results: list[ConfigWalkForward], n_folds: int, console: Console) -> None:
    # Per-config detail tables
    for r in results:
        cfg = r.config
        console.print(
            f"\n[bold]#{cfg.run_id}[/bold]  "
            f"in-sample score=[cyan]{cfg.in_sample_score:.1f}[/cyan]  "
            f"n_trades={cfg.n_trades}  "
            f"{cfg.template}  "
            f"secs={','.join(s.replace('-PERP','') for s in cfg.securities)}"
        )
        console.print(f"  params: {cfg.params}")

        tbl = Table(show_header=True, header_style="bold magenta", box=None)
        tbl.add_column("security")
        tbl.add_column("in-sample", justify="right")
        for i in range(n_folds):
            tbl.add_column(f"f{i}", justify="right")
        tbl.add_column("scored/N", justify="right")
        tbl.add_column("mean", justify="right")
        tbl.add_column("std", justify="right")
        tbl.add_column("consistent")

        for s in r.per_security:
            row = [s.security.replace("-PERP", "")]
            if s.in_sample_status == "scored":
                row.append(f"{s.in_sample_score:.1f}")
            else:
                row.append(f"[yellow]{s.in_sample_status}[/yellow]")
            for sc, st in zip(s.fold_scores, s.fold_statuses):
                row.append(_format_fold_cell(sc, st))
            n_scored = sum(1 for st in s.fold_statuses if st == "scored")
            row.append(f"{n_scored}/{len(s.fold_statuses)}")
            row.append(f"{s.mean_scored:.1f}" if s.mean_scored is not None else "-")
            row.append(f"{s.std_scored:.1f}" if s.std_scored is not None else "-")
            row.append("[green]yes[/green]" if s.consistent else "[red]no[/red]")
            tbl.add_row(*row)

        console.print(tbl)

    # Summary table
    console.print("\n[bold]Summary — mean across scored folds per security[/bold]")
    summary = Table(show_header=True, header_style="bold magenta")
    summary.add_column("run_id", justify="right")
    summary.add_column("template")
    summary.add_column("secs")
    summary.add_column("in-sample", justify="right")
    summary.add_column("best sec mean", justify="right")
    summary.add_column("best sec scored/N", justify="right")
    summary.add_column("consistent?")
    summary.add_column("degradation", justify="right")

    for r in results:
        cfg = r.config
        # Pick the security whose scored-fold mean is highest (best holdout for this config)
        best = None
        for s in r.per_security:
            if s.mean_scored is None:
                continue
            if best is None or s.mean_scored > best.mean_scored:
                best = s
        if best is None:
            summary.add_row(
                str(cfg.run_id), cfg.template,
                ",".join(s.replace("-PERP", "") for s in cfg.securities),
                f"{cfg.in_sample_score:.1f}", "-", "-", "[red]no[/red]", "-",
            )
            continue

        degradation = cfg.in_sample_score - best.mean_scored
        degradation_pct = degradation / cfg.in_sample_score * 100
        n_scored = sum(1 for st in best.fold_statuses if st == "scored")
        summary.add_row(
            str(cfg.run_id),
            cfg.template,
            ",".join(s.replace("-PERP", "") for s in cfg.securities),
            f"{cfg.in_sample_score:.1f}",
            f"{best.mean_scored:.1f}",
            f"{n_scored}/{len(best.fold_statuses)}",
            "[green]yes[/green]" if best.consistent else "[red]no[/red]",
            f"{degradation_pct:+.0f}%",
        )
    console.print(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_REPO_ROOT / "data" / "prospector_oracle.db")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--template", type=str, default=None,
        help="Filter to one template; otherwise the global top across templates is used",
    )
    args = parser.parse_args()

    console = Console()
    console.print("[bold green]Walk-forward validation[/bold green]")
    tmpl_label = args.template if args.template else "(all)"
    console.print(
        f"DB: [cyan]{args.db}[/cyan]  template=[cyan]{tmpl_label}[/cyan]  "
        f"top={args.top}  folds={args.folds}"
    )

    configs = load_top_configs(args.db, args.top, template=args.template)
    if not configs:
        console.print("[red]No scored configs found in DB.[/red]")
        return

    results = [_run_config(c, args.folds) for c in configs]
    render(results, args.folds, console)


if __name__ == "__main__":
    main()
