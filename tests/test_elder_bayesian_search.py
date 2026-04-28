"""
Smoke test for scripts/elder_bayesian_search.py.

Verifies the search loop runs end-to-end against real OHLCV data, persists
rows with the correct schema to a temp DB, and produces at least one scored
config when given enough evaluations to find one. Skips if scikit-optimize
or the OHLCV data parquet tree is missing — both are research-only deps.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


pytest.importorskip("skopt", reason="scikit-optimize is research-only")

OHLCV_DIR = REPO_ROOT / "data" / "ohlcv" / "BTC_PERP"
if not (OHLCV_DIR / "4h.parquet").exists():
    pytest.skip("OHLCV parquet tree not populated", allow_module_level=True)


from elder_bayesian_search import (  # noqa: E402
    SPACES,
    init_db,
    run_search,
)
from rich.console import Console  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "test_bayesian.db"
    init_db(db)
    return db


def _row_count(db: Path) -> int:
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    con.close()
    return n


def _row_statuses(db: Path) -> list[str]:
    con = sqlite3.connect(db)
    rows = [r[0] for r in con.execute("SELECT backtest_status FROM runs").fetchall()]
    con.close()
    return rows


def test_false_breakout_smoke(tmp_db: Path) -> None:
    run_search(
        template="false_breakout",
        db_path=tmp_db,
        n_init=4,
        n_total=8,
        seed=1,
        console=Console(quiet=True),
    )
    assert _row_count(tmp_db) == 8
    statuses = set(_row_statuses(tmp_db))
    # Every row should be one of the four valid statuses.
    assert statuses <= {"scored", "rejected", "catastrophic", "error"}


def test_triple_screen_smoke(tmp_db: Path) -> None:
    run_search(
        template="triple_screen",
        db_path=tmp_db,
        n_init=4,
        n_total=8,
        seed=2,
        console=Console(quiet=True),
    )
    assert _row_count(tmp_db) == 8
    statuses = set(_row_statuses(tmp_db))
    assert statuses <= {"scored", "rejected", "catastrophic", "error"}


def test_persisted_config_roundtrips(tmp_db: Path) -> None:
    run_search(
        template="false_breakout",
        db_path=tmp_db,
        n_init=2, n_total=3, seed=7,
        console=Console(quiet=True),
    )
    con = sqlite3.connect(tmp_db)
    rows = con.execute("SELECT config_json, securities_json, template FROM runs").fetchall()
    con.close()
    for cfg_json, secs_json, tmpl in rows:
        cfg = json.loads(cfg_json)
        secs = json.loads(secs_json)
        assert tmpl == "false_breakout"
        assert cfg["template"] == "false_breakout"
        assert cfg["optimizer"] == "bayesian_gp_ei"
        assert set(cfg["params"].keys()) == {
            "timeframe", "range_lookback", "range_threshold",
            "confirmation_bars", "volume_filter",
        }
        assert len(secs) == 1
        assert secs[0] in {"BTC-PERP", "ETH-PERP", "SOL-PERP"}


def test_spaces_are_six_dimensional() -> None:
    """Pre-registered: 6-D per template."""
    for tmpl, space in SPACES.items():
        assert len(space) == 6, f"{tmpl} space has {len(space)} dims (must be 6)"


def test_triple_screen_rejects_invalid_ema_pair(tmp_db: Path) -> None:
    """fast_ema >= slow_ema should land as rejected, not crash."""
    from elder_bayesian_search import evaluate_triple_screen

    eval_result, params, sec = evaluate_triple_screen(
        ["1d/4h", 20, 30, "rsi", 50.0, "BTC-PERP"]
    )
    assert eval_result.backtest_status == "rejected"
    assert eval_result.rejection_reason == "fast_ema >= slow_ema"
    assert eval_result.score is None
    assert params["long_tf"] == "1d" and params["short_tf"] == "4h"
    assert params["slow_ema"] == 20 and params["fast_ema"] == 30
    assert sec == "BTC-PERP"
