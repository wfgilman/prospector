"""Per-tick orchestration for the elder triple-screen paper book.

Each tick:
    1. Refresh OHLCV for every cohort coin (incremental Hyperliquid pull).
    2. Sweep open positions; close any whose stop or target was hit on a
       bar printed since the last sweep.
    3. For each cohort coin without an open position, look for a fresh
       signal at the most recent short-TF bar. If one exists and the
       portfolio has cash + capacity, paper-execute it.
    4. Record the daily snapshot.

Live execution wiring (real Hyperliquid orders) is intentionally
out of scope here — this is a paper book.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from prospector.data.client import HyperliquidClient
from prospector.data.download import download_pair
from prospector.strategies.elder_triple_screen.monitor import sweep
from prospector.strategies.elder_triple_screen.portfolio import (
    OpenPosition,
    PaperPortfolio,
)
from prospector.strategies.elder_triple_screen.signal import (
    LOCKED_PARAMS,
    OHLCV_DIR,
    extract_signals,
    load_ohlcv_pair,
)
from prospector.templates.base import Direction

# Each numeric is the bar duration of the matching pandas-style interval.
# Only the values we actually use; expand if the locked TFs change.
_INTERVAL_HOURS = {"1h": 1.0, "4h": 4.0, "1d": 24.0}

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class RunnerConfig:
    universe: list[str]                  # ['BIGTIME-PERP', 'kPEPE-PERP', ...]
    refresh_data: bool = True            # call download_pair each tick
    max_positions: int = 10              # cap concurrent open positions


def _ohlcv_safe_name(coin: str) -> str:
    """Map 'BIGTIME-PERP' → 'BIGTIME_PERP' for the OHLCV path."""
    return coin.replace("-", "_")


def _refresh_ohlcv(coin: str, client: HyperliquidClient) -> None:
    """Pull the latest bars for the locked TFs."""
    safe = _ohlcv_safe_name(coin)
    for interval in (LOCKED_PARAMS["long_tf"], LOCKED_PARAMS["short_tf"]):
        try:
            download_pair(safe, interval, client=client)
        except Exception as exc:  # noqa: BLE001 — surface but don't kill the tick
            log.warning("OHLCV refresh failed for %s/%s: %s", safe, interval, exc)


def _check_freshness(
    universe: list[str],
    short_tf: str,
    now: datetime,
    delisted_threshold: timedelta = timedelta(days=7),
) -> tuple[list[str], list[str]]:
    """Walk the cohort's short-TF parquets and classify each by freshness.

    Returns ``(stale, very_stale)``: lists of cohort coins whose short-TF
    last bar is older than expected. ``stale`` covers coins whose latest
    bar is more than ``2 × short_tf`` old (one or more missed refreshes —
    transient API failure or local-write error). ``very_stale`` covers
    coins whose latest bar is older than ``delisted_threshold`` (likely
    delisted; safe to prune from the cohort permanently).

    Coins missing the parquet file entirely are reported as ``stale``.
    """
    short_tf_hours = _INTERVAL_HOURS.get(short_tf)
    if short_tf_hours is None:
        return [], []
    stale_threshold = timedelta(hours=2 * short_tf_hours)

    stale: list[str] = []
    very_stale: list[str] = []
    for coin in universe:
        safe = _ohlcv_safe_name(coin)
        path = OHLCV_DIR / safe / f"{short_tf}.parquet"
        if not path.exists():
            stale.append(coin)
            continue
        try:
            df = pd.read_parquet(path, columns=["timestamp"])
        except Exception:  # noqa: BLE001 — corrupt parquet → treat as stale
            stale.append(coin)
            continue
        if df.empty:
            stale.append(coin)
            continue
        last = pd.Timestamp(df["timestamp"].max())
        if last.tzinfo is None:
            last = last.tz_localize("UTC")
        gap = pd.Timestamp(now) - last
        if gap > delisted_threshold:
            very_stale.append(coin)
        elif gap > stale_threshold:
            stale.append(coin)
    return stale, very_stale


def _try_open(
    portfolio: PaperPortfolio,
    coin: str,
    df_short: pd.DataFrame,
    bar_index: int,
    direction: Direction,
    entry: float,
    stop: float,
    target: float,
) -> OpenPosition | None:
    """Wrap the portfolio's sizing + open-position rules with paper semantics."""
    units, risk = portfolio.size_position(entry, stop)
    if units <= 0 or risk <= 0:
        return None
    if portfolio.cash() < risk:
        log.info("%s: insufficient cash (%.2f < %.2f), skipping", coin, portfolio.cash(), risk)
        return None
    bar_time = pd.Timestamp(df_short["timestamp"].iloc[bar_index])
    if bar_time.tzinfo is None:
        bar_time = bar_time.tz_localize("UTC")
    pid = portfolio.open_position(
        coin=coin, direction=direction,
        units=units, entry_price=entry,
        stop_price=stop, target_price=target,
        risk_budget=risk,
        entry_bar_index=bar_index,
        entry_time=bar_time.to_pydatetime(),
    )
    log.info(
        "%s: opened %s pos id=%d units=%.4f entry=%.4f stop=%.4f target=%.4f risk=$%.2f",
        coin, direction.value, pid, units, entry, stop, target, risk,
    )
    return OpenPosition(
        id=pid, coin=coin, direction=direction, units=units,
        entry_price=entry, stop_price=stop, target_price=target,
        risk_budget=risk, entry_bar_index=bar_index,
        entry_time=bar_time.isoformat(),
    )


def run_once(portfolio: PaperPortfolio, config: RunnerConfig) -> dict:
    """Single tick. Returns counters for logging."""
    client = HyperliquidClient() if config.refresh_data else None

    if config.refresh_data and client is not None:
        for coin in config.universe:
            _refresh_ohlcv(coin, client)

    # Freshness audit — emit warnings *only* when something is off so
    # healthy ticks stay quiet. Catches the failure mode where the
    # refresh loop appears to succeed (HTTP 200) but no new bars land,
    # or where a transient API failure leaves the cohort behind.
    stale, very_stale = _check_freshness(
        config.universe,
        LOCKED_PARAMS["short_tf"],
        datetime.now(timezone.utc),
    )
    if very_stale:
        log.warning(
            "OHLCV very stale (>7d) on %d coin(s) — likely delisted, prune from cohort: %s",
            len(very_stale), very_stale,
        )
    if stale:
        log.warning(
            "OHLCV stale (>2x short_tf) on %d coin(s) — refresh likely failed: %s",
            len(stale), stale,
        )

    # Phase 1 — sweep stops/targets first so cash unlocks before re-entering.
    closed = sweep(portfolio)
    n_closed = len(closed)

    # Phase 2 — open new positions on fresh signals.
    n_opened = 0
    n_skipped_open = 0
    for coin in config.universe:
        if portfolio.has_open_position(coin):
            continue
        if len(portfolio.open_positions()) >= config.max_positions:
            n_skipped_open += 1
            continue
        try:
            sigs, df_short = extract_signals(coin)
        except FileNotFoundError:
            continue
        if df_short.empty:
            continue
        latest_idx = len(df_short) - 1
        fresh = [s for s in sigs if s.bar_index == latest_idx]
        if not fresh:
            continue
        sig = fresh[0]   # take the most recent matching signal
        opened = _try_open(
            portfolio, coin, df_short, sig.bar_index,
            sig.direction, sig.entry, sig.stop, sig.target,
        )
        if opened is not None:
            n_opened += 1
        else:
            n_skipped_open += 1

    portfolio.upsert_daily_snapshot(datetime.now(timezone.utc).date())

    return {
        "closed": n_closed,
        "opened": n_opened,
        "skipped_open": n_skipped_open,
        "open_after_tick": len(portfolio.open_positions()),
        "nav": portfolio.nav(),
    }


def run_forever(
    portfolio: PaperPortfolio,
    config: RunnerConfig,
    interval_seconds: float = 4 * 3600,
) -> None:
    import time
    log.info("elder_triple_screen daemon online — interval=%.0fs", interval_seconds)
    while True:
        try:
            stats = run_once(portfolio, config)
            log.info("tick: %s", stats)
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        # Sleep helper that's interruptible enough for launchd / Ctrl-C.
        for _ in range(int(interval_seconds // 1)):
            time.sleep(1)


def cohort_universe_from(cohorts_file: Path, label: str) -> list[str]:
    """Helper: read /tmp/cohorts.json (or any cohort file) and return tickers."""
    import json
    raw = json.loads(cohorts_file.read_text())
    coins = raw[label]
    # Convert XAI_PERP → XAI-PERP for the runner's external surface.
    return [c.replace("_PERP", "-PERP") if "_PERP" in c else c for c in coins]


__all__ = [
    "RunnerConfig",
    "run_once",
    "run_forever",
    "cohort_universe_from",
]


def load_ohlcv_pair_external(coin: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Re-export of `signal.load_ohlcv_pair` for ad-hoc inspection."""
    return load_ohlcv_pair(coin)
