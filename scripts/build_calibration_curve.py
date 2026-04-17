"""
Build a calibration curve from Kalshi historical data.

For each resolved market, computes the Point-in-Time (PIT) price at 50% of
market duration, then bins by implied probability and measures the actual
resolution rate.  Outputs aggregate and per-category curves with Wilson
confidence intervals.

Data source: TrevorJS/kalshi-trades HuggingFace dataset (local parquet).

Usage:
    python scripts/build_calibration_curve.py [--data-dir DATA_DIR] [--min-volume 10]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "kalshi_hf"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "calibration"

BIN_EDGES = list(range(0, 101, 5))  # 0, 5, 10, ..., 95, 100 → 20 bins
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


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p_hat = successes / n
    denom = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denom
    spread = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def compute_pit_prices(con: duckdb.DuckDBPyConnection, data_dir: Path, min_volume: int) -> None:
    """Join markets with trades to find PIT price at 50% of market duration."""

    con.execute(f"""
        CREATE OR REPLACE TABLE markets AS
        SELECT
            ticker,
            event_ticker,
            result,
            volume,
            open_time,
            close_time,
            open_time + (close_time - open_time) / 2 AS pit_time,
            {CATEGORY_SQL} AS category
        FROM '{data_dir}/markets-*.parquet'
        WHERE result IN ('yes', 'no')
          AND volume >= {min_volume}
          AND close_time > open_time
    """)

    market_count = con.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"Resolved markets with volume >= {min_volume}: {market_count:,}")

    # Only load trades for tickers we care about
    print("Loading trades for resolved markets...")
    con.execute(f"""
        CREATE OR REPLACE TABLE trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM '{data_dir}/trades-*.parquet' t
        SEMI JOIN markets m ON t.ticker = m.ticker
        ORDER BY t.ticker, t.created_time
    """)

    trade_count = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"Matching trades loaded: {trade_count:,}")

    # ASOF join: last trade at or before PIT time
    print("Computing PIT prices via ASOF join...")
    con.execute("""
        CREATE OR REPLACE TABLE pit_prices AS
        SELECT m.ticker, m.event_ticker, m.result, m.volume,
               m.pit_time, m.category,
               t.yes_price AS pit_price,
               t.created_time AS trade_time
        FROM markets m
        ASOF JOIN trades t
            ON m.ticker = t.ticker
            AND m.pit_time >= t.created_time
    """)

    # Markets with no pre-PIT trade: get the first trade after PIT
    no_pit = con.execute("""
        SELECT COUNT(*) FROM pit_prices WHERE pit_price IS NULL
    """).fetchone()[0]
    if no_pit > 0:
        print(f"  {no_pit:,} markets have no pre-PIT trade, trying post-PIT fallback...")
        con.execute("""
            CREATE OR REPLACE TABLE post_pit AS
            SELECT m.ticker, MIN(t.created_time) AS first_after
            FROM markets m
            JOIN trades t ON m.ticker = t.ticker AND t.created_time > m.pit_time
            WHERE m.ticker IN (SELECT ticker FROM pit_prices WHERE pit_price IS NULL)
            GROUP BY m.ticker
        """)
        con.execute("""
            UPDATE pit_prices
            SET pit_price = t.yes_price,
                trade_time = t.created_time
            FROM post_pit pp
            JOIN trades t ON pp.ticker = t.ticker AND pp.first_after = t.created_time
            WHERE pit_prices.ticker = pp.ticker
        """)
        con.execute("DROP TABLE post_pit")

    pit_count = con.execute("SELECT COUNT(*) FROM pit_prices").fetchone()[0]
    print(f"Markets with PIT price: {pit_count:,} ({pit_count / market_count * 100:.1f}%)")

    # Validate: exclude markets where trade is too far from PIT
    # (>25% of market duration from midpoint means we're in the first or last quarter)
    con.execute("""
        CREATE OR REPLACE TABLE pit_clean AS
        SELECT p.*,
               m.open_time,
               m.close_time,
               ABS(EXTRACT(EPOCH FROM (p.trade_time - p.pit_time)))
                   / NULLIF(EXTRACT(EPOCH FROM (m.close_time - m.open_time)), 0) AS time_offset_frac
        FROM pit_prices p
        JOIN markets m ON p.ticker = m.ticker
    """)

    con.execute("""
        CREATE OR REPLACE TABLE pit_final AS
        SELECT * FROM pit_clean
        WHERE time_offset_frac <= 0.25
    """)

    final_count = con.execute("SELECT COUNT(*) FROM pit_final").fetchone()[0]
    print(f"After time-offset filter (≤25% from midpoint): {final_count:,}")


def build_calibration_data(con: duckdb.DuckDBPyConnection) -> dict:
    """Compute calibration bins for aggregate and per-category curves."""

    results = {}

    for scope_name, where_clause in [
        ("aggregate", "1=1"),
        ("sports", "category = 'sports'"),
        ("crypto", "category = 'crypto'"),
        ("financial", "category = 'financial'"),
        ("weather", "category = 'weather'"),
        ("economics", "category = 'economics'"),
        ("politics", "category = 'politics'"),
        ("other", "category = 'other'"),
    ]:
        rows = con.execute(f"""
            SELECT
                FLOOR(pit_price / 5) * 5 AS bin_low,
                FLOOR(pit_price / 5) * 5 + 5 AS bin_high,
                COUNT(*) AS n,
                SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) AS yes_count,
                ROUND(AVG(pit_price), 2) AS avg_price,
                ROUND(AVG(volume), 0) AS avg_vol
            FROM pit_final
            WHERE {where_clause}
              AND pit_price BETWEEN 1 AND 99
            GROUP BY bin_low, bin_high
            ORDER BY bin_low
        """).fetchall()

        bins = []
        for row in rows:
            bin_low, bin_high, n, yes_count, avg_price, avg_vol = row
            actual_rate = yes_count / n if n > 0 else 0
            implied_mid = (bin_low + bin_high) / 2 / 100
            ci_low, ci_high = wilson_ci(yes_count, n)
            deviation = actual_rate - implied_mid
            bins.append({
                "bin_low": int(bin_low),
                "bin_high": int(bin_high),
                "implied_mid": implied_mid,
                "avg_price": avg_price / 100,
                "n": n,
                "yes_count": yes_count,
                "actual_rate": actual_rate,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "deviation_pp": deviation * 100,
                "avg_vol": avg_vol,
            })

        results[scope_name] = bins

    return results


def compute_fee_adjusted_edge(implied: float, actual: float) -> float:
    """Compute edge after Kalshi taker fees (round-trip)."""
    # Taker fee per side: 0.07 * p * (1 - p)
    # Round-trip: 2 * 0.07 * p * (1 - p)
    p = implied
    fee_rt = 2 * 0.07 * p * (1 - p)
    raw_edge = abs(actual - implied)
    return raw_edge - fee_rt


def print_results(calibration: dict) -> None:
    """Print calibration tables to stdout."""

    for scope_name, bins in calibration.items():
        print(f"\n{'=' * 80}")
        print(f"  CALIBRATION: {scope_name.upper()}")
        print(f"{'=' * 80}")
        print(
            f"  {'Bin':>7}  {'N':>8}  {'Implied':>8}  {'Actual':>8}  "
            f"{'Dev(pp)':>8}  {'CI':>13}  {'Fee-adj':>8}  {'Signal':>6}"
        )
        dividers = [7, 8, 8, 8, 8, 13, 8, 6]
        print("  " + "  ".join("─" * w for w in dividers))

        signal_bins = 0
        for b in bins:
            fee_adj = compute_fee_adjusted_edge(b["implied_mid"], b["actual_rate"])
            is_signal = b["n"] >= 100 and abs(b["deviation_pp"]) > 3 and fee_adj > 0
            if is_signal:
                signal_bins += 1

            marker = " ***" if is_signal else ""
            print(
                f"  {b['bin_low']:>2}-{b['bin_high']:>3}  "
                f"{b['n']:>8,}  "
                f"{b['implied_mid']:>7.1%}  "
                f"{b['actual_rate']:>7.1%}  "
                f"{b['deviation_pp']:>+7.1f}  "
                f"[{b['ci_low']:.1%},{b['ci_high']:.1%}]  "
                f"{fee_adj * 100:>+7.1f}  "
                f"{marker}"
            )

        print(f"\n  Signal bins (>3pp dev, n≥100, fee-positive): {signal_bins}")
        total_n = sum(b["n"] for b in bins)
        print(f"  Total markets in scope: {total_n:,}")


def plot_calibration(calibration: dict, output_dir: Path) -> None:
    """Generate calibration curve plots."""
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    fig.suptitle("Kalshi Calibration Curves — PIT Price at 50% Duration", fontsize=14)

    for idx, (scope_name, bins) in enumerate(calibration.items()):
        ax = axes[idx // 4][idx % 4]

        if not bins:
            ax.set_title(f"{scope_name} (no data)")
            continue

        implied = [b["implied_mid"] * 100 for b in bins]
        actual = [b["actual_rate"] * 100 for b in bins]
        ci_low = [b["ci_low"] * 100 for b in bins]
        ci_high = [b["ci_high"] * 100 for b in bins]
        n_vals = [b["n"] for b in bins]

        ax.plot([0, 100], [0, 100], "k--", alpha=0.3, label="Perfect calibration")
        ax.errorbar(
            implied, actual,
            yerr=[
                [a - cl for a, cl in zip(actual, ci_low)],
                [ch - a for a, ch in zip(actual, ci_high)],
            ],
            fmt="o-", capsize=3, markersize=4, label="Observed",
        )

        significant = [
            (im, ac) for im, ac, n_val in zip(implied, actual, n_vals)
            if n_val >= 100 and abs(ac - im) > 3
        ]
        if significant:
            ax.scatter(
                [s[0] for s in significant],
                [s[1] for s in significant],
                color="red", s=60, zorder=5, label=">3pp deviation",
            )

        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("Implied probability (%)")
        ax.set_ylabel("Actual resolution rate (%)")
        total_n = sum(n_vals)
        ax.set_title(f"{scope_name} (n={total_n:,})")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = output_dir / "calibration_curves.png"
    fig.savefig(plot_path, dpi=150)
    print(f"\nPlot saved to {plot_path}")
    plt.close()


def go_no_go_decision(calibration: dict) -> None:
    """Apply go/no-go criteria from the deep-dive doc."""
    print("\n" + "=" * 80)
    print("  GO / NO-GO DECISION")
    print("=" * 80)

    agg = calibration.get("aggregate", [])
    signal_bins = []
    for b in agg:
        fee_adj = compute_fee_adjusted_edge(b["implied_mid"], b["actual_rate"])
        if b["n"] >= 100 and abs(b["deviation_pp"]) > 3 and fee_adj > 0:
            signal_bins.append(b)

    print("\n  Criterion: ≥3 bins with >3pp deviation, n≥100, positive after fees")
    print(f"  Result:    {len(signal_bins)} qualifying bins found\n")

    if signal_bins:
        for b in signal_bins:
            fee_adj = compute_fee_adjusted_edge(b["implied_mid"], b["actual_rate"])
            direction = "SELL (overpriced)" if b["deviation_pp"] < 0 else "BUY (underpriced)"
            print(
                f"    Bin {b['bin_low']}-{b['bin_high']}%: "
                f"implied={b['implied_mid']:.0%}, actual={b['actual_rate']:.1%}, "
                f"dev={b['deviation_pp']:+.1f}pp, fee-adj={fee_adj * 100:+.1f}pp, "
                f"n={b['n']:,} → {direction}"
            )

    if len(signal_bins) >= 3:
        print("\n  >>> GO — Sufficient calibration signal detected.")
        print("  >>> Proceed to Phase 2: walk-forward backtest.")
    elif len(signal_bins) > 0:
        print("\n  >>> MARGINAL — Some signal detected but below threshold.")
        print("  >>> Consider category-specific strategies or relaxing criteria.")
    else:
        print("\n  >>> NO-GO — Market appears well-calibrated. No systematic edge.")
        print("  >>> Pivot to Family #10 or #12.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Kalshi calibration curve")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    args = parser.parse_args()

    if not (args.data_dir / "markets-0000.parquet").exists():
        raise FileNotFoundError(f"Markets data not found in {args.data_dir}")
    if not (args.data_dir / "trades-0000.parquet").exists():
        raise FileNotFoundError(f"Trades data not found in {args.data_dir}")

    print("Connecting to DuckDB (in-memory)...")
    con = duckdb.connect()

    print("\n--- Phase 1: PIT Price Computation ---")
    compute_pit_prices(con, args.data_dir, args.min_volume)

    print("\n--- Phase 2: Calibration Curve ---")
    calibration = build_calibration_data(con)

    print_results(calibration)
    plot_calibration(calibration, OUTPUT_DIR)
    go_no_go_decision(calibration)

    con.close()


if __name__ == "__main__":
    main()
