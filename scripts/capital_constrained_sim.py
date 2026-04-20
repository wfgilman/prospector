"""
Capital-constrained portfolio simulation for PM underwriting.

Extends the walk-forward backtest to model concurrent position exposure.
Positions are entered at PIT time and resolved at close_time. A daily capital
budget, per-event correlation cap, and per-position size limit constrain
the portfolio realistically.

Runs at multiple NAV levels to show how returns scale with capital.

Usage:
    python scripts/capital_constrained_sim.py [--data-dir DIR] [--min-volume 10]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

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

KELLY_FRACTION = 0.25
MAX_POSITION_FRAC = 0.01
MAX_EVENT_FRAC = 0.05
MIN_EDGE_PP = 2.0

NAV_LEVELS = [10_000, 50_000, 100_000]
TRADES_PER_DAY_CAPS = [20, 50, 100, None]  # None = unlimited


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
class Position:
    ticker: str
    event_ticker: str
    category: str
    pit_price: int
    result: str
    close_date: object
    side: str
    edge_pp: float
    risk_budget: float
    contracts: float
    pnl: float = 0.0


@dataclass
class DailySnapshot:
    date: object
    nav: float
    cash: float
    n_open: int
    n_entered: int
    n_skipped_capital: int
    n_skipped_event: int
    capital_utilization: float
    realized_pnl: float


@dataclass
class SimResult:
    initial_nav: float
    snapshots: list[DailySnapshot] = field(default_factory=list)
    closed_trades: list[Position] = field(default_factory=list)

    @property
    def final_nav(self) -> float:
        return self.snapshots[-1].nav if self.snapshots else self.initial_nav

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def return_pct(self) -> float:
        return (self.final_nav / self.initial_nav - 1) * 100

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        return sum(1 for t in self.closed_trades if t.pnl > 0) / len(self.closed_trades)

    @property
    def sharpe(self) -> float:
        if len(self.snapshots) < 2:
            return 0.0
        navs = [s.nav for s in self.snapshots]
        returns = np.diff(navs) / navs[:-1]
        if np.std(returns) == 0:
            return 0.0
        return float((np.mean(returns) / np.std(returns)) * np.sqrt(250))

    @property
    def max_drawdown(self) -> float:
        if not self.snapshots:
            return 0.0
        peak = self.snapshots[0].nav
        max_dd = 0.0
        for s in self.snapshots:
            peak = max(peak, s.nav)
            dd = (peak - s.nav) / peak
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def avg_utilization(self) -> float:
        if not self.snapshots:
            return 0.0
        return float(np.mean([s.capital_utilization for s in self.snapshots]))

    @property
    def avg_open(self) -> float:
        if not self.snapshots:
            return 0.0
        return float(np.mean([s.n_open for s in self.snapshots]))

    @property
    def max_open(self) -> int:
        if not self.snapshots:
            return 0
        return max(s.n_open for s in self.snapshots)

    @property
    def total_entered(self) -> int:
        return sum(s.n_entered for s in self.snapshots)

    @property
    def total_candidates(self) -> int:
        return (
            self.total_entered
            + sum(s.n_skipped_capital for s in self.snapshots)
            + sum(s.n_skipped_event for s in self.snapshots)
        )

    @property
    def trades_per_day(self) -> float:
        if not self.snapshots:
            return 0.0
        return self.total_entered / len(self.snapshots)


def load_and_split(
    con: duckdb.DuckDBPyConnection, data_dir: Path, min_volume: int
) -> str:
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
    total = con.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    print(f"  Resolved markets: {total:,}")

    print("Loading trades (filtered to resolved markets)...")
    con.execute(f"""
        CREATE TABLE trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM '{data_dir}/trades-*.parquet' t
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
    bins = curves.get(category, curves["_aggregate"])
    for b in bins:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100
            side = "sell_yes" if edge > 0 else "buy_yes"
            return abs(edge), side

    for b in curves["_aggregate"]:
        if b.bin_low <= pit_price < b.bin_high and b.n >= 50:
            edge = (b.implied_mid - b.actual_rate) * 100
            side = "sell_yes" if edge > 0 else "buy_yes"
            return abs(edge), side

    return 0.0, ""


def _compute_risk_budget(
    pit_price: int, edge_pp: float, side: str, nav: float
) -> float:
    implied = pit_price / 100
    if side == "sell_yes":
        p_true = max(0.01, min(0.99, implied - edge_pp / 100))
        kelly = (implied - p_true) / (1 - p_true)
    else:
        p_true = max(0.01, min(0.99, implied + edge_pp / 100))
        kelly = (p_true - implied) / (1 - implied)
    kelly = max(0, kelly) * KELLY_FRACTION
    return min(kelly * nav, MAX_POSITION_FRAC * nav)


def _compute_pnl(p: Position) -> float:
    if p.side == "sell_yes":
        reward_per = p.pit_price / 100
        risk_per = (100 - p.pit_price) / 100
    else:
        reward_per = (100 - p.pit_price) / 100
        risk_per = p.pit_price / 100

    if p.result == "no":
        return (
            p.contracts * reward_per
            if p.side == "sell_yes"
            else -p.contracts * risk_per
        )
    else:
        return (
            -p.contracts * risk_per
            if p.side == "sell_yes"
            else p.contracts * reward_per
        )


def simulate_constrained(
    con: duckdb.DuckDBPyConnection,
    split_time: str,
    curves: dict[str, list[CalibrationBin]],
    initial_nav: float,
    max_trades_per_day: int | None = None,
) -> SimResult:
    rows = con.execute(f"""
        SELECT ticker, event_ticker, category, pit_price, result,
               CAST(pit_time AS DATE) AS pit_date,
               CAST(close_time AS DATE) AS close_date
        FROM pit_clean
        WHERE close_time > '{split_time}'
        ORDER BY pit_time
    """).fetchall()

    candidates_by_date: dict[object, list[dict]] = defaultdict(list)
    all_dates: set[object] = set()

    for ticker, event_ticker, category, pit_price, result, pit_date, close_date in rows:
        edge_pp, side = lookup_edge(curves, category, pit_price)
        all_dates.add(pit_date)
        all_dates.add(close_date)
        if edge_pp >= MIN_EDGE_PP and side:
            candidates_by_date[pit_date].append({
                "ticker": ticker,
                "event_ticker": event_ticker,
                "category": category,
                "pit_price": pit_price,
                "result": result,
                "close_date": close_date,
                "edge_pp": edge_pp,
                "side": side,
            })

    all_dates_sorted = sorted(all_dates)

    sim = SimResult(initial_nav=initial_nav)
    cash = initial_nav
    open_positions: list[Position] = []

    for date in all_dates_sorted:
        # 1. Resolve positions with close_date <= today
        still_open = []
        daily_realized = 0.0
        for p in open_positions:
            if p.close_date <= date:
                p.pnl = _compute_pnl(p)
                cash += p.risk_budget + p.pnl
                daily_realized += p.pnl
                sim.closed_trades.append(p)
            else:
                still_open.append(p)
        open_positions = still_open

        # 2. Today's candidates sorted by edge descending (best first)
        today = sorted(
            candidates_by_date.get(date, []),
            key=lambda c: -c["edge_pp"],
        )

        # 3. Current event exposures from open positions
        event_risk: dict[str, float] = defaultdict(float)
        for p in open_positions:
            event_risk[p.event_ticker] += p.risk_budget

        n_entered = 0
        n_skip_capital = 0
        n_skip_event = 0

        for c in today:
            if max_trades_per_day and n_entered >= max_trades_per_day:
                n_skip_capital += 1
                continue

            risk_budget = _compute_risk_budget(
                c["pit_price"], c["edge_pp"], c["side"], initial_nav
            )
            if risk_budget < 0.10:
                continue

            if risk_budget > cash:
                n_skip_capital += 1
                continue

            if (
                event_risk[c["event_ticker"]] + risk_budget
                > MAX_EVENT_FRAC * initial_nav
            ):
                n_skip_event += 1
                continue

            risk_per = (
                (100 - c["pit_price"]) / 100
                if c["side"] == "sell_yes"
                else c["pit_price"] / 100
            )
            contracts = risk_budget / risk_per

            pos = Position(
                ticker=c["ticker"],
                event_ticker=c["event_ticker"],
                category=c["category"],
                pit_price=c["pit_price"],
                result=c["result"],
                close_date=c["close_date"],
                side=c["side"],
                edge_pp=c["edge_pp"],
                risk_budget=risk_budget,
                contracts=contracts,
            )
            open_positions.append(pos)
            cash -= risk_budget
            event_risk[c["event_ticker"]] += risk_budget
            n_entered += 1

        # 4. Daily snapshot
        total_committed = sum(p.risk_budget for p in open_positions)
        nav = cash + total_committed
        utilization = total_committed / nav if nav > 0 else 0

        sim.snapshots.append(DailySnapshot(
            date=date,
            nav=nav,
            cash=cash,
            n_open=len(open_positions),
            n_entered=n_entered,
            n_skipped_capital=n_skip_capital,
            n_skipped_event=n_skip_event,
            capital_utilization=utilization,
            realized_pnl=daily_realized,
        ))

    return sim


def print_comparison(results: dict[str, SimResult]) -> None:
    print("\n" + "=" * 120)
    print("  CAPITAL-CONSTRAINED SIMULATION — THROUGHPUT COMPARISON ($10K NAV)")
    print("=" * 120)

    header = (
        f"  {'Trades/d Cap':>13}  {'Return':>8}  {'Sharpe':>7}  {'MaxDD':>7}  "
        f"{'WinRate':>8}  {'Trades':>8}  {'Cands':>8}  "
        f"{'Util%':>6}  {'Avg Open':>9}  {'Max Open':>9}"
    )
    print(header)
    dividers = [13, 8, 7, 7, 8, 8, 8, 6, 9, 9]
    print("  " + "  ".join("─" * w for w in dividers))

    for label in results:
        r = results[label]
        print(
            f"  {label:>13}  "
            f"{r.return_pct:>7.1f}%  "
            f"{r.sharpe:>7.2f}  "
            f"{r.max_drawdown * 100:>6.1f}%  "
            f"{r.win_rate * 100:>7.1f}%  "
            f"{r.total_entered:>8,}  "
            f"{r.total_candidates:>8,}  "
            f"{r.avg_utilization * 100:>5.0f}%  "
            f"{r.avg_open:>9.0f}  "
            f"{r.max_open:>9,}"
        )


def print_detail(label: str, r: SimResult) -> None:
    print(f"\n  --- Detail: {label} ---")
    print(f"  Initial NAV:      ${r.initial_nav:>12,.2f}")
    print(f"  Final NAV:        ${r.final_nav:>12,.2f}")
    print(f"  Total P&L:        ${r.total_pnl:>12,.2f}")
    print(f"  Return:            {r.return_pct:>11.1f}%")
    print(f"  Sharpe:            {r.sharpe:>11.2f}")
    print(f"  Max drawdown:      {r.max_drawdown * 100:>11.1f}%")
    print(f"  Win rate:          {r.win_rate * 100:>11.1f}%")
    print(f"  Trades entered:   {r.total_entered:>12,}")
    print(f"  Skipped (capital):{sum(s.n_skipped_capital for s in r.snapshots):>12,}")
    print(f"  Skipped (event):  {sum(s.n_skipped_event for s in r.snapshots):>12,}")
    print(f"  Avg utilization:   {r.avg_utilization * 100:>11.1f}%")
    print(f"  Avg open pos:      {r.avg_open:>11.0f}")
    print(f"  Max open pos:     {r.max_open:>12,}")
    print(f"  Sim days:         {len(r.snapshots):>12,}")
    if r.snapshots:
        avg_daily_pnl = r.total_pnl / len(r.snapshots)
        print(f"  Avg daily P&L:    ${avg_daily_pnl:>12,.2f}")

    categories = sorted(set(t.category for t in r.closed_trades))
    if categories:
        print(
            f"\n  {'Category':<15} {'Trades':>8} "
            f"{'P&L':>12} {'WinRate':>8} {'AvgEdge':>8}"
        )
        print(
            f"  {'─' * 15} {'─' * 8} {'─' * 12} {'─' * 8} {'─' * 8}"
        )
        for cat in categories:
            ct = [t for t in r.closed_trades if t.category == cat]
            cat_pnl = sum(t.pnl for t in ct)
            cat_wr = sum(1 for t in ct if t.pnl > 0) / len(ct)
            cat_edge = float(np.mean([t.edge_pp for t in ct]))
            print(
                f"  {cat:<15} {len(ct):>8,} ${cat_pnl:>11,.2f} "
                f"{cat_wr * 100:>7.1f}% {cat_edge:>7.1f}pp"
            )


def plot_results(results: dict[str, SimResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        "Capital-Constrained Simulation — PM Underwriting ($10K NAV)",
        fontsize=14,
    )

    labels = list(results.keys())

    # 1. NAV curves (% return) by throughput cap
    ax = axes[0][0]
    for label in labels:
        r = results[label]
        navs = [s.nav for s in r.snapshots]
        pct = [(n / r.initial_nav - 1) * 100 for n in navs]
        ax.plot(pct, linewidth=1, label=label)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Portfolio Return (%)")
    ax.set_xlabel("Trading days")
    ax.set_ylabel("Return (%)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 2. Capital utilization (most constrained — 20/d)
    first = results[labels[0]]
    ax = axes[0][1]
    utils = [s.capital_utilization * 100 for s in first.snapshots]
    ax.plot(utils, linewidth=1, color="steelblue")
    ax.set_title(f"Capital Utilization ({labels[0]})")
    ax.set_xlabel("Trading days")
    ax.set_ylabel("Utilization (%)")
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    # 3. Open positions over time
    ax = axes[1][0]
    for label in labels:
        r = results[label]
        opens = [s.n_open for s in r.snapshots]
        ax.plot(opens, linewidth=1, label=label)
    ax.set_title("Open Positions")
    ax.set_xlabel("Trading days")
    ax.set_ylabel("Count")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 4. Daily P&L for the 20/d scenario (most realistic)
    ax = axes[1][1]
    daily_pnl = [s.realized_pnl for s in first.snapshots]
    colors = ["green" if p >= 0 else "red" for p in daily_pnl]
    ax.bar(
        range(len(daily_pnl)), daily_pnl, color=colors, alpha=0.7, width=1.0
    )
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    ax.set_title(f"Daily Realized P&L ({labels[0]})")
    ax.set_xlabel("Trading days")
    ax.set_ylabel("P&L ($)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = output_dir / "capital_constrained_sim.png"
    fig.savefig(plot_path, dpi=150)
    print(f"\nPlot saved to {plot_path}")
    plt.close()


def go_no_go(results: dict[str, SimResult]) -> None:
    print("\n" + "=" * 80)
    print("  CAPITAL-CONSTRAINED GO / NO-GO")
    print("=" * 80)

    labels = list(results.keys())
    # Evaluate the most constrained (first label, lowest throughput)
    conservative_label = labels[0]
    r = results[conservative_label]

    print(f"\n  Evaluating at most conservative throughput ({conservative_label}):")

    checks = [
        ("Sharpe > 1.0", r.sharpe > 1.0, f"{r.sharpe:.2f}"),
        ("Win rate > 50%", r.win_rate > 0.50, f"{r.win_rate:.1%}"),
        (
            "Max drawdown < 20%",
            r.max_drawdown < 0.20,
            f"{r.max_drawdown:.1%}",
        ),
        ("Positive P&L", r.total_pnl > 0, f"${r.total_pnl:,.2f}"),
        (
            "≥100 trades",
            len(r.closed_trades) >= 100,
            f"{len(r.closed_trades):,}",
        ),
    ]

    all_pass = True
    for name, passed, value in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}: {value}")

    sim_days = max(len(r.snapshots), 1)
    monthly_pnl = r.total_pnl * (30 / sim_days)
    annual_return = r.return_pct * (365 / sim_days)
    print(f"\n  Extrapolated monthly P&L on $10K: ~${monthly_pnl:,.0f}")
    print(f"  Extrapolated annual return: ~{annual_return:.0f}%")
    print(f"  Avg P&L per trade: ${r.total_pnl / max(len(r.closed_trades), 1):,.2f}")

    if all_pass:
        print("\n  >>> GO — Capital-constrained metrics pass at conservative throughput.")
        print("  >>> Proceed to Phase 3 (paper trading) with ~20 trades/day target.")
    else:
        print("\n  >>> Review failing criteria.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--min-volume", type=int, default=10)
    parser.add_argument("--nav", type=float, default=10_000.0)
    args = parser.parse_args()

    con = duckdb.connect()

    print("--- Phase 1: Data Loading & Split ---")
    split_time = load_and_split(con, args.data_dir, args.min_volume)

    print("\n--- Phase 2: Train Calibration Curves ---")
    curves = build_calibration(con, split_time)
    for cat, bins in sorted(curves.items()):
        total_n = sum(b.n for b in bins)
        sig = sum(
            1
            for b in bins
            if b.n >= 50 and abs(b.actual_rate - b.implied_mid) * 100 > 3
        )
        print(f"  {cat:<15} bins={len(bins):>2}  train_n={total_n:>8,}  signal={sig}")

    print("\n--- Phase 3: Capital-Constrained Simulation ---")
    print(f"  Base NAV: ${args.nav:,.0f}")
    print(f"  Throughput caps: {TRADES_PER_DAY_CAPS}")

    results: dict[str, SimResult] = {}
    for cap in TRADES_PER_DAY_CAPS:
        label = f"{cap}/day" if cap else "unlimited"
        print(f"\n  Simulating {label}...")
        r = simulate_constrained(
            con, split_time, curves, args.nav, max_trades_per_day=cap
        )
        results[label] = r
        print(
            f"    Entered {r.total_entered:,} / {r.total_candidates:,} "
            f"candidates, util={r.avg_utilization:.1%}"
        )

    print_comparison(results)
    for label in results:
        print_detail(label, results[label])
    plot_results(results, OUTPUT_DIR)
    go_no_go(results)

    con.close()


if __name__ == "__main__":
    main()
