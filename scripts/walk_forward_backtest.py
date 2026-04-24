"""
Walk-forward backtest for the prediction market underwriting strategy.

Splits resolved Kalshi markets into train (70%) and test (30%) by close_time.
Builds per-category calibration curves on the train set, then simulates a
portfolio on the test set using fractional Kelly sizing and maker-order pricing.

Usage:
    python scripts/walk_forward_backtest.py [--data-dir DIR] [--min-volume 10]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

# Unified tree (post-TrevorJS-migration). Prices cast to int-cents in the
# trades SQL to preserve downstream 0-100 semantics.
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "kalshi"
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

KELLY_FRACTION = 0.25
MAX_POSITION_FRAC = 0.01  # 1% of NAV per position
MIN_EDGE_PP = 2.0  # minimum edge in pp to trade
INITIAL_NAV = 10_000.0


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


@dataclass
class Trade:
    ticker: str
    category: str
    pit_price: int  # 1-99 cents
    result: str  # 'yes' or 'no'
    close_time: str
    side: str = ""  # 'sell_yes' or 'buy_yes'
    edge: float = 0.0
    size_dollars: float = 0.0
    pnl: float = 0.0


@dataclass
class PortfolioStats:
    trades: list[Trade] = field(default_factory=list)
    nav_series: list[float] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades)

    @property
    def sharpe(self) -> float:
        if len(self.nav_series) < 2:
            return 0.0
        returns = np.diff(self.nav_series) / self.nav_series[:-1]
        if np.std(returns) == 0:
            return 0.0
        # Annualize: assume ~250 trading days
        daily_sharpe = np.mean(returns) / np.std(returns)
        return daily_sharpe * np.sqrt(250)

    @property
    def max_drawdown(self) -> float:
        if not self.nav_series:
            return 0.0
        peak = self.nav_series[0]
        max_dd = 0.0
        for nav in self.nav_series:
            peak = max(peak, nav)
            dd = (peak - nav) / peak
            max_dd = max(max_dd, dd)
        return max_dd


def load_and_split(
    con: duckdb.DuckDBPyConnection, data_dir: Path, min_volume: int
) -> str:
    """Load data, compute PIT prices, split 70/30 by close_time."""

    print("Loading markets...")
    con.execute(f"""
        CREATE TABLE markets AS
        SELECT ticker, event_ticker, result, volume, open_time, close_time,
               open_time + (close_time - open_time) / 2 AS pit_time,
               {CATEGORY_SQL} AS category
        FROM '{data_dir}/markets/date=*/part.parquet'
        WHERE result IN ('yes', 'no')
          AND volume >= {min_volume}
          AND close_time > open_time
    """)
    total = con.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"  Resolved markets: {total:,}")

    print("Loading trades (filtered to resolved markets)...")
    con.execute(f"""
        CREATE TABLE trades AS
        SELECT
            t.ticker,
            CAST(t.yes_price * 100 AS INTEGER) AS yes_price,
            t.created_time
        FROM '{data_dir}/trades/date=*/part.parquet' t
        SEMI JOIN markets m ON t.ticker = m.ticker
        ORDER BY t.ticker, t.created_time
    """)
    trade_n = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"  Matching trades: {trade_n:,}")

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
        WHERE offset_frac <= 0.25
          AND pit_price BETWEEN 1 AND 99
    """)
    clean_n = con.execute("SELECT COUNT(*) FROM pit_clean").fetchone()[0]
    print(f"  PIT-priced markets (offset ≤25%): {clean_n:,}")

    # Find the 70% split point by close_time
    split_time = con.execute("""
        SELECT close_time FROM (
            SELECT close_time,
                   ROW_NUMBER() OVER (ORDER BY close_time) AS rn,
                   COUNT(*) OVER () AS total
            FROM pit_clean
        )
        WHERE rn = CAST(FLOOR(total * 0.7) AS INTEGER)
    """).fetchone()[0]
    split_str = str(split_time)
    print(f"  Train/test split at: {split_str}")

    train_n = con.execute(
        f"SELECT COUNT(*) FROM pit_clean WHERE close_time <= '{split_str}'"
    ).fetchone()[0]
    test_n = con.execute(
        f"SELECT COUNT(*) FROM pit_clean WHERE close_time > '{split_str}'"
    ).fetchone()[0]
    print(f"  Train: {train_n:,}  Test: {test_n:,}")

    return split_str


def build_calibration(
    con: duckdb.DuckDBPyConnection, split_time: str
) -> dict[str, list[CalibrationBin]]:
    """Build per-category calibration curves from train set only."""

    categories = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT category FROM pit_clean ORDER BY category"
        ).fetchall()
    ]

    curves: dict[str, list[CalibrationBin]] = {}
    for cat in categories:
        rows = con.execute(f"""
            SELECT FLOOR(pit_price / 5) * 5 AS bin_low,
                   FLOOR(pit_price / 5) * 5 + 5 AS bin_high,
                   COUNT(*) AS n,
                   SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) AS yes_n
            FROM pit_clean
            WHERE close_time <= '{split_time}' AND category = '{cat}'
            GROUP BY bin_low, bin_high
            ORDER BY bin_low
        """).fetchall()
        curves[cat] = [
            CalibrationBin(int(r[0]), int(r[1]), r[2], r[3]) for r in rows
        ]

    # Also build aggregate curve
    rows = con.execute(f"""
        SELECT FLOOR(pit_price / 5) * 5 AS bin_low,
               FLOOR(pit_price / 5) * 5 + 5 AS bin_high,
               COUNT(*) AS n,
               SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) AS yes_n
        FROM pit_clean
        WHERE close_time <= '{split_time}'
        GROUP BY bin_low, bin_high
        ORDER BY bin_low
    """).fetchall()
    curves["_aggregate"] = [
        CalibrationBin(int(r[0]), int(r[1]), r[2], r[3]) for r in rows
    ]

    return curves


def lookup_edge(
    curves: dict[str, list[CalibrationBin]], category: str, pit_price: int
) -> tuple[float, str]:
    """Look up the calibration edge for a given category and price.

    Returns (edge_pp, side) where side is 'sell_yes' if market overprices
    (actual < implied) or 'buy_yes' if market underprices.
    Falls back to aggregate curve if category has insufficient data.
    """
    bins = curves.get(category, curves["_aggregate"])

    for b in bins:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100  # positive = overpriced
            side = "sell_yes" if edge > 0 else "buy_yes"
            return abs(edge), side

    # Fallback to aggregate
    for b in curves["_aggregate"]:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100
            side = "sell_yes" if edge > 0 else "buy_yes"
            return abs(edge), side

    return 0.0, ""


def simulate_portfolio(
    con: duckdb.DuckDBPyConnection,
    split_time: str,
    curves: dict[str, list[CalibrationBin]],
) -> PortfolioStats:
    """Simulate the portfolio on the test set."""

    # Fetch test-set markets ordered by close_time
    test_markets = con.execute(f"""
        SELECT ticker, category, pit_price, result,
               strftime(close_time, '%Y-%m-%d') AS close_date
        FROM pit_clean
        WHERE close_time > '{split_time}'
        ORDER BY close_time
    """).fetchall()

    stats = PortfolioStats()
    nav = INITIAL_NAV
    stats.nav_series.append(nav)
    current_date = None

    for row in test_markets:
        ticker, category, pit_price, result, close_date = row

        # Track daily NAV
        if close_date != current_date:
            if current_date is not None:
                stats.nav_series.append(nav)
            current_date = close_date

        edge_pp, side = lookup_edge(curves, category, pit_price)
        if edge_pp < MIN_EDGE_PP or not side:
            continue

        # Kelly sizing (flat: use initial NAV to isolate edge from compounding)
        implied = pit_price / 100
        if side == "sell_yes":
            p_true = max(0.01, min(0.99, implied - edge_pp / 100))
            kelly = (implied - p_true) / (1 - p_true)
        else:
            p_true = max(0.01, min(0.99, implied + edge_pp / 100))
            kelly = (p_true - implied) / (1 - implied)

        kelly = max(0, kelly) * KELLY_FRACTION
        # position_size = max amount at risk (max loss on this trade)
        risk_budget = min(kelly * INITIAL_NAV, MAX_POSITION_FRAC * INITIAL_NAV)

        if risk_budget < 0.10:
            continue

        # Contracts: risk_budget / risk_per_contract
        if side == "sell_yes":
            risk_per_contract = (100 - pit_price) / 100
            reward_per_contract = pit_price / 100
        else:
            risk_per_contract = pit_price / 100
            reward_per_contract = (100 - pit_price) / 100

        contracts = risk_budget / risk_per_contract

        if result == "no":
            pnl = contracts * reward_per_contract if side == "sell_yes" \
                else -contracts * risk_per_contract
        else:
            pnl = -contracts * risk_per_contract if side == "sell_yes" \
                else contracts * reward_per_contract

        nav += pnl

        trade = Trade(
            ticker=ticker,
            category=category,
            pit_price=pit_price,
            result=result,
            close_time=close_date,
            side=side,
            edge=edge_pp,
            size_dollars=risk_budget,
            pnl=pnl,
        )
        stats.trades.append(trade)

    stats.nav_series.append(nav)
    return stats


def print_results(stats: PortfolioStats, curves: dict) -> None:
    """Print backtest results."""

    print("\n" + "=" * 80)
    print("  WALK-FORWARD BACKTEST RESULTS")
    print("=" * 80)

    print(f"\n  Initial NAV:    ${INITIAL_NAV:>12,.2f}")
    print(f"  Final NAV:      ${stats.nav_series[-1]:>12,.2f}")
    print(f"  Total P&L:      ${stats.total_pnl:>12,.2f}")
    print(
        f"  Return:          {(stats.nav_series[-1] / INITIAL_NAV - 1) * 100:>11.1f}%"
    )
    print(f"  Total trades:   {len(stats.trades):>12,}")
    print(f"  Win rate:        {stats.win_rate * 100:>11.1f}%")
    print(f"  Sharpe ratio:    {stats.sharpe:>11.2f}")
    print(f"  Max drawdown:    {stats.max_drawdown * 100:>11.1f}%")

    # Per-category breakdown
    categories = sorted(set(t.category for t in stats.trades))
    print(f"\n  {'Category':<15} {'Trades':>8} {'P&L':>12} {'WinRate':>8} {'AvgEdge':>8}")
    print(f"  {'─' * 15} {'─' * 8} {'─' * 12} {'─' * 8} {'─' * 8}")

    for cat in categories:
        cat_trades = [t for t in stats.trades if t.category == cat]
        cat_pnl = sum(t.pnl for t in cat_trades)
        cat_wr = sum(1 for t in cat_trades if t.pnl > 0) / len(cat_trades)
        cat_edge = np.mean([t.edge for t in cat_trades])
        print(
            f"  {cat:<15} {len(cat_trades):>8,} ${cat_pnl:>11,.2f} "
            f"{cat_wr * 100:>7.1f}% {cat_edge:>7.1f}pp"
        )

    # Side breakdown
    sell_trades = [t for t in stats.trades if t.side == "sell_yes"]
    buy_trades = [t for t in stats.trades if t.side == "buy_yes"]
    print(f"\n  Sell-yes trades: {len(sell_trades):,} "
          f"(P&L: ${sum(t.pnl for t in sell_trades):,.2f})")
    print(f"  Buy-yes trades:  {len(buy_trades):,} "
          f"(P&L: ${sum(t.pnl for t in buy_trades):,.2f})")

    # Calibration accuracy: predicted vs actual hit rates
    print("\n  Calibration accuracy (test set):")
    print(f"  {'Bin':>7}  {'N':>8}  {'Train Cal':>10}  {'Test Actual':>12}  {'Gap':>6}")
    print(f"  {'─' * 7}  {'─' * 8}  {'─' * 10}  {'─' * 12}  {'─' * 6}")

    agg_bins = curves.get("_aggregate", [])
    traded_by_bin: dict[str, list[Trade]] = {}
    for t in stats.trades:
        bin_key = f"{(t.pit_price // 5) * 5}-{(t.pit_price // 5) * 5 + 5}"
        traded_by_bin.setdefault(bin_key, []).append(t)

    for b in agg_bins:
        key = f"{b.bin_low}-{b.bin_high}"
        if key in traded_by_bin:
            trades_in_bin = traded_by_bin[key]
            test_yes = sum(1 for t in trades_in_bin if t.result == "yes")
            test_actual = test_yes / len(trades_in_bin)
            gap = (test_actual - b.actual_rate) * 100
            print(
                f"  {key:>7}  {len(trades_in_bin):>8,}  "
                f"{b.actual_rate:>9.1%}  {test_actual:>11.1%}  "
                f"{gap:>+5.1f}"
            )


def plot_results(stats: PortfolioStats, output_dir: Path) -> None:
    """Generate backtest result plots."""
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Walk-Forward Backtest — PM Underwriting", fontsize=14)

    # 1. NAV curve
    ax = axes[0][0]
    ax.plot(stats.nav_series, linewidth=1)
    ax.axhline(y=INITIAL_NAV, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Portfolio NAV")
    ax.set_xlabel("Trading days")
    ax.set_ylabel("NAV ($)")
    ax.grid(True, alpha=0.3)

    # 2. Cumulative P&L by category
    ax = axes[0][1]
    categories = sorted(set(t.category for t in stats.trades))
    for cat in categories:
        cat_trades = [t for t in stats.trades if t.category == cat]
        cum_pnl = np.cumsum([t.pnl for t in cat_trades])
        ax.plot(cum_pnl, label=cat, linewidth=1)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Cumulative P&L by Category")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative P&L ($)")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    # 3. P&L distribution
    ax = axes[1][0]
    pnls = [t.pnl for t in stats.trades]
    ax.hist(pnls, bins=100, edgecolor="none", alpha=0.7)
    ax.axvline(x=0, color="red", linestyle="--", alpha=0.5)
    ax.set_title(f"P&L Distribution (n={len(pnls):,})")
    ax.set_xlabel("P&L per trade ($)")
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.3)

    # 4. Monthly P&L
    ax = axes[1][1]
    monthly: dict[str, float] = {}
    for t in stats.trades:
        month = t.close_time[:7]
        monthly[month] = monthly.get(month, 0) + t.pnl
    months = sorted(monthly.keys())
    vals = [monthly[m] for m in months]
    colors = ["green" if v >= 0 else "red" for v in vals]
    ax.bar(range(len(months)), vals, color=colors, alpha=0.7)
    ax.set_xticks(range(0, len(months), max(1, len(months) // 8)))
    ax.set_xticklabels(
        [months[i] for i in range(0, len(months), max(1, len(months) // 8))],
        rotation=45, fontsize=7,
    )
    ax.set_title("Monthly P&L")
    ax.set_ylabel("P&L ($)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = output_dir / "walk_forward_backtest.png"
    fig.savefig(plot_path, dpi=150)
    print(f"\nPlot saved to {plot_path}")
    plt.close()


def go_no_go(stats: PortfolioStats) -> None:
    """Apply go/no-go criteria."""
    print("\n" + "=" * 80)
    print("  GO / NO-GO DECISION (Phase 2)")
    print("=" * 80)

    checks = [
        ("Sharpe > 1.0", stats.sharpe > 1.0, f"{stats.sharpe:.2f}"),
        ("Win rate > 50%", stats.win_rate > 0.50, f"{stats.win_rate:.1%}"),
        (
            "Max drawdown < 20%",
            stats.max_drawdown < 0.20,
            f"{stats.max_drawdown:.1%}",
        ),
        ("Positive total P&L", stats.total_pnl > 0, f"${stats.total_pnl:,.2f}"),
        ("≥100 trades", len(stats.trades) >= 100, f"{len(stats.trades):,}"),
    ]

    all_pass = True
    for name, passed, value in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {value}")

    if all_pass:
        print("\n  >>> GO — All criteria met. Proceed to Phase 3 (paper trading).")
    else:
        print("\n  >>> Review failing criteria before proceeding.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    args = parser.parse_args()

    con = duckdb.connect()

    print("--- Phase 1: Data Loading & Split ---")
    split_time = load_and_split(con, args.data_dir, args.min_volume)

    print("\n--- Phase 2: Train Calibration Curves ---")
    curves = build_calibration(con, split_time)
    for cat, bins in sorted(curves.items()):
        total_n = sum(b.n for b in bins)
        sig_bins = sum(
            1 for b in bins
            if b.n >= 50 and abs(b.actual_rate - b.implied_mid) * 100 > 3
        )
        print(f"  {cat:<15} bins={len(bins):>2}  train_n={total_n:>8,}  signal={sig_bins}")

    print("\n--- Phase 3: Portfolio Simulation ---")
    portfolio = simulate_portfolio(con, split_time, curves)

    print_results(portfolio, curves)
    plot_results(portfolio, OUTPUT_DIR)
    go_no_go(portfolio)

    con.close()


if __name__ == "__main__":
    main()
