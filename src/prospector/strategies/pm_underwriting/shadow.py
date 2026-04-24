"""Shadow ledger for PM-Underwriting positions rejected on structural filters.

Paper trading has a narrow validation window: positions that resolve more
than a few weeks out return no signal in time for the strategy to be
validated. We filter them out at entry time. But those positions would
have been tradeable in a real portfolio, and we'd like to reconstruct the
counterfactual "what if we didn't screen them" result later.

This module writes full candidate metadata to a parquet file each time
a candidate is rejected on a structural filter (not fee/sizing/guardrail
— those are real-portfolio constraints too). The parquet carries enough
information to replay the rejection against a shadow PaperPortfolio
downstream: ticker, category, side, entry_price, edge_pp, σ_bin, the
risk_budget we'd have assigned, and the close_time so a reconstruction
script can resolve each shadow position post-hoc.

Storage: `data/paper/pm_underwriting/shadow/shadow_rejections.parquet`
(single file, deduped on (ticker, reject_date) so re-scanning the same
market across ticks on the same day doesn't duplicate rows).

Rejection reasons are enumerated so we can add more filters later
(e.g., low-liquidity screen, event-type screen) without changing the
parquet schema.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ShadowRejection:
    """One rejected candidate with everything needed for counterfactual replay."""

    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    side: str                        # "sell_yes" | "buy_yes"
    entry_price: float
    edge_pp: float
    sigma_bin: float
    risk_budget: float               # what portfolio.size_position would have returned
    close_time: datetime | None
    entry_time: datetime
    reject_reason: str               # e.g. "expiry_gt_28d"


def _path(root: Path) -> Path:
    return root / "shadow" / "shadow_rejections.parquet"


def _to_df(rows: list[ShadowRejection]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "ticker", "event_ticker", "series_ticker", "category", "side",
                "entry_price", "edge_pp", "sigma_bin", "risk_budget",
                "close_time", "entry_time", "reject_reason",
            ]
        )
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    return df


def write_rejections(rows: list[ShadowRejection], root: Path) -> dict:
    """Append rejections to the shadow parquet, deduping on (ticker, date).

    `root` is the PM paper-portfolio root (e.g. `data/paper/pm_underwriting`).
    Returns {total_rows_after_write, rows_added}."""
    if not rows:
        return {"total_rows_after_write": 0, "rows_added": 0}
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    new_df = _to_df(rows)
    new_df["reject_date"] = new_df["entry_time"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")

    existing_len = 0
    if path.exists():
        existing = pd.read_parquet(path)
        existing_len = len(existing)
        if "reject_date" not in existing.columns:
            existing["reject_date"] = existing["entry_time"].dt.tz_convert(
                "UTC"
            ).dt.strftime("%Y-%m-%d")
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    # Dedupe on (ticker, reject_date): first-seen rejection per ticker per UTC
    # day wins. Re-scans of the same market across ticks on the same day
    # don't accumulate, but the shadow ledger accumulates over days so we
    # can track decay / re-appearance.
    combined = combined.drop_duplicates(
        subset=["ticker", "reject_date"], keep="first"
    ).sort_values("entry_time").reset_index(drop=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    combined.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return {
        "total_rows_after_write": len(combined),
        "rows_added": len(combined) - existing_len,
    }
