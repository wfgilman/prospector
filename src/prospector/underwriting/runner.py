"""Main loop for the paper-trading daemon.

Each tick:
  1. Sweep resolutions for open paper positions.
  2. Scan active markets for calibration-driven edge.
  3. Size each candidate by equal-σ (risk-parity) sizing and rank by
     per-trade Sharpe proxy (edge / σ_bin). Enter up to the remaining
     daily trade budget.
  4. Write a daily snapshot.

The σ table is a required dependency — candidates with no σ estimate at
any fallback level are rejected rather than sized from a guess.

The loop is intentionally simple and stateless between ticks; all state
(positions, snapshots) lives in the paper portfolio SQLite database. The
scheduling cadence is the caller's problem — `run_forever()` uses a sleep,
but production usage should be a launchd plist invoking `run_once()`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from prospector.kalshi import KalshiClient
from prospector.underwriting.calibration import Calibration
from prospector.underwriting.monitor import MonitorReport, sweep
from prospector.underwriting.portfolio import PaperPortfolio, RejectedEntry
from prospector.underwriting.scanner import Candidate, scan
from prospector.underwriting.sizing import MissingSigma, SigmaTable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunnerConfig:
    min_edge_pp: float = 5.0
    categories: tuple[str, ...] | None = ("sports", "crypto")
    orderbook_depth: int = 1
    max_candidates_per_tick: int = 200


@dataclass(frozen=True)
class TickReport:
    monitor: MonitorReport
    candidates_seen: int
    entered: int
    rejected: int
    tick_time: datetime


def run_once(
    client: KalshiClient,
    portfolio: PaperPortfolio,
    calibration: Calibration,
    sigma_table: SigmaTable,
    config: RunnerConfig | None = None,
    *,
    now: datetime | None = None,
) -> TickReport:
    """Execute one sweep+scan+snapshot cycle. Returns a TickReport."""
    config = config or RunnerConfig()
    now = now or datetime.now(timezone.utc)

    monitor_report = sweep(client, portfolio)
    logger.info(
        "monitor: resolved=%d voided=%d still_open=%d errors=%d",
        monitor_report.resolved,
        monitor_report.voided,
        monitor_report.still_open,
        monitor_report.errors,
    )

    remaining_today = portfolio.config.max_trades_per_day - portfolio.trades_today(now.date())
    if remaining_today <= 0:
        logger.info("daily trade cap reached; skipping scan")
        portfolio.snapshot_today(now.date())
        return TickReport(
            monitor=monitor_report,
            candidates_seen=0,
            entered=0,
            rejected=0,
            tick_time=now,
        )

    candidates_iter = scan(
        client,
        calibration,
        categories=config.categories,
        min_edge_pp=config.min_edge_pp,
        orderbook_depth=config.orderbook_depth,
    )
    candidates = _collect(candidates_iter, config.max_candidates_per_tick)

    # Attach σ and rank by edge/σ (bin-level Sharpe proxy). Drop candidates
    # with no σ estimate at any fallback level — a signal we can't size is
    # a signal we don't trust.
    sized: list[tuple[Candidate, float]] = []
    for candidate in candidates:
        try:
            entry = sigma_table.lookup(
                candidate.category, candidate.side, candidate.entry_price
            )
        except MissingSigma as exc:
            logger.debug("skip %s: %s", candidate.market.ticker, exc)
            continue
        sized.append((candidate, entry.sigma))
    sized.sort(key=lambda cs: cs[0].edge_pp / cs[1] if cs[1] > 0 else 0.0, reverse=True)

    entered = rejected = 0
    for candidate, sigma_i in sized:
        if entered >= remaining_today:
            break
        if portfolio.has_open_position(candidate.market.ticker):
            continue
        risk_budget = portfolio.size_position(sigma_i=sigma_i)
        if risk_budget <= 0:
            continue
        try:
            portfolio.enter(
                ticker=candidate.market.ticker,
                event_ticker=candidate.market.event_ticker,
                series_ticker=candidate.market.series_ticker or None,
                category=candidate.category,
                side=candidate.side,
                entry_price=candidate.entry_price,
                edge_pp=candidate.edge_pp,
                risk_budget=risk_budget,
                expected_close_time=candidate.market.close_time,
                entry_time=now,
            )
            entered += 1
            logger.info(
                "ENTER %s %s @ %.3f edge=%.2fpp σ=%.3f risk=$%.2f",
                candidate.market.ticker,
                candidate.side,
                candidate.entry_price,
                candidate.edge_pp,
                sigma_i,
                risk_budget,
            )
        except RejectedEntry as exc:
            rejected += 1
            logger.debug("skip %s: %s", candidate.market.ticker, exc)

    portfolio.snapshot_today(now.date())
    return TickReport(
        monitor=monitor_report,
        candidates_seen=len(candidates),
        entered=entered,
        rejected=rejected,
        tick_time=now,
    )


def run_forever(
    client: KalshiClient,
    portfolio: PaperPortfolio,
    calibration: Calibration,
    sigma_table: SigmaTable,
    config: RunnerConfig | None = None,
    *,
    interval_seconds: float = 900.0,
) -> None:
    """Loop `run_once()` forever with a fixed sleep between ticks."""
    while True:
        try:
            report = run_once(client, portfolio, calibration, sigma_table, config)
            logger.info(
                "tick done: entered=%d rejected=%d candidates=%d",
                report.entered,
                report.rejected,
                report.candidates_seen,
            )
        except Exception:
            logger.exception("runner tick failed")
        time.sleep(interval_seconds)


def _collect(it: Iterable[Candidate], cap: int) -> list[Candidate]:
    out: list[Candidate] = []
    for candidate in it:
        out.append(candidate)
        if len(out) >= cap:
            break
    return out
