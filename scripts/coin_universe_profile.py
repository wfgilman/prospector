"""
Profile the Hyperliquid perp universe by realized-vol cohort.

For each coin in `data/ohlcv/<COIN>_PERP/1d.parquet` with sufficient
history, computes:
    sigma_daily        annualized stdev of daily log returns (sqrt(365))
    mean_abs_ret       avg daily |log return|
    max_drawdown       worst peak-to-trough on daily closes
    autocorr_lag1      lag-1 autocorrelation of daily returns
    bars               days of history available

Coins with < `--min-days` history are dropped. The remaining set is
sorted by `sigma_daily` and bucketed into `--cohorts` quantile cohorts.

Output:
    /tmp/cohorts.json    {cohort_label: [coin_ticker, ...]}
    stdout               summary table
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO_ROOT / "data" / "ohlcv"


@dataclass
class CoinProfile:
    coin: str
    bars: int
    sigma_daily: float
    mean_abs_ret: float
    max_drawdown: float
    autocorr_lag1: float


def profile_coin(coin: str) -> CoinProfile | None:
    path = OHLCV_DIR / coin / "1d.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path).sort_values("timestamp")
    if len(df) < 30:
        return None
    closes = df["close"].astype(float)
    log_ret = np.log(closes).diff().dropna()
    if len(log_ret) < 30:
        return None
    sigma = float(log_ret.std() * np.sqrt(365))
    mean_abs = float(log_ret.abs().mean())
    cummax = closes.cummax()
    dd = (cummax - closes) / cummax
    max_dd = float(dd.max())
    if len(log_ret) >= 5:
        autocorr = float(log_ret.autocorr(lag=1))
        if not np.isfinite(autocorr):
            autocorr = 0.0
    else:
        autocorr = 0.0
    return CoinProfile(
        coin=coin, bars=len(df),
        sigma_daily=sigma, mean_abs_ret=mean_abs,
        max_drawdown=max_dd, autocorr_lag1=autocorr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-days", type=int, default=365)
    parser.add_argument("--cohorts", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("/tmp/cohorts.json"))
    args = parser.parse_args()

    console = Console()

    coins = sorted([d.name for d in OHLCV_DIR.iterdir() if d.is_dir()])
    console.print(f"Found [cyan]{len(coins)}[/cyan] coin directories under {OHLCV_DIR}")

    profiles: list[CoinProfile] = []
    skipped = 0
    for c in coins:
        p = profile_coin(c)
        if p is None or p.bars < args.min_days:
            skipped += 1
            continue
        profiles.append(p)

    console.print(
        f"Profiled [cyan]{len(profiles)}[/cyan] coins; "
        f"[yellow]{skipped}[/yellow] skipped (insufficient history)"
    )

    profiles.sort(key=lambda p: p.sigma_daily)

    # Quintile bucket by sigma_daily.
    n = len(profiles)
    cohorts: dict[str, list[str]] = {}
    bucket_size = n // args.cohorts
    for i in range(args.cohorts):
        start = i * bucket_size
        end = (i + 1) * bucket_size if i < args.cohorts - 1 else n
        label = f"vol_q{i + 1}"
        cohorts[label] = [p.coin for p in profiles[start:end]]

    table = Table(
        title="Cohort summary (sorted by σ ascending → quintiles)",
        show_header=True, header_style="bold magenta",
    )
    table.add_column("cohort")
    table.add_column("n", justify="right")
    table.add_column("σ low", justify="right")
    table.add_column("σ med", justify="right")
    table.add_column("σ high", justify="right")
    table.add_column("median DD", justify="right")
    table.add_column("median bars", justify="right")
    table.add_column("first 5 coins")

    for label, coins_in_cohort in cohorts.items():
        ps = [p for p in profiles if p.coin in coins_in_cohort]
        sigmas = sorted(p.sigma_daily for p in ps)
        dds = sorted(p.max_drawdown for p in ps)
        bs = sorted(p.bars for p in ps)
        table.add_row(
            label,
            str(len(ps)),
            f"{sigmas[0]:.2f}",
            f"{sigmas[len(sigmas) // 2]:.2f}",
            f"{sigmas[-1]:.2f}",
            f"{dds[len(dds) // 2]:.1%}",
            str(bs[len(bs) // 2]),
            ", ".join(c.replace("_PERP", "") for c in coins_in_cohort[:5]),
        )

    console.print(table)

    args.out.write_text(json.dumps(cohorts, indent=2))
    console.print(f"\n[green]wrote {args.out}[/green]")


if __name__ == "__main__":
    main()
