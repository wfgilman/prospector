"""
Tests for orchestrator pure functions: parse_response, validate_config, _aggregate,
assemble_prompt, and run_one_iteration (with mocked Ollama + dispatch).

No real Ollama calls, no real OHLCV files. All external I/O is mocked.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from prospector.harness.engine import BacktestResult
from prospector.ledger import Ledger, RunRecord
from prospector.orchestrator import (
    AppConfig,
    _aggregate,
    _mock_model_response,
    _params_match,
    assemble_prompt,
    parse_response,
    run_one_iteration,
    validate_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path):
    ld = Ledger(tmp_path / "test.db")
    yield ld
    ld.close()


@pytest.fixture
def universe():
    return {"BTC-PERP", "ETH-PERP", "SOL-PERP"}


def _false_breakout_proposal(**overrides) -> dict:
    base = {
        "thinking": "Testing false breakout.",
        "template": "false_breakout",
        "params": {
            "timeframe": "4h",
            "range_lookback": 30,
            "range_threshold": 0.03,
            "confirmation_bars": 1,
        },
        "securities": ["BTC-PERP"],
        "rationale": "Baseline false breakout on BTC.",
    }
    base.update(overrides)
    return base


def _make_backtest_result(status="scored", score=50.0) -> BacktestResult:
    return BacktestResult(
        status=status,
        rejection_reason=None if status == "scored" else "insufficient_trades: 5 < 20",
        score=score if status == "scored" else (float("nan") if status == "rejected" else -1000.0),
        n_trades=25 if status == "scored" else 5,
        pct_return=0.10,
        max_drawdown=0.08,
        profit_factor=1.8,
        win_rate=0.56,
        sharpe_ratio=1.1,
        avg_trade_pnl=40.0,
        avg_hold_bars=5.0,
        total_return=1000.0,
    )


# ---------------------------------------------------------------------------
# parse_response
# ---------------------------------------------------------------------------

def test_parse_response_clean_json():
    raw = '{"template": "false_breakout", "params": {}, "securities": ["BTC-PERP"], "rationale": "x"}'  # noqa: E501
    result = parse_response(raw)
    assert result["template"] == "false_breakout"


def test_parse_response_with_preamble():
    raw = 'Here is my proposal:\n\n{"template": "false_breakout", "params": {}, "rationale": "x"}'
    result = parse_response(raw)
    assert result["template"] == "false_breakout"


def test_parse_response_with_trailing_text():
    raw = '{"template": "false_breakout"} Some trailing commentary.'
    result = parse_response(raw)
    assert result["template"] == "false_breakout"


def test_parse_response_nested_json():
    """Nested objects in params must parse cleanly."""
    raw = '{"template": "t", "params": {"nested": {"a": 1}}, "thinking": "ok"}'
    result = parse_response(raw)
    assert result["params"]["nested"]["a"] == 1


def test_parse_response_invalid_raises():
    with pytest.raises(ValueError, match="No JSON"):
        parse_response("This is just plain text with no JSON.")


def test_parse_response_empty_raises():
    with pytest.raises(ValueError):
        parse_response("")


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

def test_validate_valid_false_breakout(ledger, universe):
    ok, reason = validate_config(_false_breakout_proposal(), universe, ledger)
    assert ok, f"Expected valid but got: {reason}"


def test_validate_missing_field(ledger, universe):
    proposal = _false_breakout_proposal()
    del proposal["rationale"]
    ok, reason = validate_config(proposal, universe, ledger)
    assert not ok
    assert "rationale" in reason


def test_validate_unknown_template(ledger, universe):
    ok, reason = validate_config(_false_breakout_proposal(template="nonexistent"), universe, ledger)
    assert not ok
    assert "Unknown template" in reason


def test_validate_unimplemented_template(ledger, universe):
    ok, reason = validate_config(
        _false_breakout_proposal(template="impulse_system"), universe, ledger
    )
    assert not ok
    assert "not yet implemented" in reason


def test_validate_param_out_of_range(ledger, universe):
    p = _false_breakout_proposal()
    p["params"]["range_lookback"] = 999  # Max is 60
    ok, reason = validate_config(p, universe, ledger)
    assert not ok
    assert "range_lookback" in reason


def test_validate_param_wrong_type(ledger, universe):
    p = _false_breakout_proposal()
    p["params"]["range_lookback"] = "thirty"  # Should be int
    ok, reason = validate_config(p, universe, ledger)
    assert not ok
    assert "range_lookback" in reason


def test_validate_param_invalid_choice(ledger, universe):
    p = _false_breakout_proposal()
    p["params"]["timeframe"] = "5m"  # Not in allowed choices
    ok, reason = validate_config(p, universe, ledger)
    assert not ok
    assert "timeframe" in reason


def test_validate_cross_constraint_fast_ema(ledger, universe):
    proposal = {
        "thinking": "test",
        "template": "triple_screen",
        "params": {
            "long_tf": "1d",
            "short_tf": "4h",
            "slow_ema": 20,
            "fast_ema": 25,  # fast >= slow — invalid
            "oscillator": "stochastic",
            "osc_entry_threshold": 30.0,
        },
        "securities": ["BTC-PERP"],
        "rationale": "Testing constraint.",
    }
    ok, reason = validate_config(proposal, universe, ledger)
    assert not ok
    assert "fast_ema" in reason


def test_validate_cross_constraint_timeframe(ledger, universe):
    proposal = {
        "thinking": "test",
        "template": "triple_screen",
        "params": {
            "long_tf": "1d",
            "short_tf": "1d",  # same as long_tf — invalid
            "slow_ema": 26,
            "fast_ema": 13,
            "oscillator": "stochastic",
            "osc_entry_threshold": 30.0,
        },
        "securities": ["BTC-PERP"],
        "rationale": "Testing timeframe constraint.",
    }
    ok, reason = validate_config(proposal, universe, ledger)
    assert not ok
    assert "short_tf" in reason or "long_tf" in reason


def test_validate_unknown_security(ledger, universe):
    ok, reason = validate_config(
        _false_breakout_proposal(securities=["DOGE-PERP"]), universe, ledger
    )
    assert not ok
    assert "DOGE-PERP" in reason


def test_validate_empty_securities(ledger, universe):
    ok, reason = validate_config(_false_breakout_proposal(securities=[]), universe, ledger)
    assert not ok
    assert "non-empty" in reason.lower()


def test_validate_duplicate_rejected(ledger, universe):
    """Exact duplicate of a prior valid run should be rejected."""
    proposal = _false_breakout_proposal()
    # Log a previous run with the same config
    ledger.log(RunRecord(
        timestamp="2024-01-01T00:00:00+00:00",
        validation_status="valid",
        template="false_breakout",
        config_json=json.dumps(proposal),
        securities=["BTC-PERP"],
    ))

    ok, reason = validate_config(proposal, universe, ledger)
    assert not ok
    assert "Duplicate" in reason


def test_validate_different_params_not_duplicate(ledger, universe):
    """Same template + security but different params should not be flagged."""
    proposal_a = _false_breakout_proposal()
    ledger.log(RunRecord(
        timestamp="2024-01-01T00:00:00+00:00",
        validation_status="valid",
        template="false_breakout",
        config_json=json.dumps(proposal_a),
        securities=["BTC-PERP"],
    ))

    proposal_b = _false_breakout_proposal()
    proposal_b["params"]["range_lookback"] = 45  # Different
    ok, _ = validate_config(proposal_b, universe, ledger)
    assert ok


# ---------------------------------------------------------------------------
# _params_match
# ---------------------------------------------------------------------------

def test_params_match_identical():
    assert _params_match({"a": 1, "b": "x"}, {"a": 1, "b": "x"})


def test_params_match_different_value():
    assert not _params_match({"a": 1}, {"a": 2})


def test_params_match_different_keys():
    assert not _params_match({"a": 1}, {"b": 1})


# ---------------------------------------------------------------------------
# _aggregate
# ---------------------------------------------------------------------------

def test_aggregate_single_scored():
    r = _make_backtest_result("scored", score=42.0)
    status, score, metrics = _aggregate({"BTC-PERP": r})
    assert status == "scored"
    assert score == pytest.approx(42.0)
    assert metrics["n_trades"] == r.n_trades


def test_aggregate_any_catastrophic():
    cat = _make_backtest_result("catastrophic", score=-1000.0)
    scored = _make_backtest_result("scored", score=50.0)
    status, score, _ = _aggregate({"BTC-PERP": cat, "ETH-PERP": scored})
    assert status == "catastrophic"
    assert score == -1000.0


def test_aggregate_all_rejected():
    r1 = _make_backtest_result("rejected")
    r2 = _make_backtest_result("rejected")
    status, score, metrics = _aggregate({"BTC-PERP": r1, "ETH-PERP": r2})
    assert status == "rejected"
    assert score is None
    assert "BTC-PERP" in metrics["rejection_reason"]


def test_aggregate_mixed_scored_rejected():
    """One scored + one rejected → aggregate the scored one."""
    s = _make_backtest_result("scored", score=60.0)
    r = _make_backtest_result("rejected")
    status, score, metrics = _aggregate({"BTC-PERP": s, "ETH-PERP": r})
    assert status == "scored"
    assert score == pytest.approx(60.0)
    assert metrics["n_trades"] == s.n_trades  # Only scored security


def test_aggregate_mean_of_scored():
    s1 = _make_backtest_result("scored", score=40.0)
    s2 = _make_backtest_result("scored", score=60.0)
    status, score, _ = _aggregate({"BTC-PERP": s1, "ETH-PERP": s2})
    assert status == "scored"
    assert score == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# assemble_prompt
# ---------------------------------------------------------------------------

def test_assemble_prompt_contains_registry():
    text = assemble_prompt("No prior results.", ["BTC-PERP"])
    assert "triple_screen" in text
    assert "false_breakout" in text


def test_assemble_prompt_contains_universe():
    text = assemble_prompt("No prior results.", ["BTC-PERP", "ETH-PERP"])
    assert "BTC-PERP" in text
    assert "ETH-PERP" in text


def test_assemble_prompt_contains_window():
    text = assemble_prompt("RECENT RESULTS HERE", ["BTC-PERP"])
    assert "RECENT RESULTS HERE" in text


def test_assemble_prompt_stagnation_note():
    text = assemble_prompt("window", ["BTC-PERP"], stagnation_note="Explore a different template.")
    assert "Explore a different template." in text


def test_assemble_prompt_no_stagnation_note():
    text = assemble_prompt("window", ["BTC-PERP"], stagnation_note=None)
    assert "Explore a different template." not in text


# ---------------------------------------------------------------------------
# run_one_iteration (mocked)
# ---------------------------------------------------------------------------

def test_run_one_iteration_system_error_logged(ledger, tmp_path):
    """Ollama failure → logs a system_error record and returns gracefully."""
    config = AppConfig(
        model="test-model",
        ollama_host="http://localhost:11434",
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "ohlcv",
    )

    with patch("prospector.orchestrator.call_model", side_effect=Exception("connection refused")):
        record = run_one_iteration(ledger, config)

    assert record.validation_status == "system_error"
    assert "connection refused" in record.error
    assert ledger.count() == 1


def test_run_one_iteration_invalid_json_logged(ledger, tmp_path):
    config = AppConfig(db_path=tmp_path / "test.db", data_dir=tmp_path / "ohlcv")

    with patch("prospector.orchestrator.call_model", return_value="not json at all"):
        record = run_one_iteration(ledger, config)

    assert record.validation_status == "invalid_json"
    assert ledger.count() == 1


def test_run_one_iteration_valid_scored(ledger, tmp_path):
    """End-to-end: mocked Ollama + mocked dispatch → scored record in ledger."""
    config = AppConfig(
        securities=["BTC-PERP"],
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "ohlcv",
    )
    proposal = _false_breakout_proposal()
    scored_result = _make_backtest_result("scored", score=55.0)

    with (
        patch("prospector.orchestrator.call_model", return_value=json.dumps(proposal)),
        patch("prospector.orchestrator._dispatch", return_value={"BTC-PERP": scored_result}),
    ):
        record = run_one_iteration(ledger, config)

    assert record.validation_status == "valid"
    assert record.backtest_status == "scored"
    assert record.score == pytest.approx(55.0)
    assert record.run_id is not None
    assert ledger.count() == 1


# ---------------------------------------------------------------------------
# _mock_model_response
# ---------------------------------------------------------------------------

def test_mock_model_response_always_validates(ledger, universe):
    """Every mock proposal must parse and pass validate_config."""
    securities = sorted(universe)
    for _ in range(50):
        raw = _mock_model_response("ignored prompt", securities)
        proposal = parse_response(raw)
        ok, reason = validate_config(proposal, set(securities), ledger)
        assert ok, f"Mock produced invalid proposal: {reason} | proposal={proposal}"


def test_run_one_iteration_invalid_schema_logged(ledger, tmp_path):
    config = AppConfig(
        securities=["BTC-PERP"],
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "ohlcv",
    )
    bad_proposal = _false_breakout_proposal()
    bad_proposal["params"]["range_lookback"] = 9999  # Out of range

    with patch("prospector.orchestrator.call_model", return_value=json.dumps(bad_proposal)):
        record = run_one_iteration(ledger, config)

    assert record.validation_status == "invalid_schema"
    assert ledger.count() == 1
