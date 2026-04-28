"""
Elder templates — Bayesian (GP + EI) parameter search.

Reformulates candidate 00 (LLM-as-optimizer) as candidate 15 with a Gaussian
process surrogate + Expected Improvement acquisition replacing the LLM
proposal loop. Same templates, same securities, same scoring harness, same
walk-forward validator — only the proposer changes.

Pre-registered configuration (locked per docs/rd/candidates/15-…):
    Surrogate         : Matern 5/2 GP
    Acquisition       : Expected Improvement, xi=0.01
    Initial random    : 20
    Total budget      : 200 evaluations per template
    Search space      : 6-D per template, identical structure across templates
    Templates         : false_breakout, triple_screen
    Universe          : BTC-PERP, ETH-PERP, SOL-PERP

Usage:
    python scripts/elder_bayesian_search.py --template false_breakout
    python scripts/elder_bayesian_search.py --template triple_screen
    python scripts/elder_bayesian_search.py --template both

Output is written to data/prospector_bayesian.db with the same `runs` schema
as data/prospector_oracle.db, so scripts/walk_forward_top_configs.py works
against the new DB unchanged.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from skopt import gp_minimize
from skopt.space import Categorical, Integer, Real

from prospector.harness.engine import run_backtest
from prospector.templates import (
    channel_fade,
    ema_divergence,
    false_breakout,
    impulse_system,
    kangaroo_tail,
    triple_screen,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OHLCV_DIR = REPO_ROOT / "data" / "ohlcv"
DEFAULT_DB = REPO_ROOT / "data" / "prospector_bayesian.db"

SECURITIES = ["BTC-PERP", "ETH-PERP", "SOL-PERP"]

# Sentinel objective values for the optimizer. We minimize objective; smaller
# is better. Scored runs use -score so best score → lowest objective.
OBJ_CATASTROPHIC = 1_000.0   # matches harness's -1000 score floor
OBJ_REJECTED = 10_000.0      # worse than catastrophic — config never even
                             # produced enough trades to score


# ---------------------------------------------------------------------------
# Pre-registered search spaces (LOCKED — do not change without a new candidate
# id and decision-log entry; sweeping spaces re-introduces selection bias).
# ---------------------------------------------------------------------------

FALSE_BREAKOUT_SPACE = [
    Categorical(["1h", "4h", "1d"], name="timeframe"),
    Integer(15, 60, name="range_lookback"),
    Real(0.01, 0.10, name="range_threshold"),
    Integer(1, 3, name="confirmation_bars"),
    Categorical([False, True], name="volume_filter"),
    Categorical(SECURITIES, name="security"),
]

# Triple screen: long_tf locked at "1d" (dominant choice in oracle baseline)
# to keep the space at 6-D. fast_ema < slow_ema constraint is enforced as a
# rejection at evaluation time (matches the oracle's implicit rejection of
# invalid LLM proposals — apples-to-apples).
TRIPLE_SCREEN_SPACE = [
    Categorical(["4h", "1h"], name="short_tf"),
    Integer(15, 50, name="slow_ema"),
    Integer(5, 25, name="fast_ema"),
    Categorical(["stochastic", "rsi", "force_index_2"], name="oscillator"),
    Real(0.0, 100.0, name="osc_entry_threshold"),
    Categorical(SECURITIES, name="security"),
]

IMPULSE_SYSTEM_SPACE = [
    Categorical(["1h", "4h", "1d"], name="timeframe"),
    Integer(8, 30, name="ema_period"),
    Integer(6, 18, name="macd_fast"),
    Integer(20, 40, name="macd_slow"),
    Integer(5, 15, name="macd_signal"),
    Categorical(SECURITIES, name="security"),
]

CHANNEL_FADE_SPACE = [
    Categorical(["1h", "4h", "1d"], name="timeframe"),
    Integer(15, 60, name="ema_period"),
    Real(0.01, 0.10, name="channel_coefficient"),
    Categorical(["rsi", "macd_hist", "force_index_2"], name="confirmation"),
    Integer(5, 30, name="divergence_lookback"),
    Categorical(SECURITIES, name="security"),
]

KANGAROO_TAIL_SPACE = [
    Categorical(["1h", "4h", "1d"], name="timeframe"),
    Real(1.5, 4.0, name="tail_multiplier"),
    Integer(10, 30, name="context_bars"),
    Integer(1, 3, name="entry_lag"),
    Real(0.3, 1.0, name="target_multiplier"),
    Categorical(SECURITIES, name="security"),
]

EMA_DIVERGENCE_SPACE = [
    Categorical(["1h", "4h", "1d"], name="timeframe"),
    Integer(15, 50, name="ema_period"),
    Categorical(["rsi", "macd_hist", "force_index_2"], name="oscillator"),
    Integer(10, 50, name="divergence_lookback"),
    Integer(3, 15, name="min_separation"),
    Categorical(SECURITIES, name="security"),
]

SPACES = {
    "false_breakout": FALSE_BREAKOUT_SPACE,
    "triple_screen": TRIPLE_SCREEN_SPACE,
    "impulse_system": IMPULSE_SYSTEM_SPACE,
    "channel_fade": CHANNEL_FADE_SPACE,
    "kangaroo_tail": KANGAROO_TAIL_SPACE,
    "ema_divergence": EMA_DIVERGENCE_SPACE,
}


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> None:
    """Create the runs table if absent. Schema mirrors prospector_oracle.db."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp               TEXT    NOT NULL,
            validation_status       TEXT    NOT NULL,
            template                TEXT,
            config_json             TEXT,
            securities_json         TEXT,
            rationale               TEXT,
            thinking                TEXT,
            backtest_status         TEXT,
            score                   REAL,
            n_trades                INTEGER,
            pct_return              REAL,
            max_drawdown            REAL,
            profit_factor           REAL,
            win_rate                REAL,
            sharpe_ratio            REAL,
            rejection_reason        TEXT,
            securities_results_json TEXT,
            error                   TEXT
        )
    """)
    con.commit()
    con.close()


def insert_run(db_path: Path, row: dict) -> int:
    con = sqlite3.connect(db_path)
    cur = con.execute(
        """
        INSERT INTO runs (
            timestamp, validation_status, template, config_json, securities_json,
            rationale, thinking, backtest_status, score, n_trades, pct_return,
            max_drawdown, profit_factor, win_rate, sharpe_ratio, rejection_reason,
            securities_results_json, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["timestamp"], row["validation_status"], row["template"],
            row["config_json"], row["securities_json"], row.get("rationale"),
            row.get("thinking"), row["backtest_status"], row.get("score"),
            row.get("n_trades"), row.get("pct_return"), row.get("max_drawdown"),
            row.get("profit_factor"), row.get("win_rate"),
            row.get("sharpe_ratio"), row.get("rejection_reason"),
            row.get("securities_results_json"), row.get("error"),
        ),
    )
    run_id = cur.lastrowid
    con.commit()
    con.close()
    return run_id


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _coin(sec: str) -> str:
    return sec.replace("-", "_")


def _load_ohlcv(coin: str, tf: str) -> pd.DataFrame:
    path = OHLCV_DIR / coin / f"{tf}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OHLCV data not found: {path}")
    return pd.read_parquet(path)


@dataclass
class EvalResult:
    objective: float
    backtest_status: str
    score: float | None
    n_trades: int
    pct_return: float | None
    max_drawdown: float | None
    profit_factor: float | None
    win_rate: float | None
    sharpe_ratio: float | None
    rejection_reason: str | None
    error: str | None


def evaluate_false_breakout(point: list) -> tuple[EvalResult, dict, str]:
    """Run one false_breakout config; return (eval, params, security)."""
    timeframe, range_lookback, range_threshold, confirmation_bars, volume_filter, security = point
    params = {
        "timeframe": str(timeframe),
        "range_lookback": int(range_lookback),
        "range_threshold": float(range_threshold),
        "confirmation_bars": int(confirmation_bars),
        "volume_filter": bool(volume_filter),
    }
    try:
        df = _load_ohlcv(_coin(str(security)), str(timeframe))
        signals = false_breakout.run(df, params)
        result = run_backtest(signals, df)
    except Exception as exc:  # noqa: BLE001 — surface any harness error
        return (
            EvalResult(
                objective=OBJ_REJECTED,
                backtest_status="error",
                score=None, n_trades=0,
                pct_return=None, max_drawdown=None,
                profit_factor=None, win_rate=None, sharpe_ratio=None,
                rejection_reason=None, error=str(exc),
            ),
            params, str(security),
        )
    return _result_to_eval(result), params, str(security)


def evaluate_triple_screen(point: list) -> tuple[EvalResult, dict, str]:
    """Run one triple_screen config; return (eval, params, security)."""
    short_tf, slow_ema, fast_ema, oscillator, osc_entry_threshold, security = point
    params = {
        "long_tf": "1d",
        "short_tf": str(short_tf),
        "slow_ema": int(slow_ema),
        "fast_ema": int(fast_ema),
        "oscillator": str(oscillator),
        "osc_entry_threshold": float(osc_entry_threshold),
    }
    if int(fast_ema) >= int(slow_ema):
        return (
            EvalResult(
                objective=OBJ_REJECTED,
                backtest_status="rejected",
                score=None, n_trades=0,
                pct_return=None, max_drawdown=None,
                profit_factor=None, win_rate=None, sharpe_ratio=None,
                rejection_reason="fast_ema >= slow_ema",
                error=None,
            ),
            params, str(security),
        )
    try:
        df_long = _load_ohlcv(_coin(str(security)), params["long_tf"])
        df_short = _load_ohlcv(_coin(str(security)), params["short_tf"])
        signals = triple_screen.run(df_long, df_short, params)
        result = run_backtest(signals, df_short)
    except Exception as exc:  # noqa: BLE001
        return (
            EvalResult(
                objective=OBJ_REJECTED,
                backtest_status="error",
                score=None, n_trades=0,
                pct_return=None, max_drawdown=None,
                profit_factor=None, win_rate=None, sharpe_ratio=None,
                rejection_reason=None, error=str(exc),
            ),
            params, str(security),
        )
    return _result_to_eval(result), params, str(security)


def _result_to_eval(r) -> EvalResult:
    if r.status == "scored":
        return EvalResult(
            objective=-float(r.score),
            backtest_status="scored",
            score=float(r.score),
            n_trades=int(r.n_trades),
            pct_return=float(r.pct_return),
            max_drawdown=float(r.max_drawdown),
            profit_factor=float(r.profit_factor) if r.profit_factor != float("inf") else None,
            win_rate=float(r.win_rate),
            sharpe_ratio=float(r.sharpe_ratio),
            rejection_reason=None,
            error=None,
        )
    if r.status == "catastrophic":
        return EvalResult(
            objective=OBJ_CATASTROPHIC,
            backtest_status="catastrophic",
            score=-1000.0,
            n_trades=int(r.n_trades),
            pct_return=float(r.pct_return),
            max_drawdown=float(r.max_drawdown),
            profit_factor=None, win_rate=None, sharpe_ratio=None,
            rejection_reason=r.rejection_reason, error=None,
        )
    # rejected
    return EvalResult(
        objective=OBJ_REJECTED,
        backtest_status="rejected",
        score=None,
        n_trades=int(r.n_trades),
        pct_return=None, max_drawdown=None,
        profit_factor=None, win_rate=None, sharpe_ratio=None,
        rejection_reason=r.rejection_reason, error=None,
    )


def _evaluate_single_tf(
    template_module, params: dict, security: str, timeframe: str,
) -> EvalResult:
    """Run a single-timeframe template + backtest and convert to EvalResult."""
    try:
        df = _load_ohlcv(_coin(security), timeframe)
        signals = template_module.run(df, params)
        result = run_backtest(signals, df)
    except Exception as exc:  # noqa: BLE001
        return EvalResult(
            objective=OBJ_REJECTED,
            backtest_status="error",
            score=None, n_trades=0,
            pct_return=None, max_drawdown=None,
            profit_factor=None, win_rate=None, sharpe_ratio=None,
            rejection_reason=None, error=str(exc),
        )
    return _result_to_eval(result)


def evaluate_impulse_system(point: list) -> tuple[EvalResult, dict, str]:
    timeframe, ema_period, macd_fast, macd_slow, macd_signal, security = point
    params = {
        "timeframe": str(timeframe),
        "ema_period": int(ema_period),
        "macd_fast": int(macd_fast),
        "macd_slow": int(macd_slow),
        "macd_signal": int(macd_signal),
    }
    if int(macd_fast) >= int(macd_slow):
        return (
            EvalResult(
                objective=OBJ_REJECTED, backtest_status="rejected",
                score=None, n_trades=0,
                pct_return=None, max_drawdown=None,
                profit_factor=None, win_rate=None, sharpe_ratio=None,
                rejection_reason="macd_fast >= macd_slow", error=None,
            ),
            params, str(security),
        )
    return (
        _evaluate_single_tf(impulse_system, params, str(security), str(timeframe)),
        params, str(security),
    )


def evaluate_channel_fade(point: list) -> tuple[EvalResult, dict, str]:
    timeframe, ema_period, channel_coefficient, confirmation, divergence_lookback, security = point
    params = {
        "timeframe": str(timeframe),
        "ema_period": int(ema_period),
        "channel_coefficient": float(channel_coefficient),
        "confirmation": str(confirmation),
        "divergence_lookback": int(divergence_lookback),
    }
    return (
        _evaluate_single_tf(channel_fade, params, str(security), str(timeframe)),
        params, str(security),
    )


def evaluate_kangaroo_tail(point: list) -> tuple[EvalResult, dict, str]:
    timeframe, tail_multiplier, context_bars, entry_lag, target_multiplier, security = point
    params = {
        "timeframe": str(timeframe),
        "tail_multiplier": float(tail_multiplier),
        "context_bars": int(context_bars),
        "entry_lag": int(entry_lag),
        "target_multiplier": float(target_multiplier),
    }
    return (
        _evaluate_single_tf(kangaroo_tail, params, str(security), str(timeframe)),
        params, str(security),
    )


def evaluate_ema_divergence(point: list) -> tuple[EvalResult, dict, str]:
    timeframe, ema_period, oscillator, divergence_lookback, min_separation, security = point
    params = {
        "timeframe": str(timeframe),
        "ema_period": int(ema_period),
        "oscillator": str(oscillator),
        "divergence_lookback": int(divergence_lookback),
        "min_separation": int(min_separation),
    }
    return (
        _evaluate_single_tf(ema_divergence, params, str(security), str(timeframe)),
        params, str(security),
    )


EVALUATORS = {
    "false_breakout": evaluate_false_breakout,
    "triple_screen": evaluate_triple_screen,
    "impulse_system": evaluate_impulse_system,
    "channel_fade": evaluate_channel_fade,
    "kangaroo_tail": evaluate_kangaroo_tail,
    "ema_divergence": evaluate_ema_divergence,
}


# ---------------------------------------------------------------------------
# Search loop
# ---------------------------------------------------------------------------

def run_search(
    template: str,
    db_path: Path,
    n_init: int,
    n_total: int,
    seed: int,
    console: Console,
) -> None:
    space = SPACES[template]
    evaluator = EVALUATORS[template]

    console.print(
        f"\n[bold green]Bayesian search[/bold green]  "
        f"template=[cyan]{template}[/cyan]  "
        f"n_init={n_init}  n_total={n_total}  seed={seed}"
    )

    eval_count = {"n": 0}
    started = time.time()

    def objective(point: list) -> float:
        eval_result, params, security = evaluator(point)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cfg = {
            "template": template,
            "params": params,
            "securities": [security],
            "rationale": f"Bayesian (GP+EI) eval #{eval_count['n'] + 1}",
            "optimizer": "bayesian_gp_ei",
            "seed": seed,
        }
        insert_run(db_path, {
            "timestamp": ts,
            "validation_status": "valid",
            "template": template,
            "config_json": json.dumps(cfg),
            "securities_json": json.dumps([security]),
            "rationale": cfg["rationale"],
            "thinking": None,
            "backtest_status": eval_result.backtest_status,
            "score": eval_result.score,
            "n_trades": eval_result.n_trades,
            "pct_return": eval_result.pct_return,
            "max_drawdown": eval_result.max_drawdown,
            "profit_factor": eval_result.profit_factor,
            "win_rate": eval_result.win_rate,
            "sharpe_ratio": eval_result.sharpe_ratio,
            "rejection_reason": eval_result.rejection_reason,
            "securities_results_json": None,
            "error": eval_result.error,
        })
        eval_count["n"] += 1
        if eval_count["n"] % 20 == 0 or eval_count["n"] == 1:
            elapsed = time.time() - started
            console.print(
                f"  eval {eval_count['n']:>3}/{n_total}  "
                f"status={eval_result.backtest_status:<13} "
                f"score={eval_result.score if eval_result.score is not None else '-':>8}  "
                f"sec={security:<8}  elapsed={elapsed:>5.0f}s"
            )
        return eval_result.objective

    # gp_minimize with EI acquisition.
    gp_minimize(
        objective,
        space,
        n_calls=n_total,
        n_initial_points=n_init,
        acq_func="EI",
        xi=0.01,
        random_state=seed,
        verbose=False,
    )

    elapsed = time.time() - started
    console.print(f"  [green]done[/green] in {elapsed:.0f}s")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report_summary(db_path: Path, console: Console) -> None:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT template, backtest_status, score, n_trades, config_json "
        "FROM runs ORDER BY run_id"
    ).fetchall()
    con.close()
    if not rows:
        console.print("[yellow]no rows in DB[/yellow]")
        return

    by_template: dict[str, list[tuple[str, float | None, int, str]]] = {}
    for tmpl, status, score, n, cfg in rows:
        by_template.setdefault(tmpl, []).append((status, score, n, cfg))

    table = Table(
        title="Bayesian search — by template",
        show_header=True, header_style="bold magenta",
    )
    table.add_column("template")
    table.add_column("n_total", justify="right")
    table.add_column("scored", justify="right")
    table.add_column("scored-rate", justify="right")
    table.add_column("max_score", justify="right")
    table.add_column("median scored", justify="right")
    table.add_column("top-10 mean", justify="right")

    for tmpl, runs in sorted(by_template.items()):
        n_total = len(runs)
        scored = [s for st, s, _, _ in runs if st == "scored" and s is not None]
        scored.sort(reverse=True)
        max_s = scored[0] if scored else float("nan")
        med = scored[len(scored) // 2] if scored else float("nan")
        top10 = scored[:10]
        top10_mean = sum(top10) / len(top10) if top10 else float("nan")
        table.add_row(
            tmpl,
            str(n_total),
            str(len(scored)),
            f"{len(scored) / n_total:.1%}" if n_total else "-",
            f"{max_s:.1f}" if scored else "-",
            f"{med:.1f}" if scored else "-",
            f"{top10_mean:.1f}" if top10 else "-",
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        choices=[*SPACES.keys(), "all"],
        default="all",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--n-init", type=int, default=20,
        help="Random initial samples (pre-registered: 20)",
    )
    parser.add_argument(
        "--n-total", type=int, default=200,
        help="Total evaluations including init (pre-registered: 200)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Drop and recreate the runs table before searching",
    )
    args = parser.parse_args()

    console = Console()
    if args.reset and args.db.exists():
        console.print(f"[yellow]resetting[/yellow] {args.db}")
        args.db.unlink()
    init_db(args.db)

    templates = list(SPACES.keys()) if args.template == "all" else [args.template]
    for tmpl in templates:
        run_search(
            template=tmpl,
            db_path=args.db,
            n_init=args.n_init,
            n_total=args.n_total,
            seed=args.seed,
            console=console,
        )

    report_summary(args.db, console)


if __name__ == "__main__":
    main()
