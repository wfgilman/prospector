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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from prospector.kalshi import KalshiClient
from prospector.strategies.pm_underwriting.calibration import Calibration
from prospector.strategies.pm_underwriting.monitor import MonitorReport, sweep
from prospector.strategies.pm_underwriting.portfolio import PaperPortfolio, RejectedEntry
from prospector.strategies.pm_underwriting.scanner import Candidate, scan
from prospector.strategies.pm_underwriting.shadow import ShadowRejection, write_rejections
from prospector.strategies.pm_underwriting.sizing import MissingSigma, SigmaTable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunnerConfig:
    min_edge_pp: float = 5.0
    categories: tuple[str, ...] | None = ("sports", "crypto")
    orderbook_depth: int = 1
    max_candidates_per_tick: int = 200
    # Time-to-close window. The calibration store is built from PIT prices
    # sampled at each market's mid-life — so its predictions are *implicitly*
    # conditioned on a "mid-life" state. Entering markets at end-of-life
    # (e.g. NBA player props at 0.99 with 30min to tipoff) samples a
    # different state distribution where the calibration's edge does not
    # hold. Empirical evidence in the 2026-04-21 → 2026-04-29 paper window:
    # entries with <6h to close had a ~2.6% win rate vs. calibration's
    # predicted ~13%; entries at [6,24)h matched calibration. So the
    # default window matches the regime the calibration was fit on.
    # Rejections write to the shadow ledger for counterfactual replay.
    # See `docs/rd/candidates/01-pm-underwriting-lottery.md` decision log
    # 2026-04-29.
    min_hours_to_close: float | None = 6.0
    max_hours_to_close: float | None = 24.0
    # Where shadow rejections are written. Usually the paper-portfolio root.
    shadow_ledger_root: Path | None = None
    # Entry-price band — used to scope a book to a slice of the calibration
    # surface. Defaults `(0, 1)` keep the lottery-book behavior (edge/σ pulls
    # to 85-99¢ extremes naturally). Setting e.g. `(0.55, 0.75)` builds an
    # "insurance" book: high-WR, low-variance favorites at moderate prices.
    # Filter is applied AFTER the σ-rank, so candidates outside the band
    # never enter regardless of edge magnitude. See fresh-eyes-review §4 (T1).
    entry_price_min: float = 0.0
    entry_price_max: float = 1.0


@dataclass(frozen=True)
class TickReport:
    monitor: MonitorReport
    candidates_seen: int
    entered: int
    rejected: int
    shadow_rejected: int         # rejected on time-to-close window (logged to shadow ledger)
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
            shadow_rejected=0,
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

    min_close_time = None
    if config.min_hours_to_close is not None:
        min_close_time = now + timedelta(hours=config.min_hours_to_close)
    max_close_time = None
    if config.max_hours_to_close is not None:
        max_close_time = now + timedelta(hours=config.max_hours_to_close)

    entered = rejected = shadow_rejected = 0
    shadow_rows: list[ShadowRejection] = []
    for candidate, sigma_i in sized:
        if entered >= remaining_today:
            break
        if portfolio.has_open_position(candidate.market.ticker):
            continue

        # Entry-price band filter — scopes the book to a slice of the
        # calibration surface (e.g. insurance band 0.55-0.75).
        if (
            candidate.entry_price < config.entry_price_min
            or candidate.entry_price > config.entry_price_max
        ):
            continue

        # Structural time-to-close window. Reject markets outside
        # [min_hours_to_close, max_hours_to_close] but log to shadow
        # ledger so we can replay counterfactuals (e.g. did adding
        # the late-life cutoff actually help?).
        out_of_window_reason: str | None = None
        if (
            min_close_time is not None
            and candidate.market.close_time is not None
            and candidate.market.close_time < min_close_time
        ):
            out_of_window_reason = f"ttc_lt_{config.min_hours_to_close:g}h"
        elif (
            max_close_time is not None
            and candidate.market.close_time is not None
            and candidate.market.close_time > max_close_time
        ):
            out_of_window_reason = f"ttc_gt_{config.max_hours_to_close:g}h"
        if out_of_window_reason is not None:
            would_be_risk = portfolio.size_position(sigma_i=sigma_i)
            shadow_rows.append(ShadowRejection(
                ticker=candidate.market.ticker,
                event_ticker=candidate.market.event_ticker,
                series_ticker=candidate.market.series_ticker or "",
                category=candidate.category,
                side=candidate.side,
                entry_price=candidate.entry_price,
                edge_pp=candidate.edge_pp,
                sigma_bin=sigma_i,
                risk_budget=would_be_risk,
                close_time=candidate.market.close_time,
                entry_time=now,
                reject_reason=out_of_window_reason,
            ))
            shadow_rejected += 1
            logger.debug(
                "SHADOW %s close=%s edge=%.2fpp (%s)",
                candidate.market.ticker,
                candidate.market.close_time,
                candidate.edge_pp,
                out_of_window_reason,
            )
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

    if shadow_rows and config.shadow_ledger_root is not None:
        write_rejections(shadow_rows, config.shadow_ledger_root)
        logger.info(
            "shadow: logged %d expiry-screened candidates to %s",
            len(shadow_rows), config.shadow_ledger_root,
        )

    portfolio.snapshot_today(now.date())
    return TickReport(
        monitor=monitor_report,
        candidates_seen=len(candidates),
        entered=entered,
        rejected=rejected,
        shadow_rejected=shadow_rejected,
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
