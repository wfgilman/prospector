"""
Orchestrator — inner loop for LLM-driven strategy discovery.

Each iteration:
  1. Assemble prompt (sliding window + stagnation detection)
  2. Call Ollama to generate a strategy configuration
  3. Parse and validate the JSON proposal
  4. Dispatch to the backtest harness (per security)
  5. Aggregate results and log to the ledger
  6. Repeat

Entry point: python -m prospector.orchestrator

Configuration via environment variables:
  PROSPECTOR_MODEL   Ollama model name (default: qwen2.5-coder:14b)
  OLLAMA_HOST        Ollama base URL (default: http://localhost:11434)
  PROSPECTOR_MOCK    If set to 1/true/yes, bypass Ollama and emit random
                     schema-valid proposals (for shaking out the loop without
                     a running model server).
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from prospector.harness.engine import BacktestResult, run_backtest
from prospector.ledger import Ledger, RunRecord
from prospector.templates import false_breakout, triple_screen
from prospector.templates.base import Signal

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AppConfig:
    """Runtime configuration for the orchestrator loop."""

    model: str = "qwen2.5-coder:14b"
    ollama_host: str = "http://localhost:11434"
    securities: list[str] = field(default_factory=lambda: ["BTC-PERP", "ETH-PERP", "SOL-PERP"])
    sliding_window_size: int = 10
    stagnation_n: int = 5          # Consecutive same-template proposals → nudge
    db_path: Path = field(default_factory=lambda: _REPO_ROOT / "data" / "prospector.db")
    data_dir: Path = field(default_factory=lambda: _REPO_ROOT / "data" / "ohlcv")
    mock_model: bool = False       # Bypass Ollama and emit random valid proposals

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build config from environment variables, falling back to defaults."""
        return cls(
            model=os.environ.get("PROSPECTOR_MODEL", "qwen2.5-coder:14b"),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            mock_model=os.environ.get("PROSPECTOR_MOCK", "").lower() in ("1", "true", "yes"),
        )


# ---------------------------------------------------------------------------
# Parameter schemas (for validation)
# ---------------------------------------------------------------------------

# Only templates with running implementations can be dispatched.
IMPLEMENTED_TEMPLATES: frozenset[str] = frozenset({"false_breakout", "triple_screen"})

# Full schema for all 6 templates. Unimplemented ones fail at the "not implemented" gate.
# Schema entry keys:
#   type: "str" | "int" | "float" | "bool"
#   required: bool (default True)
#   choices: set of allowed values (for str)
#   min/max: numeric bounds (for int/float)
PARAM_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "triple_screen": {
        "long_tf":              {"type": "str",   "choices": {"1w", "1d"}},
        "short_tf":             {"type": "str",   "choices": {"1d", "4h", "1h"}},
        "slow_ema":             {"type": "int",   "min": 15, "max": 50},
        "fast_ema":             {"type": "int",   "min": 5,  "max": 25},
        "oscillator":           {"type": "str", "choices": {"force_index_2", "stochastic", "rsi"}},
        "osc_entry_threshold":  {"type": "float", "min": 0.0, "max": 100.0},
    },
    "false_breakout": {
        "timeframe":         {"type": "str",   "choices": {"1d", "4h", "1h"}},
        "range_lookback":    {"type": "int",   "min": 15,   "max": 60},
        "range_threshold":   {"type": "float", "min": 0.01, "max": 0.10},
        "confirmation_bars": {"type": "int",   "min": 1,    "max": 3},
        "volume_filter":     {"type": "bool",  "required": False},
    },
    "impulse_system": {
        "timeframe":    {"type": "str",  "choices": {"1d", "4h", "1h"}},
        "ema_period":   {"type": "int",  "min": 8,  "max": 30},
        "macd_fast":    {"type": "int",  "min": 6,  "max": 20},
        "macd_slow":    {"type": "int",  "min": 15, "max": 40},
        "macd_signal":  {"type": "int",  "min": 5,  "max": 15},
        "hold_bars":    {"type": "int",  "min": 1,  "max": 20, "required": False},
    },
    "channel_fade": {
        "timeframe":            {"type": "str",   "choices": {"1d", "4h", "1h"}},
        "ema_period":           {"type": "int",   "min": 15,   "max": 50},
        "channel_coefficient":  {"type": "float", "min": 0.01, "max": 0.10},
        "confirmation":         {"type": "str",   "choices": {"macd_histogram", "force_index"}},
        "auto_fit_channel":     {"type": "bool",  "required": False},
    },
    "kangaroo_tail": {
        "timeframe":      {"type": "str",   "choices": {"1d", "4h", "1h"}},
        "tail_multiplier": {"type": "float", "min": 1.5, "max": 5.0},
        "context_bars":   {"type": "int",   "min": 5,   "max": 30},
        "max_hold_bars":  {"type": "int",   "min": 2,   "max": 10},
    },
    "ema_divergence": {
        "timeframe":           {"type": "str",  "choices": {"1d", "4h", "1h"}},
        "ema_period":          {"type": "int",  "min": 15, "max": 50},
        "oscillator": {"type": "str", "choices": {"macd_histogram", "force_index", "rsi"}},
        "divergence_lookback": {"type": "int",  "min": 10, "max": 60},
    },
}

ALL_TEMPLATES: frozenset[str] = frozenset(PARAM_SCHEMAS.keys())

# Timeframe ordering for cross-param constraint checks (smaller = shorter)
_TF_RANK: dict[str, int] = {"1h": 0, "4h": 1, "1d": 2, "1w": 3}


# ---------------------------------------------------------------------------
# Prompt components (static sections)
# ---------------------------------------------------------------------------

_PREAMBLE = """\
You are a strategy configuration agent for a crypto trading system. Your job is to propose \
the next strategy configuration to backtest.

You have access to a library of strategy templates — pre-built trading strategies with tunable \
parameters. You do NOT write code. You select a template, choose parameter values within the \
allowed ranges, and pick which securities to test on.

Your goal: maximize the backtest score by exploring the configuration space intelligently. \
Study the recent results below to understand what has been tried, what worked, what failed, \
and why. Then propose a configuration that explores a different or promising region of the space.

Rules:
- Output ONLY valid JSON matching the schema below. No commentary before or after.
- All parameter values must be within the specified ranges.
- Securities must come from the universe listed below.
- Your proposal must be materially different from recent results — do not repeat or make \
minor tweaks to failed configs.
- The "rationale" field is important. Explain your reasoning: what pattern you see in \
recent results and why your proposal addresses it.\
"""

_REGISTRY = """\
TEMPLATES AND PARAMETER RANGES:

1. triple_screen — Trade with higher-timeframe trend, enter on lower-timeframe pullback.
   Params:
     long_tf: "1w" | "1d"
     short_tf: "1d" | "4h" | "1h"  (must be shorter than long_tf)
     slow_ema: int 15–50 (default 26)
     fast_ema: int 5–25 (default 13, must be < slow_ema)
     oscillator: "force_index_2" | "stochastic" | "rsi"
     osc_entry_threshold: float 0–100

2. false_breakout — Fade breakouts from trading ranges when price returns inside.
   Params:
     timeframe: "1d" | "4h" | "1h"
     range_lookback: int 15–60 (default 30)
     range_threshold: float 0.01–0.10 (default 0.03)
     confirmation_bars: int 1–3 (default 1)
     volume_filter: bool (optional, default false)\
"""

_OUTPUT_FORMAT = """\
OUTPUT FORMAT:

First, write a brief analysis inside a "thinking" field (2-4 sentences). Then provide \
your configuration.

{
  "thinking": "Your analysis of the recent results and reasoning for this proposal.",
  "template": "<template_id>",
  "params": { ... },
  "securities": ["<PAIR>", ...],
  "rationale": "1-2 sentences: what you're trying and why, given recent results."
}

Score meaning: higher is better. Negative scores indicate catastrophic failure. \
"rejected" means the config failed a hard gate (too few trades or profit factor below 1.3). \
The score accounts for realistic position sizing, drawdown penalties, and transaction costs \
— you cannot game it by proposing extreme parameters.\
"""

_EXAMPLES = """\
EXAMPLES OF GOOD PROPOSALS:

Example 1 — Exploring an untested security:
{
  "thinking": "false_breakout has only been tested on BTC. ETH has similar volatility but \
different market structure. Using the same timeframe with a slightly wider range threshold \
to account for ETH's higher volatility relative to its price.",
  "template": "false_breakout",
  "params": {
    "timeframe": "4h",
    "range_lookback": 30,
    "range_threshold": 0.04,
    "confirmation_bars": 1,
    "volume_filter": false
  },
  "securities": ["ETH-PERP"],
  "rationale": "ETH untested. Matching BTC params but wider range_threshold for ETH volatility."
}

Example 2 — Iterating on a promising result:
{
  "thinking": "Run 12 (triple_screen on BTC, score 42.1) used stochastic with default EMAs. \
The stochastic oscillator on 4h trend showed promise. Trying a wider EMA spread to give the \
trend filter more authority and reduce false signals on choppy days.",
  "template": "triple_screen",
  "params": {
    "long_tf": "1d",
    "short_tf": "4h",
    "slow_ema": 35,
    "fast_ema": 10,
    "oscillator": "stochastic",
    "osc_entry_threshold": 25
  },
  "securities": ["BTC-PERP"],
  "rationale": "Widening EMA spread (35/10 vs 26/13) to strengthen trend filter on the \
daily/4h pair that scored 42.1."
}\
"""


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def assemble_prompt(
    sliding_window_text: str,
    securities: list[str],
    stagnation_note: str | None = None,
) -> str:
    """
    Build the full prompt from static sections and dynamic content.

    Args:
        sliding_window_text: Formatted table from Ledger.format_sliding_window(),
                             or the cold-start message.
        securities:          Available trading pairs for this session.
        stagnation_note:     Optional nudge injected when last N proposals reuse
                             the same template.
    """
    universe = ", ".join(securities)
    recent_section = f"RECENT RESULTS (most recent first):\n{sliding_window_text}"
    if stagnation_note:
        recent_section += f"\n\n{stagnation_note}"

    return "\n\n".join([
        _PREAMBLE,
        _REGISTRY,
        f"SECURITIES (choose one or more):\n{universe}",
        recent_section,
        _OUTPUT_FORMAT,
        _EXAMPLES,
    ])


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------

def call_model(prompt: str, config: AppConfig) -> str:
    """Call the Ollama /api/generate endpoint. Returns the raw response text."""
    if config.mock_model:
        return _mock_model_response(prompt, config.securities)

    payload = {
        "model": config.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 1024,
        },
    }
    resp = httpx.post(
        f"{config.ollama_host}/api/generate",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def _mock_model_response(prompt: str, securities: list[str]) -> str:
    """
    Return a JSON-stringified proposal for one of the implemented templates with
    randomized but schema-valid params and a random non-empty subset of the
    available securities. Used when PROSPECTOR_MOCK is set so the loop can be
    exercised end-to-end without a running Ollama instance.
    """
    template = random.choice(sorted(IMPLEMENTED_TEMPLATES))

    if template == "false_breakout":
        params: dict[str, Any] = {
            "timeframe": random.choice(["1d", "4h", "1h"]),
            "range_lookback": random.randint(15, 60),
            "range_threshold": round(random.uniform(0.01, 0.10), 3),
            "confirmation_bars": random.randint(1, 3),
            "volume_filter": random.choice([True, False]),
        }
    elif template == "triple_screen":
        long_tf = random.choice(["1w", "1d"])
        # short_tf must be strictly shorter than long_tf
        short_choices = [tf for tf in ("1d", "4h", "1h") if _TF_RANK[tf] < _TF_RANK[long_tf]]
        slow = random.randint(20, 50)
        # fast_ema schema bounds [5, 25] AND must be < slow_ema
        fast = random.randint(5, min(25, slow - 1))
        params = {
            "long_tf": long_tf,
            "short_tf": random.choice(short_choices),
            "slow_ema": slow,
            "fast_ema": fast,
            "oscillator": random.choice(["force_index_2", "stochastic", "rsi"]),
            "osc_entry_threshold": round(random.uniform(10.0, 90.0), 1),
        }
    else:
        raise RuntimeError(f"Mock model has no generator for template {template!r}")

    n_sec = random.randint(1, len(securities))
    chosen = random.sample(securities, n_sec)

    proposal = {
        "thinking": "Mock model: randomized proposal for end-to-end loop testing.",
        "template": template,
        "params": params,
        "securities": chosen,
        "rationale": f"Mock proposal exploring {template} on {','.join(chosen)}.",
    }
    return json.dumps(proposal)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_response(raw: str) -> dict:
    """
    Extract and return the JSON object from the LLM's response text.

    Handles the common case where the model emits preamble text before the JSON
    block despite the prompt instructing otherwise. Raises ValueError if no
    valid JSON object can be found.
    """
    text = raw.strip()

    # Fast path: the model followed instructions and output only JSON.
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: scan from the first '{' and find the matching '}'.
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object found in LLM response")

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(text[start : i + 1])
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        break

    raise ValueError("No valid JSON object found in LLM response")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(
    proposal: dict,
    securities_universe: set[str],
    ledger: Ledger,
    window_size: int = 10,
) -> tuple[bool, str]:
    """
    Validate a parsed LLM proposal.

    Checks: required fields, template known + implemented, param schema,
    cross-param constraints, securities universe membership, and exact-match
    duplicate detection against the recent sliding window.

    Returns:
        (True, "")          — valid
        (False, reason)     — invalid, with a human-readable reason
    """
    # --- Top-level fields ---
    required = {"template", "params", "securities", "rationale"}
    missing = required - set(proposal.keys())
    if missing:
        return False, f"Missing required fields: {sorted(missing)}"

    template = proposal["template"]
    params = proposal["params"]
    securities = proposal["securities"]
    rationale = proposal["rationale"]

    # --- Template ---
    if not isinstance(template, str) or template not in ALL_TEMPLATES:
        known = sorted(ALL_TEMPLATES)
        return False, f"Unknown template {template!r}. Must be one of {known}"
    if template not in IMPLEMENTED_TEMPLATES:
        return False, f"Template {template!r} is not yet implemented"

    # --- Params ---
    if not isinstance(params, dict):
        return False, "params must be a JSON object"
    errors = _validate_params(template, params)
    if errors:
        return False, f"Invalid params: {'; '.join(errors)}"
    constraint_err = _check_constraints(template, params)
    if constraint_err:
        return False, constraint_err

    # --- Securities ---
    if not isinstance(securities, list) or not securities:
        return False, "securities must be a non-empty array"
    unknown_sec = [s for s in securities if s not in securities_universe]
    if unknown_sec:
        return False, f"Unknown securities: {unknown_sec}. Universe: {sorted(securities_universe)}"

    # --- Rationale ---
    if not isinstance(rationale, str) or not rationale.strip():
        return False, "rationale must be a non-empty string"

    # --- Diversity: exact duplicate check against recent window ---
    recent = ledger.get_sliding_window(window_size)
    for r in recent:
        if r.validation_status != "valid" or r.template != template:
            continue
        if sorted(r.securities) != sorted(securities):
            continue
        if r.config_json:
            try:
                prev = json.loads(r.config_json)
                if _params_match(params, prev.get("params", {})):
                    return False, f"Duplicate of run #{r.run_id}"
            except (json.JSONDecodeError, TypeError):
                pass

    return True, ""


def _validate_params(template: str, params: dict) -> list[str]:
    """Validate params against the template schema. Returns list of error strings."""
    schema = PARAM_SCHEMAS[template]
    errors: list[str] = []

    for name, spec in schema.items():
        required = spec.get("required", True)
        if name not in params:
            if required:
                errors.append(f"missing required param '{name}'")
            continue

        value = params[name]
        ptype = spec["type"]

        if ptype == "str":
            if not isinstance(value, str):
                errors.append(f"'{name}' must be a string")
                continue
            choices = spec.get("choices")
            if choices and value not in choices:
                errors.append(f"'{name}' must be one of {sorted(choices)}, got {value!r}")

        elif ptype == "int":
            # JSON numbers may arrive as int or float; accept only integer-valued numbers.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"'{name}' must be an integer")
                continue
            if float(value) != int(value):
                errors.append(f"'{name}' must be an integer, got {value}")
                continue
            int_val = int(value)
            mn, mx = spec.get("min"), spec.get("max")
            if mn is not None and int_val < mn:
                errors.append(f"'{name}' must be >= {mn}, got {int_val}")
            if mx is not None and int_val > mx:
                errors.append(f"'{name}' must be <= {mx}, got {int_val}")

        elif ptype == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"'{name}' must be a number")
                continue
            float_val = float(value)
            mn, mx = spec.get("min"), spec.get("max")
            if mn is not None and float_val < mn:
                errors.append(f"'{name}' must be >= {mn}, got {float_val}")
            if mx is not None and float_val > mx:
                errors.append(f"'{name}' must be <= {mx}, got {float_val}")

        elif ptype == "bool":
            if not isinstance(value, bool):
                errors.append(f"'{name}' must be a boolean")

    # Unknown params
    unknown = set(params.keys()) - set(schema.keys())
    if unknown:
        errors.append(f"unknown params: {sorted(unknown)}")

    return errors


def _check_constraints(template: str, params: dict) -> str | None:
    """Check cross-param constraints. Returns an error string, or None if valid."""
    if template == "triple_screen":
        fast = params.get("fast_ema")
        slow = params.get("slow_ema")
        if fast is not None and slow is not None and int(fast) >= int(slow):
            return f"fast_ema ({fast}) must be < slow_ema ({slow})"
        long_tf = params.get("long_tf")
        short_tf = params.get("short_tf")
        if long_tf and short_tf:
            if _TF_RANK.get(short_tf, -1) >= _TF_RANK.get(long_tf, -1):
                return f"short_tf ({short_tf!r}) must be shorter than long_tf ({long_tf!r})"

    elif template == "impulse_system":
        fast = params.get("macd_fast")
        slow = params.get("macd_slow")
        if fast is not None and slow is not None and int(fast) >= int(slow):
            return f"macd_fast ({fast}) must be < macd_slow ({slow})"

    return None


def _params_match(a: dict, b: dict) -> bool:
    """True if two param dicts are identical (exact duplicate detection)."""
    if set(a.keys()) != set(b.keys()):
        return False
    return all(a[k] == b[k] for k in a)


# ---------------------------------------------------------------------------
# Data loading and template dispatch
# ---------------------------------------------------------------------------

def _coin_from_security(security: str) -> str:
    """
    Map a security symbol to its OHLCV directory name (e.g. 'BTC-PERP' → 'BTC_PERP').
    Matches the convention used by `prospector.data.download._parquet_path`.
    """
    return security.replace("-", "_")


def _load_ohlcv(coin: str, timeframe: str, data_dir: Path) -> pd.DataFrame:
    """Load OHLCV parquet for a (coin, timeframe) pair."""
    path = data_dir / coin / f"{timeframe}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"OHLCV data not found: {path}. "
            f"Run python -m prospector.data.download to fetch it."
        )
    return pd.read_parquet(path)


def _load_and_run(
    template: str, params: dict, coin: str, data_dir: Path
) -> tuple[list[Signal], pd.DataFrame]:
    """
    Load the required OHLCV data, generate signals, and return (signals, backtest_df).

    backtest_df is the DataFrame that bar indices in signals refer to.
    For triple_screen that is the short-TF frame.
    """
    if template == "false_breakout":
        df = _load_ohlcv(coin, params["timeframe"], data_dir)
        return false_breakout.run(df, params), df

    if template == "triple_screen":
        df_long = _load_ohlcv(coin, params["long_tf"], data_dir)
        df_short = _load_ohlcv(coin, params["short_tf"], data_dir)
        return triple_screen.run(df_long, df_short, params), df_short

    raise ValueError(f"Template not implemented: {template!r}")


def _backtest_security(
    template: str, params: dict, coin: str, data_dir: Path
) -> BacktestResult:
    """Run the full signal-generation + backtest pipeline for one (template, params, coin)."""
    signals, df = _load_and_run(template, params, coin, data_dir)
    return run_backtest(signals, df)


def _dispatch(proposal: dict, data_dir: Path) -> dict[str, BacktestResult]:
    """Run per-security backtests. Returns {security_symbol: BacktestResult}."""
    template = proposal["template"]
    params = proposal["params"]
    results: dict[str, BacktestResult] = {}
    for security in proposal["securities"]:
        coin = _coin_from_security(security)
        results[security] = _backtest_security(template, params, coin, data_dir)
    return results


# ---------------------------------------------------------------------------
# Result aggregation
# ---------------------------------------------------------------------------

def _aggregate(
    per_security: dict[str, BacktestResult],
) -> tuple[str, float | None, dict]:
    """
    Aggregate per-security BacktestResults into a single (status, score, metrics).

    Rules:
      - Any catastrophic result → aggregate is catastrophic, score = -1000.
      - All rejected → aggregate is rejected.
      - Otherwise → mean of scored results.
    """
    results = list(per_security.values())

    for r in results:
        if r.status == "catastrophic":
            return "catastrophic", -1000.0, _result_metrics(r)

    scored = [r for r in results if r.status == "scored"]
    rejected = [r for r in results if r.status == "rejected"]

    if not scored:
        reasons = "; ".join(
            f"{sec}: {r.rejection_reason}" for sec, r in per_security.items()
        )
        m = _result_metrics(rejected[0])
        m["rejection_reason"] = reasons[:500]
        return "rejected", None, m

    # At least one scored; aggregate those (rejected ones had insufficient data)
    n = len(scored)
    agg_score = sum(r.score for r in scored) / n
    metrics = {
        "n_trades": sum(r.n_trades for r in scored),
        "pct_return": sum(r.pct_return for r in scored) / n,
        "max_drawdown": max(r.max_drawdown for r in scored),
        "profit_factor": sum(r.profit_factor for r in scored) / n,
        "win_rate": sum(r.win_rate for r in scored) / n,
        "sharpe_ratio": sum(r.sharpe_ratio for r in scored) / n,
        "rejection_reason": None,
    }
    return "scored", agg_score, metrics


def _result_metrics(r: BacktestResult) -> dict:
    return {
        "n_trades": r.n_trades,
        "pct_return": r.pct_return,
        "max_drawdown": r.max_drawdown,
        "profit_factor": r.profit_factor,
        "win_rate": r.win_rate,
        "sharpe_ratio": r.sharpe_ratio,
        "rejection_reason": r.rejection_reason,
    }


# ---------------------------------------------------------------------------
# Main iteration
# ---------------------------------------------------------------------------

def run_one_iteration(ledger: Ledger, config: AppConfig) -> RunRecord:
    """
    Execute one complete inner-loop iteration.

    All errors are caught, logged to the ledger, and returned as a RunRecord
    so that the loop can continue. A failed iteration counts toward the window
    (the model will see that the previous attempt produced an error).
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    # --- Stagnation detection ---
    recent_templates = ledger.last_n_templates(config.stagnation_n)
    stagnation_note = None
    if (
        len(recent_templates) == config.stagnation_n
        and len(set(recent_templates)) == 1
    ):
        stagnation_note = (
            f"The last {config.stagnation_n} proposals all used "
            f"{recent_templates[0]!r}. Explore a different template."
        )

    # --- Prompt assembly ---
    window_text = ledger.format_sliding_window(config.sliding_window_size)
    prompt = assemble_prompt(window_text, config.securities, stagnation_note)

    # --- LLM call ---
    try:
        raw_response = call_model(prompt, config)
    except Exception as exc:
        record = RunRecord(
            timestamp=now,
            validation_status="system_error",
            error=f"Ollama call failed: {exc}",
        )
        ledger.log(record)
        return record

    # --- Parse response ---
    try:
        proposal = parse_response(raw_response)
    except ValueError as exc:
        record = RunRecord(
            timestamp=now,
            validation_status="invalid_json",
            config_json=raw_response[:2000],
            error=str(exc),
        )
        ledger.log(record)
        return record

    template = proposal.get("template")
    securities = proposal.get("securities", [])
    rationale = proposal.get("rationale")
    thinking = proposal.get("thinking")
    config_json = json.dumps(proposal)
    sec_list = securities if isinstance(securities, list) else []

    # --- Schema + diversity validation ---
    ok, reason = validate_config(
        proposal, set(config.securities), ledger, config.sliding_window_size
    )
    if not ok:
        vstatus = "duplicate" if "Duplicate" in reason else "invalid_schema"
        record = RunRecord(
            timestamp=now,
            validation_status=vstatus,
            template=template,
            config_json=config_json,
            securities=sec_list,
            rationale=rationale,
            thinking=thinking,
            error=reason,
        )
        ledger.log(record)
        return record

    # --- Dispatch to harness ---
    try:
        per_security = _dispatch(proposal, config.data_dir)
    except Exception as exc:
        record = RunRecord(
            timestamp=now,
            validation_status="system_error",
            template=template,
            config_json=config_json,
            securities=sec_list,
            rationale=rationale,
            thinking=thinking,
            error=f"Dispatch error: {exc}",
        )
        ledger.log(record)
        return record

    # --- Aggregate and log ---
    status, score, metrics = _aggregate(per_security)
    sec_results_json = json.dumps({
        sec: {
            "status": r.status,
            "score": r.score,
            "n_trades": r.n_trades,
            "rejection_reason": r.rejection_reason,
        }
        for sec, r in per_security.items()
    })

    record = RunRecord(
        timestamp=now,
        validation_status="valid",
        template=template,
        config_json=config_json,
        securities=sec_list,
        rationale=rationale,
        thinking=thinking,
        backtest_status=status,
        score=score,
        n_trades=metrics.get("n_trades"),
        pct_return=metrics.get("pct_return"),
        max_drawdown=metrics.get("max_drawdown"),
        profit_factor=metrics.get("profit_factor"),
        win_rate=metrics.get("win_rate"),
        sharpe_ratio=metrics.get("sharpe_ratio"),
        rejection_reason=metrics.get("rejection_reason"),
        securities_results_json=sec_results_json,
    )
    ledger.log(record)
    return record


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(config: AppConfig | None = None, max_iterations: int | None = None) -> None:
    """
    Run the inner loop indefinitely (or until max_iterations).

    Ctrl+C stops the loop cleanly after the current iteration completes.
    Each iteration is independent; errors are caught and logged without
    crashing the loop.
    """
    from rich.console import Console

    if config is None:
        config = AppConfig.from_env()

    ledger = Ledger(config.db_path)
    console = Console()

    console.print("[bold green]Prospector inner loop starting[/bold green]")
    console.print(
        f"Model: [cyan]{config.model}[/cyan]  "
        f"Host: [cyan]{config.ollama_host}[/cyan]  "
        f"DB: [cyan]{config.db_path}[/cyan]"
    )

    # Backoff state for consecutive system_error (Ollama unreachable).
    # Delays: 1–4 consecutive → 30 s; 5+ consecutive → 300 s.
    _BACKOFF_SHORT = 30
    _BACKOFF_LONG = 300
    _BACKOFF_THRESHOLD = 5
    consecutive_errors = 0

    iteration = 0
    try:
        while max_iterations is None or iteration < max_iterations:
            iteration += 1
            console.print(f"\n[dim]--- Iteration {ledger.count() + 1} ---[/dim]")

            record = run_one_iteration(ledger, config)

            if record.validation_status == "system_error":
                consecutive_errors += 1
                delay = (
                    _BACKOFF_LONG if consecutive_errors >= _BACKOFF_THRESHOLD else _BACKOFF_SHORT
                )
                console.print(
                    f"  [red]system_error[/red] ({consecutive_errors} consecutive): "
                    f"{record.error}  — backing off {delay}s"
                )
                time.sleep(delay)
                continue

            consecutive_errors = 0

            if record.validation_status != "valid":
                console.print(
                    f"  [yellow]{record.validation_status}[/yellow]: {record.error}"
                )
            elif record.backtest_status == "scored":
                console.print(
                    f"  [green]scored[/green]  {record.template} "
                    f"{','.join(s.replace('-PERP','') for s in record.securities)} "
                    f"score=[bold]{record.score:.1f}[/bold] "
                    f"trades={record.n_trades} "
                    f"dd={record.max_drawdown:.1%}"
                )
            elif record.backtest_status == "rejected":
                console.print(
                    f"  [yellow]rejected[/yellow] {record.template} — "
                    f"{record.rejection_reason}"
                )
            elif record.backtest_status == "catastrophic":
                console.print(
                    f"  [red]catastrophic[/red] {record.template} on "
                    f"{','.join(record.securities)}"
                )

    except KeyboardInterrupt:
        console.print("\n[bold]Loop stopped.[/bold]")
    finally:
        ledger.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    run_loop()
