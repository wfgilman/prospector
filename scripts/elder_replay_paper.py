"""
Funding-aware replay of an Elder triple-screen config across a cohort.

Loads the locked config + a coin universe, runs the harness on each coin,
applies per-trade funding cost via `prospector.harness.funding`, then
aggregates to a portfolio-level Sharpe / DD / win-rate report. The
output is the go/no-go signal against candidate 16's pre-committed
paper-portfolio criteria.

Two replay modes:
    full       Run on the entire ~730-day history (in-sample-with-funding)
    holdout    Run on the most recent N days only (out-of-sample tail)

Usage:
    python scripts/elder_replay_paper.py --run-id 3895
    python scripts/elder_replay_paper.py --run-id 3895 --mode holdout --holdout-days 150
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from walk_forward_top_configs import (  # noqa: E402
    _generate_signals,
    load_top_configs,
)

from prospector.harness.engine import run_backtest  # noqa: E402
from prospector.harness.funding import funding_costs, load_funding  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "prospector_bayesian.db"
DEFAULT_COHORTS = Path("/tmp/cohorts.json")


@dataclass
class CoinReplay:
    coin: str
    n_trades: int
    gross_pnl: float
    funding_cost: float
    fees: float
    net_pnl_no_funding: float
    net_pnl_with_funding: float
    sharpe_no_funding: float
    sharpe_with_funding: float
    max_drawdown: float
    final_nav_no_funding: float
    final_nav_with_funding: float


def _per_trade_returns(net_pnls: list[float], initial_nav: float) -> list[float]:
    """Approximate per-trade returns as net_pnl / initial_nav (flat sizing)."""
    return [p / initial_nav for p in net_pnls]


def _sharpe(per_trade_returns: list[float], bars_per_year_per_trade: float) -> float:
    if len(per_trade_returns) < 2:
        return 0.0
    mean = statistics.fmean(per_trade_returns)
    sd = statistics.pstdev(per_trade_returns)
    if sd == 0.0:
        return 0.0
    return (mean / sd) * math.sqrt(bars_per_year_per_trade)


def _max_drawdown(nav_series: list[float]) -> float:
    peak = nav_series[0]
    max_dd = 0.0
    for v in nav_series:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd


def replay_coin(
    coin: str,
    template: str,
    params: dict,
    holdout_days: int | None = None,
) -> CoinReplay | None:
    coin_root = coin.replace("-PERP", "").replace("_PERP", "")
    perp_safe = coin_root.replace("-", "_") + "_PERP"
    try:
        signals, df = _generate_signals(template, params, perp_safe)
    except FileNotFoundError:
        return None
    if not signals:
        return None
    result = run_backtest(signals, df)
    if result.status != "scored":
        return None

    try:
        funding_df = load_funding(coin_root)
    except FileNotFoundError:
        funding_df = pd.DataFrame({"time": [], "funding_rate": []})

    fundings = funding_costs(result.trades, df, funding_df)

    # Holdout filter: keep only trades whose entry timestamp is within the
    # last N days of the data. This isolates the most-recent fold.
    if holdout_days is not None:
        cutoff = df["timestamp"].iloc[-1] - pd.Timedelta(days=holdout_days)
        keep = [
            i for i, t in enumerate(result.trades)
            if df["timestamp"].iloc[t.entry_bar] >= cutoff
        ]
        trades = [result.trades[i] for i in keep]
        fundings = [fundings[i] for i in keep]
    else:
        trades = result.trades

    if not trades:
        return None

    fees = sum(t.transaction_cost for t in trades)
    gross = sum(t.gross_pnl for t in trades)
    fund_total = sum(fundings)
    pnl_nf = sum(t.net_pnl for t in trades)
    pnl_wf = pnl_nf - fund_total

    initial_nav = trades[0].nav_before
    rets_nf = _per_trade_returns([t.net_pnl for t in trades], initial_nav)
    rets_wf = _per_trade_returns(
        [t.net_pnl - f for t, f in zip(trades, fundings)],
        initial_nav,
    )

    timeframe_days = {"1m": 1 / 1440, "1h": 1 / 24, "4h": 1 / 6, "1d": 1, "1w": 7}
    tf = params.get("short_tf") or params.get("timeframe") or "4h"
    bar_days = timeframe_days[tf]
    avg_hold_bars = sum(t.hold_bars for t in trades) / len(trades)
    avg_hold_days = avg_hold_bars * bar_days
    bars_per_year_per_trade = 365 / max(avg_hold_days, 1e-6)

    sharpe_nf = _sharpe(rets_nf, bars_per_year_per_trade)
    sharpe_wf = _sharpe(rets_wf, bars_per_year_per_trade)

    nav_nf = [initial_nav]
    nav_wf = [initial_nav]
    for t, f in zip(trades, fundings):
        nav_nf.append(nav_nf[-1] + t.net_pnl)
        nav_wf.append(nav_wf[-1] + (t.net_pnl - f))
    max_dd = max(_max_drawdown(nav_nf), _max_drawdown(nav_wf))

    return CoinReplay(
        coin=coin_root,
        n_trades=len(trades),
        gross_pnl=gross,
        funding_cost=fund_total,
        fees=fees,
        net_pnl_no_funding=pnl_nf,
        net_pnl_with_funding=pnl_wf,
        sharpe_no_funding=sharpe_nf,
        sharpe_with_funding=sharpe_wf,
        max_drawdown=max_dd,
        final_nav_no_funding=nav_nf[-1],
        final_nav_with_funding=nav_wf[-1],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--run-id", type=int, required=False,
        help="Specific config run_id to replay; if absent, picks top of "
             "(--template, --cohort) cell",
    )
    parser.add_argument("--template", default="triple_screen")
    parser.add_argument("--cohort", default="vol_q4")
    parser.add_argument(
        "--mode", choices=["full", "holdout"], default="full",
    )
    parser.add_argument("--holdout-days", type=int, default=150)
    parser.add_argument("--cohorts-file", type=Path, default=DEFAULT_COHORTS)
    args = parser.parse_args()

    console = Console()

    # Resolve config.
    if args.run_id:
        con = sqlite3.connect(args.db)
        row = con.execute(
            "SELECT template, config_json FROM runs WHERE run_id = ?",
            (args.run_id,),
        ).fetchone()
        con.close()
        if not row:
            console.print(f"[red]run_id {args.run_id} not found[/red]")
            return
        template, cfg_json = row
        params = json.loads(cfg_json)["params"]
    else:
        configs = load_top_configs(
            args.db, top_n=1, template=args.template, cohort=args.cohort,
        )
        if not configs:
            console.print("[red]no scored configs[/red]")
            return
        cfg = configs[0]
        template = cfg.template
        params = cfg.params
        args.run_id = cfg.run_id

    console.print(
        f"[bold]replay #{args.run_id}[/bold]  template={template}  "
        f"params={params}  mode={args.mode}"
        + (f" (last {args.holdout_days}d)" if args.mode == "holdout" else "")
    )

    cohorts = json.loads(args.cohorts_file.read_text())
    cohort_coins = cohorts[args.cohort]

    holdout = args.holdout_days if args.mode == "holdout" else None

    replays: list[CoinReplay] = []
    skipped = 0
    for coin in cohort_coins:
        r = replay_coin(coin, template, params, holdout_days=holdout)
        if r is None:
            skipped += 1
            continue
        replays.append(r)
    console.print(f"  {len(replays)} replays  ({skipped} skipped)")

    table = Table(
        title="Per-coin replay (sorted by Sharpe-with-funding desc)",
        show_header=True, header_style="bold magenta",
    )
    for col in [
        "coin", "trades", "gross", "fees", "funding",
        "net (no fund)", "net (w/fund)", "Sharpe nf", "Sharpe wf", "max DD",
    ]:
        table.add_column(col, justify="right" if col != "coin" else "left")
    replays.sort(key=lambda r: r.sharpe_with_funding, reverse=True)
    for r in replays:
        table.add_row(
            r.coin, str(r.n_trades),
            f"{r.gross_pnl:+.0f}", f"{r.fees:.0f}", f"{r.funding_cost:+.0f}",
            f"{r.net_pnl_no_funding:+.0f}",
            f"{r.net_pnl_with_funding:+.0f}",
            f"{r.sharpe_no_funding:.2f}", f"{r.sharpe_with_funding:.2f}",
            f"{r.max_drawdown:.0%}",
        )
    console.print(table)

    # Aggregate to portfolio level (1/N capital allocation).
    if not replays:
        console.print("[red]no replays produced; cannot compute portfolio metrics[/red]")
        return
    total_pnl_nf = sum(r.net_pnl_no_funding for r in replays)
    total_pnl_wf = sum(r.net_pnl_with_funding for r in replays)
    total_fund = sum(r.funding_cost for r in replays)
    median_sharpe_wf = statistics.median(r.sharpe_with_funding for r in replays)
    mean_sharpe_wf = statistics.fmean(r.sharpe_with_funding for r in replays)
    max_dd = max(r.max_drawdown for r in replays)
    funding_pct = (total_fund / abs(total_pnl_nf) * 100) if total_pnl_nf else 0.0

    console.print(
        "\n[bold]Portfolio aggregate[/bold] "
        f"(n_coins={len(replays)}, mode={args.mode})"
    )
    console.print(f"  total gross P&L:      ${sum(r.gross_pnl for r in replays):+.0f}")
    console.print(f"  total fees:           ${sum(r.fees for r in replays):.0f}")
    console.print(f"  total funding cost:   ${total_fund:+.0f}  "
                  f"({funding_pct:+.1f}% of P&L magnitude)")
    console.print(f"  total net (no fund):  ${total_pnl_nf:+.0f}")
    console.print(f"  total net (w/ fund):  ${total_pnl_wf:+.0f}")
    console.print(f"  median Sharpe wf:     {median_sharpe_wf:.2f}")
    console.print(f"  mean Sharpe wf:       {mean_sharpe_wf:.2f}")
    console.print(f"  max DD across coins:  {max_dd:.0%}")

    # Pre-committed criteria from candidate 16.
    console.print("\n[bold]Pre-committed paper criteria (#16):[/bold]")
    crit1 = mean_sharpe_wf >= 1.0
    crit2 = median_sharpe_wf >= 0.5
    crit3 = max_dd <= 0.25
    console.print(
        f"  [green]✓[/green] aggregate Sharpe ≥ 1.0    : "
        f"{mean_sharpe_wf:.2f}  {'PASS' if crit1 else 'FAIL'}"
    )
    console.print(
        f"  [green]✓[/green] median per-coin ≥ 0.5     : "
        f"{median_sharpe_wf:.2f}  {'PASS' if crit2 else 'FAIL'}"
    )
    console.print(
        f"  [green]✓[/green] max DD ≤ 25%              : "
        f"{max_dd:.0%}  {'PASS' if crit3 else 'FAIL'}"
    )
    if crit1 and crit2 and crit3:
        console.print("\n[bold green]GO — all paper criteria met[/bold green]")
    else:
        console.print("\n[bold red]NO-GO — at least one paper criterion fails[/bold red]")


if __name__ == "__main__":
    main()
