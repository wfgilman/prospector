"""
Ledger — append-only SQLite log of inner-loop iterations.

Every orchestrator iteration produces one row: the LLM proposal, validation
outcome, backtest result, and all diagnostic metrics.

Two uses:
  1. Sliding window for the next prompt (format_sliding_window)
  2. Persistent audit trail for outer-loop analysis

No updates or deletes on run records.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunRecord:
    """One iteration of the inner loop, as stored in the ledger."""

    # Required at construction time
    timestamp: str          # ISO 8601 UTC
    validation_status: str  # "valid"|"invalid_json"|"invalid_schema"|"duplicate"|"system_error"

    # LLM output fields (None on JSON parse failure)
    template: str | None = None
    config_json: str | None = None      # Raw JSON string from LLM
    securities: list[str] = field(default_factory=list)
    rationale: str | None = None
    thinking: str | None = None

    # Backtest outcome (None if validation failed before dispatch)
    backtest_status: str | None = None  # "scored"|"rejected"|"catastrophic"|None
    score: float | None = None
    n_trades: int | None = None
    pct_return: float | None = None
    max_drawdown: float | None = None
    profit_factor: float | None = None
    win_rate: float | None = None
    sharpe_ratio: float | None = None
    rejection_reason: str | None = None

    # Per-security breakdown as a JSON blob: {security: {status, score, ...}}
    securities_results_json: str | None = None

    # System-level error message (non-validation failures)
    error: str | None = None

    # Set after insert by Ledger.log()
    run_id: int | None = None


_CREATE_TABLE = """
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
"""

_INSERT = """
INSERT INTO runs (
    timestamp, validation_status, template, config_json, securities_json,
    rationale, thinking, backtest_status, score, n_trades, pct_return,
    max_drawdown, profit_factor, win_rate, sharpe_ratio, rejection_reason,
    securities_results_json, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class Ledger:
    """Append-only SQLite log of orchestrator iterations."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def log(self, record: RunRecord) -> int:
        """Insert a RunRecord and return its assigned run_id."""
        cur = self._conn.execute(
            _INSERT,
            (
                record.timestamp,
                record.validation_status,
                record.template,
                record.config_json,
                json.dumps(record.securities) if record.securities else None,
                record.rationale,
                record.thinking,
                record.backtest_status,
                record.score,
                record.n_trades,
                record.pct_return,
                record.max_drawdown,
                record.profit_factor,
                record.win_rate,
                record.sharpe_ratio,
                record.rejection_reason,
                record.securities_results_json,
                record.error,
            ),
        )
        self._conn.commit()
        run_id: int = cur.lastrowid  # type: ignore[assignment]
        record.run_id = run_id
        return run_id

    def get_sliding_window(
        self, n: int = 10, exclude_system_errors: bool = False
    ) -> list[RunRecord]:
        """Return the last n runs, most recent first.

        Args:
            n: Maximum number of records to return.
            exclude_system_errors: If True, skip rows with validation_status='system_error'.
                Use this for prompt injection — Ollama failures carry no signal for the model.
        """
        if exclude_system_errors:
            query = (
                "SELECT * FROM runs "
                "WHERE validation_status != 'system_error' "
                "ORDER BY run_id DESC LIMIT ?"
            )
        else:
            query = "SELECT * FROM runs ORDER BY run_id DESC LIMIT ?"
        cur = self._conn.execute(query, (n,))
        col_names = [d[0] for d in cur.description]
        records: list[RunRecord] = []
        for row in cur.fetchall():
            d = dict(zip(col_names, row))
            sec_json = d.pop("securities_json", None)
            records.append(RunRecord(
                run_id=d["run_id"],
                timestamp=d["timestamp"],
                validation_status=d["validation_status"],
                template=d["template"],
                config_json=d["config_json"],
                securities=json.loads(sec_json) if sec_json else [],
                rationale=d["rationale"],
                thinking=d["thinking"],
                backtest_status=d["backtest_status"],
                score=d["score"],
                n_trades=d["n_trades"],
                pct_return=d["pct_return"],
                max_drawdown=d["max_drawdown"],
                profit_factor=d["profit_factor"],
                win_rate=d["win_rate"],
                sharpe_ratio=d["sharpe_ratio"],
                rejection_reason=d["rejection_reason"],
                securities_results_json=d["securities_results_json"],
                error=d["error"],
            ))
        return records

    def last_n_templates(self, n: int = 5) -> list[str]:
        """
        Return template names for the last n successfully dispatched runs, most recent first.
        Used for stagnation detection (all same template → inject nudge).
        """
        cur = self._conn.execute(
            """SELECT template FROM runs
               WHERE validation_status = 'valid' AND template IS NOT NULL
               ORDER BY run_id DESC LIMIT ?""",
            (n,),
        )
        return [row[0] for row in cur.fetchall()]

    def count(self) -> int:
        """Total number of rows in the ledger."""
        return self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def format_sliding_window(self, n: int = 10) -> str:
        """
        Format the last n runs as a compact text table for prompt injection.

        Cold start (no records): returns the baseline instruction string.

        Columns: Run, Template, Securities, Score, Sharpe, PF, WR, Trades, MaxDD, Rationale
        Rejected/invalid rows show a brief reason instead of numeric metrics.
        """
        records = self.get_sliding_window(n, exclude_system_errors=True)
        if not records:
            return (
                "No prior results. This is the first run. "
                "Propose any configuration to establish a baseline."
            )

        w = {"run": 5, "tmpl": 16, "sec": 14, "score": 7, "sharpe": 6, "pf": 5, "wr": 6,
             "trades": 6, "dd": 6}

        header = (
            f"{'Run':<{w['run']}} {'Template':<{w['tmpl']}} {'Securities':<{w['sec']}} "
            f"{'Score':>{w['score']}} {'Sharpe':>{w['sharpe']}} {'PF':>{w['pf']}} "
            f"{'WR':>{w['wr']}} {'Trades':>{w['trades']}} {'MaxDD':>{w['dd']}}  Rationale"
        )
        sep = (
            f"{'---':<{w['run']}} {'---------------':<{w['tmpl']}} {'----------':<{w['sec']}} "
            f"{'------':>{w['score']}} {'------':>{w['sharpe']}} {'----':>{w['pf']}} "
            f"{'-----':>{w['wr']}} {'------':>{w['trades']}} {'------':>{w['dd']}}  ---------"
        )
        lines = [header, sep]

        for r in records:
            run_s = str(r.run_id or "?")
            tmpl_s = (r.template or "—")[: w["tmpl"] - 1]
            sec_s = ",".join(s.replace("-PERP", "") for s in (r.securities or []))[: w["sec"] - 1]

            if r.backtest_status in ("scored", "catastrophic"):
                score_s  = f"{r.score:.1f}" if r.score is not None else "—"
                sharpe_s = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio is not None else "—"
                pf_s     = f"{r.profit_factor:.1f}" if r.profit_factor is not None else "—"
                wr_s     = f"{r.win_rate * 100:.0f}%" if r.win_rate is not None else "—"
                trades_s = str(r.n_trades) if r.n_trades is not None else "—"
                dd_s     = f"{r.max_drawdown * 100:.0f}%" if r.max_drawdown is not None else "—"
                rationale = (r.rationale or "")[:80]
            elif r.backtest_status == "rejected":
                score_s = sharpe_s = pf_s = wr_s = trades_s = dd_s = ""
                reason = (r.rejection_reason or "")
                rationale = f"rejected ({reason[:40]})  {(r.rationale or '')[:25]}"
            elif r.validation_status != "valid":
                score_s = sharpe_s = pf_s = wr_s = trades_s = dd_s = ""
                rationale = f"[{r.validation_status}] {(r.error or '')[:60]}"
            else:
                score_s = sharpe_s = pf_s = wr_s = trades_s = dd_s = ""
                rationale = (r.error or "")[:80]

            line = (
                f"{run_s:<{w['run']}} {tmpl_s:<{w['tmpl']}} {sec_s:<{w['sec']}} "
                f"{score_s:>{w['score']}} {sharpe_s:>{w['sharpe']}} {pf_s:>{w['pf']}} "
                f"{wr_s:>{w['wr']}} {trades_s:>{w['trades']}} {dd_s:>{w['dd']}}  {rationale}"
            )
            lines.append(line)

        return "\n".join(lines)

    def coverage_summary(self) -> list[dict]:
        """
        Return per-(template, timeframe) attempt counts for all valid runs.

        Used by the orchestrator to inject exploration-pressure context into the
        prompt: the LLM should see which (template, timeframe) cells have been
        attempted many times without success and which are under-explored.

        Each entry: {template, timeframe, attempts, scored, best_score}.
        `timeframe` is pulled from params.timeframe (false_breakout) or
        params.short_tf (triple_screen); runs without either are skipped.
        """
        cur = self._conn.execute(
            "SELECT template, config_json, backtest_status, score FROM runs "
            "WHERE validation_status = 'valid' AND config_json IS NOT NULL"
        )
        buckets: dict[tuple[str, str], dict] = {}
        for template, cfg_json, status, score in cur.fetchall():
            if not template:
                continue
            try:
                params = json.loads(cfg_json).get("params", {})
            except (json.JSONDecodeError, TypeError):
                continue
            tf = params.get("timeframe") or params.get("short_tf")
            if not tf:
                continue
            key = (template, tf)
            b = buckets.setdefault(key, {"attempts": 0, "scored": 0, "best_score": None})
            b["attempts"] += 1
            if status == "scored":
                b["scored"] += 1
                if score is not None and (b["best_score"] is None or score > b["best_score"]):
                    b["best_score"] = score

        result = []
        for (tmpl, tf), b in sorted(buckets.items()):
            result.append({"template": tmpl, "timeframe": tf, **b})
        return result

    def format_coverage(self) -> str:
        """
        Format coverage_summary() as a compact text block for prompt injection.
        Returns empty string if no valid runs exist yet.
        """
        rows = self.coverage_summary()
        if not rows:
            return ""
        lines = ["EXPLORATION COVERAGE (valid attempts across all history):"]
        for r in rows:
            best = f"{r['best_score']:.0f}" if r["best_score"] is not None else "—"
            lines.append(
                f"  {r['template']:<16} × {r['timeframe']:<3}  "
                f"attempts={r['attempts']:<3}  scored={r['scored']:<3}  best={best}"
            )
        return "\n".join(lines)

    def close(self) -> None:
        self._conn.close()
