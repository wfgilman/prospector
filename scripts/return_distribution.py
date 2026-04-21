"""Per-trade return-distribution analysis for the PM underwriting book.

Reruns the walk-forward pipeline (same 70/30 split, same per-category
calibration) but instead of reporting aggregate Sharpe it dumps the per-trade
return distribution. Per-trade return is expressed as (pnl / risk_budget) so
it's dimensionless and stratifies cleanly by price bin and side.

Outputs:
  - Per-bet μ, σ, Sharpe (dimensionless, per $1 of risk)
  - Per-price-bin × side breakdown (where signal concentrates)
  - Per-category breakdown
  - Sample-size requirement N for P(book positive) ≥ {0.90, 0.95, 0.99}
    under the independence assumption
  - Comparison: what the current Kelly + caps framework allows vs. what
    the data says is needed

The goal is to tell us: is the current book sized appropriately relative to
its realized distribution, or are we operating in a regime where the LLN
hasn't had a chance to work?
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "kalshi_hf"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration"

CATEGORY_SQL = """
CASE
    WHEN event_ticker LIKE 'KXMVESPORTS%' OR event_ticker LIKE 'KXMVENFL%'
         OR event_ticker LIKE 'KXMVENBA%' OR event_ticker LIKE 'KXNCAA%'
         OR event_ticker LIKE 'KXNFLGAME%' OR event_ticker LIKE 'KXNFL%'
         OR event_ticker LIKE 'KXNBA%' THEN 'sports'
    WHEN event_ticker LIKE 'KXBTC%' OR event_ticker LIKE 'KXETH%'
         OR event_ticker LIKE 'KXDOGE%' OR event_ticker LIKE 'KXXRP%'
         OR event_ticker LIKE 'KXSOL%' OR event_ticker LIKE 'KXSHIBA%' THEN 'crypto'
    WHEN event_ticker LIKE 'KXNASDAQ%' OR event_ticker LIKE 'KXINX%'
         OR event_ticker LIKE 'NASDAQ%' OR event_ticker LIKE 'INX%'
         OR event_ticker LIKE '%USDJPY%' OR event_ticker LIKE '%EURUSD%' THEN 'financial'
    WHEN event_ticker LIKE 'KXCITIES%' OR event_ticker LIKE 'HIGH%'
         OR event_ticker LIKE 'LOW%' THEN 'weather'
    WHEN event_ticker LIKE 'CPI%' OR event_ticker LIKE 'FED%'
         OR event_ticker LIKE 'KXFED%' OR event_ticker LIKE 'GDP%' THEN 'economics'
    WHEN event_ticker LIKE 'PRES%' OR event_ticker LIKE 'SENATE%'
         OR event_ticker LIKE 'HOUSE%' OR event_ticker LIKE 'KXGOV%'
         OR event_ticker LIKE 'KXMAYOR%' THEN 'politics'
    ELSE 'other'
END
"""

MIN_EDGE_PP = 2.0


@dataclass
class CalibrationBin:
    bin_low: int
    bin_high: int
    n: int
    yes_count: int

    @property
    def actual_rate(self) -> float:
        return self.yes_count / self.n if self.n > 0 else 0.0

    @property
    def implied_mid(self) -> float:
        return (self.bin_low + self.bin_high) / 2 / 100


def load_and_split(con: duckdb.DuckDBPyConnection, data_dir: Path, min_volume: int) -> str:
    print("Loading markets...")
    con.execute(f"""
        CREATE TABLE markets AS
        SELECT ticker, event_ticker, result, volume, open_time, close_time,
               open_time + (close_time - open_time) / 2 AS pit_time,
               {CATEGORY_SQL} AS category
        FROM '{data_dir}/markets-*.parquet'
        WHERE result IN ('yes', 'no')
          AND volume >= {min_volume}
          AND close_time > open_time
    """)
    print(f"  Resolved markets: {con.execute('SELECT COUNT(*) FROM markets').fetchone()[0]:,}")

    print("Loading trades (filtered to resolved markets)...")
    con.execute(f"""
        CREATE TABLE trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM '{data_dir}/trades-*.parquet' t
        SEMI JOIN markets m ON t.ticker = m.ticker
        ORDER BY t.ticker, t.created_time
    """)
    print(f"  Matching trades: {con.execute('SELECT COUNT(*) FROM trades').fetchone()[0]:,}")

    print("Computing PIT prices...")
    con.execute("""
        CREATE TABLE pit AS
        SELECT m.ticker, m.event_ticker, m.result, m.volume,
               m.pit_time, m.category, m.close_time,
               t.yes_price AS pit_price,
               t.created_time AS trade_time,
               ABS(EXTRACT(EPOCH FROM (t.created_time - m.pit_time)))
                   / NULLIF(EXTRACT(EPOCH FROM (m.close_time - m.open_time)), 0)
                   AS offset_frac
        FROM markets m
        ASOF JOIN trades t
            ON m.ticker = t.ticker
            AND m.pit_time >= t.created_time
        WHERE t.yes_price IS NOT NULL
    """)
    con.execute("""
        CREATE TABLE pit_clean AS
        SELECT * FROM pit
        WHERE offset_frac <= 0.25 AND pit_price BETWEEN 1 AND 99
    """)
    print(f"  PIT-priced markets (offset ≤25%): "
          f"{con.execute('SELECT COUNT(*) FROM pit_clean').fetchone()[0]:,}")

    split_time = con.execute("""
        SELECT close_time FROM (
            SELECT close_time,
                   ROW_NUMBER() OVER (ORDER BY close_time) AS rn,
                   COUNT(*) OVER () AS total FROM pit_clean
        )
        WHERE rn = CAST(FLOOR(total * 0.7) AS INTEGER)
    """).fetchone()[0]
    print(f"  Train/test split at: {split_time}")
    return str(split_time)


def build_calibration(con, split_time: str) -> dict[str, list[CalibrationBin]]:
    categories = [r[0] for r in con.execute(
        "SELECT DISTINCT category FROM pit_clean ORDER BY category"
    ).fetchall()]
    curves: dict[str, list[CalibrationBin]] = {}
    for cat in categories:
        rows = con.execute(f"""
            SELECT FLOOR(pit_price / 5) * 5, FLOOR(pit_price / 5) * 5 + 5,
                   COUNT(*), SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END)
            FROM pit_clean
            WHERE close_time <= '{split_time}' AND category = '{cat}'
            GROUP BY 1, 2 ORDER BY 1
        """).fetchall()
        curves[cat] = [CalibrationBin(int(r[0]), int(r[1]), r[2], r[3]) for r in rows]
    rows = con.execute(f"""
        SELECT FLOOR(pit_price / 5) * 5, FLOOR(pit_price / 5) * 5 + 5,
               COUNT(*), SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END)
        FROM pit_clean
        WHERE close_time <= '{split_time}'
        GROUP BY 1, 2 ORDER BY 1
    """).fetchall()
    curves["_aggregate"] = [CalibrationBin(int(r[0]), int(r[1]), r[2], r[3]) for r in rows]
    return curves


def lookup_edge(curves, category: str, pit_price: int) -> tuple[float, str]:
    bins = curves.get(category, curves["_aggregate"])
    for b in bins:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100
            return abs(edge), ("sell_yes" if edge > 0 else "buy_yes")
    for b in curves["_aggregate"]:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100
            return abs(edge), ("sell_yes" if edge > 0 else "buy_yes")
    return 0.0, ""


def collect_trades(con, split_time: str, curves) -> list[dict]:
    """Enumerate every tradeable test-set market and record its per-bet return.

    Per-bet return is normalized: pnl / risk_budget ∈ {+reward/risk, -1}.
    Reward/risk is a function of entry price and side; it collapses to a
    dimensionless payoff multiple that's directly comparable across trades.
    """
    rows = con.execute(f"""
        SELECT ticker, category, pit_price, result
        FROM pit_clean WHERE close_time > '{split_time}'
        ORDER BY close_time
    """).fetchall()

    trades = []
    for ticker, category, pit_price, result in rows:
        edge, side = lookup_edge(curves, category, pit_price)
        if edge < MIN_EDGE_PP or not side:
            continue
        # Dimensionless payoffs: +reward/risk on win, -1 on loss.
        p = pit_price / 100
        if side == "sell_yes":
            reward_per_risk = p / (1 - p)
            won = (result == "no")
        else:
            reward_per_risk = (1 - p) / p
            won = (result == "yes")
        per_bet_return = reward_per_risk if won else -1.0
        trades.append({
            "category": category,
            "pit_price": pit_price,
            "side": side,
            "edge": edge,
            "won": won,
            "per_bet_return": per_bet_return,
            "reward_per_risk": reward_per_risk,
        })
    return trades


def summarize(label: str, trades: list[dict]) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    returns = np.array([t["per_bet_return"] for t in trades])
    wins = np.array([t["won"] for t in trades])
    payoffs = np.array([t["reward_per_risk"] for t in trades])
    mu = float(returns.mean())
    sigma = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = mu / sigma if sigma > 0 else 0.0
    # N required so that (mu/sigma) * sqrt(N) ≥ z_target → 90% ≈ 1.28, 95% ≈ 1.645, 99% ≈ 2.33
    n_for = {
        0.90: int(np.ceil((1.2816 / sharpe) ** 2)) if sharpe > 0 else float("inf"),
        0.95: int(np.ceil((1.6449 / sharpe) ** 2)) if sharpe > 0 else float("inf"),
        0.99: int(np.ceil((2.3263 / sharpe) ** 2)) if sharpe > 0 else float("inf"),
    }
    return {
        "label": label, "n": len(trades),
        "win_rate": float(wins.mean()),
        "avg_payoff": float(payoffs.mean()),
        "mu": mu, "sigma": sigma, "sharpe": sharpe,
        "n_for_90": n_for[0.90], "n_for_95": n_for[0.95], "n_for_99": n_for[0.99],
    }


def print_summary(summaries: list[dict], title: str) -> None:
    print(f"\n{title}")
    print("  " + "-" * 110)
    print(f"  {'Stratum':<30} {'n':>8} {'WR':>7} {'avg/$':>8} {'μ':>8} {'σ':>8}"
          f" {'Sharpe':>8} {'N@90%':>9} {'N@95%':>9} {'N@99%':>9}")
    print("  " + "-" * 110)
    for s in summaries:
        if s["n"] == 0:
            continue
        print(f"  {s['label']:<30} {s['n']:>8,} {s['win_rate']:>7.1%} "
              f"{s['avg_payoff']:>8.2f} {s['mu']:>+8.3f} {s['sigma']:>8.3f} "
              f"{s['sharpe']:>8.3f} {s['n_for_90']:>9} {s['n_for_95']:>9} {s['n_for_99']:>9}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    parser.add_argument(
        "--top-edge-only", action="store_true",
        help="Filter to top-decile edge (matches capital-constrained selection)",
    )
    args = parser.parse_args()

    con = duckdb.connect()
    split_time = load_and_split(con, args.data_dir, args.min_volume)
    curves = build_calibration(con, split_time)
    trades = collect_trades(con, split_time, curves)
    print(f"\nCollected {len(trades):,} tradeable trades on test set.")

    if args.top_edge_only:
        threshold = np.quantile([t["edge"] for t in trades], 0.90)
        trades = [t for t in trades if t["edge"] >= threshold]
        print(f"Filtered to top decile (edge ≥ {threshold:.1f}pp): {len(trades):,} trades")

    all_summary = summarize("ALL TRADES", trades)
    print_summary([all_summary], "AGGREGATE DISTRIBUTION")

    # By side
    by_side = []
    for side in ("sell_yes", "buy_yes"):
        by_side.append(summarize(f"side={side}", [t for t in trades if t["side"] == side]))
    print_summary(by_side, "BY SIDE")

    # By category
    by_cat = []
    for cat in sorted(set(t["category"] for t in trades)):
        by_cat.append(summarize(f"cat={cat}", [t for t in trades if t["category"] == cat]))
    print_summary(by_cat, "BY CATEGORY")

    # By price bin × side
    by_bin = []
    for side in ("sell_yes", "buy_yes"):
        for low in range(0, 100, 5):
            sub = [t for t in trades if t["side"] == side and low <= t["pit_price"] < low + 5]
            if len(sub) >= 50:
                by_bin.append(summarize(f"{side} {low:>2}-{low+5:<3}", sub))
    print_summary(by_bin, "BY PRICE BIN × SIDE (only bins with n ≥ 50)")

    # Highlight the "high-edge" slice: bins where |deviation| ≥ 5pp
    high_edge = [t for t in trades if t["edge"] >= 5.0]
    print_summary([summarize("edge ≥ 5pp", high_edge)], "HIGH-EDGE SLICE (what the ranker picks)")

    # Current-framework rough comparison
    print("\nCURRENT FRAMEWORK SNAPSHOT")
    print("  " + "-" * 70)
    print("  Paper portfolio at ~36 positions, $10K NAV, 1%/position cap.")
    print(f"  Per-bet σ (all trades):         {all_summary['sigma']:.3f}")
    print(f"  Per-bet Sharpe (all trades):    {all_summary['sharpe']:.3f}")
    print(f"  N required for 90% confidence:  {all_summary['n_for_90']}")
    print(f"  N required for 95% confidence:  {all_summary['n_for_95']}")
    print(f"  Current book vs target (90%):   36 vs {all_summary['n_for_90']}"
          f" → {'OK' if 36 >= all_summary['n_for_90'] else 'UNDER-SAMPLED'}")
    if high_edge:
        he = summarize("edge ≥ 5pp", high_edge)
        print(f"  High-edge slice Sharpe:         {he['sharpe']:.3f}")
        print(f"  High-edge N required (90%):     {he['n_for_90']}")

    con.close()


if __name__ == "__main__":
    main()
