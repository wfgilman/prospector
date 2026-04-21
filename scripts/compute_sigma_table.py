"""Build a per-bin σ table for equal-σ position sizing.

Reruns the walk-forward return-distribution pipeline and aggregates per
(category, side, 5¢ price bin): count, mean per-bet return, and σ of per-bet
return. Narrow bins are stabilized with James-Stein-style shrinkage toward
the pooled (category, side) σ using a pseudo-count n0.

Output: data/calibration/sigma_table.json. The live paper trader loads this
at startup and sizes each position as

    risk_budget = NAV * book_σ_target / (N_target * σ_bin)

clipped by the per-bin and per-position caps.

Bins with n < `--min-bin-n` (default 20) are omitted from the bin table; the
portfolio falls back to the pooled (category, side) σ, then to the global
aggregate σ. A candidate that finds no match at any level is rejected at
entry — this is a signal-level failure, not something to guess through.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from return_distribution import (  # noqa: E402
    build_calibration,
    collect_trades,
    load_and_split,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "kalshi_hf"
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "calibration"
    / "sigma_table.json"
)


@dataclass(frozen=True)
class BinStats:
    category: str
    side: str
    bin_low: int
    bin_high: int
    n: int
    mu: float
    sigma_raw: float
    sigma_shrunk: float
    sharpe: float


@dataclass(frozen=True)
class PooledStats:
    key: str
    n: int
    mu: float
    sigma: float


def _group_returns(
    trades: list[dict],
) -> tuple[dict[tuple[str, str, int], list[float]], dict[tuple[str, str], list[float]]]:
    """Index per-bet returns by (category, side, 5¢ bin) and by (category, side)."""
    by_bin: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    by_pool: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in trades:
        bin_low = (int(t["pit_price"]) // 5) * 5
        key = (t["category"], t["side"], bin_low)
        by_bin[key].append(t["per_bet_return"])
        by_pool[(t["category"], t["side"])].append(t["per_bet_return"])
    return by_bin, by_pool


def _moments(returns: list[float]) -> tuple[float, float]:
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return float(arr.mean()) if len(arr) else 0.0, 0.0
    return float(arr.mean()), float(arr.std(ddof=1))


def build(
    trades: list[dict],
    *,
    min_bin_n: int,
    pseudo_count: float,
) -> tuple[list[BinStats], list[PooledStats], PooledStats]:
    """Aggregate trades into per-bin stats with shrinkage toward pool.

    Shrinkage: σ_shrunk² = (n·σ_raw² + n0·σ_pool²) / (n + n0). At n >> n0 the
    bin dominates; at n ≤ n0 the pool carries the estimate. Defaults to
    `pseudo_count=200` — narrow enough that bins with 1000+ observations
    are untouched, wide enough that bins of 200–500 (where per-bin σ is
    noisy) get stabilized.
    """
    by_bin, by_pool = _group_returns(trades)

    pool_moments = {k: _moments(v) for k, v in by_pool.items()}

    bins: list[BinStats] = []
    for (category, side, bin_low), returns in sorted(by_bin.items()):
        n = len(returns)
        if n < min_bin_n:
            continue
        mu, sigma_raw = _moments(returns)
        _, sigma_pool = pool_moments[(category, side)]
        variance_shrunk = (
            n * sigma_raw**2 + pseudo_count * sigma_pool**2
        ) / (n + pseudo_count)
        sigma_shrunk = float(np.sqrt(max(variance_shrunk, 1e-12)))
        sharpe = mu / sigma_shrunk if sigma_shrunk > 0 else 0.0
        bins.append(
            BinStats(
                category=category,
                side=side,
                bin_low=bin_low,
                bin_high=bin_low + 5,
                n=n,
                mu=mu,
                sigma_raw=sigma_raw,
                sigma_shrunk=sigma_shrunk,
                sharpe=sharpe,
            )
        )

    pooled: list[PooledStats] = []
    for (category, side), (mu, sigma) in sorted(pool_moments.items()):
        pooled.append(
            PooledStats(
                key=f"{category}|{side}",
                n=len(by_pool[(category, side)]),
                mu=mu,
                sigma=sigma,
            )
        )

    all_returns = [r for returns in by_pool.values() for r in returns]
    agg_mu, agg_sigma = _moments(all_returns)
    aggregate = PooledStats(
        key="aggregate",
        n=len(all_returns),
        mu=agg_mu,
        sigma=agg_sigma,
    )
    return bins, pooled, aggregate


def save(
    path: Path,
    bins: list[BinStats],
    pooled: list[PooledStats],
    aggregate: PooledStats,
    *,
    min_bin_n: int,
    pseudo_count: float,
    source_window: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_window": source_window,
        "min_bin_n": min_bin_n,
        "pseudo_count": pseudo_count,
        "aggregate": asdict(aggregate),
        "pooled": [asdict(p) for p in pooled],
        "bins": [asdict(b) for b in bins],
    }
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def print_summary(
    bins: list[BinStats],
    pooled: list[PooledStats],
    aggregate: PooledStats,
) -> None:
    print(f"\nAGGREGATE  n={aggregate.n:,}  μ={aggregate.mu:+.3f}  σ={aggregate.sigma:.3f}")
    print("\nPOOLED (category|side)")
    print("  " + "-" * 60)
    print(f"  {'key':<24} {'n':>8} {'μ':>8} {'σ':>8}")
    print("  " + "-" * 60)
    for p in pooled:
        print(f"  {p.key:<24} {p.n:>8,} {p.mu:>+8.3f} {p.sigma:>8.3f}")

    print("\nPER-BIN (showing top 25 by Sharpe)")
    print("  " + "-" * 96)
    print(
        f"  {'cat':<10} {'side':<9} {'bin':<8} {'n':>6} {'μ':>8} {'σ_raw':>8}"
        f" {'σ_shr':>8} {'Sharpe':>8}"
    )
    print("  " + "-" * 96)
    top = sorted(bins, key=lambda b: -b.sharpe)[:25]
    for b in top:
        print(
            f"  {b.category:<10} {b.side:<9} {b.bin_low:>2}-{b.bin_high:<3}"
            f"  {b.n:>6,} {b.mu:>+8.3f} {b.sigma_raw:>8.3f}"
            f" {b.sigma_shrunk:>8.3f} {b.sharpe:>+8.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    parser.add_argument(
        "--min-bin-n",
        type=int,
        default=20,
        help="Minimum trades in a (category, side, bin) cell to emit a bin entry",
    )
    parser.add_argument(
        "--pseudo-count",
        type=float,
        default=200.0,
        help="Shrinkage pseudo-count toward pooled (category, side) σ",
    )
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    con = duckdb.connect()
    split_time = load_and_split(con, args.data_dir, args.min_volume)
    curves = build_calibration(con, split_time)
    trades = collect_trades(con, split_time, curves)
    print(f"\nCollected {len(trades):,} tradeable test-set trades.")

    bins, pooled, aggregate = build(
        trades,
        min_bin_n=args.min_bin_n,
        pseudo_count=args.pseudo_count,
    )
    print_summary(bins, pooled, aggregate)

    source_window = f"test set split at {split_time}"
    save(
        args.out,
        bins,
        pooled,
        aggregate,
        min_bin_n=args.min_bin_n,
        pseudo_count=args.pseudo_count,
        source_window=source_window,
    )
    print(f"\nWrote {args.out} — {len(bins)} bin entries, {len(pooled)} pools.")
    con.close()


if __name__ == "__main__":
    main()
