"""Fit Hyperliquid BTC_PERP implied terminal distribution for each Kalshi snapshot.

Week-1 spike for strategy #10. Hyperparameters locked per deep-dive §5.0.

For each unique (snapshot_ts, event_ticker), compute a lognormal CDF at the
Kalshi strike-ladder grid, using:
  - spot: most recent BTC_PERP close at or before snapshot_ts
  - sigma: EWMA(lambda=0.94) of 1h log-returns over preceding 48h
  - drift: 0 (locked)
  - T-t: close_time - snapshot_ts, in years
  - log-price centering: ln(S_T) ~ N(ln(S_0), sigma**2 * T); no Ito correction

Output: parquet at `data/vol_surface/perp_implied.parquet` keyed by
    (event_ticker, snapshot_ts, strike_mid) -> q_i (bucket probability),
    bucket_lower, bucket_upper, spot, sigma_annual, years_to_close.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# --- Pre-registered hyperparameters (see §5.0) ---------------------------------
EWMA_LAMBDA = 0.94
EWMA_LOOKBACK_HOURS = 48
DRIFT_ANNUAL = 0.0
HOURS_PER_YEAR = 24 * 365.25
# --------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LADDER_PATH = REPO_ROOT / "data" / "vol_surface" / "kalshi_ladder.parquet"
OHLCV_PATH = REPO_ROOT / "data" / "ohlcv" / "BTC_PERP" / "1h.parquet"
OUT_PATH = REPO_ROOT / "data" / "vol_surface" / "perp_implied.parquet"


def norm_cdf(z: np.ndarray) -> np.ndarray:
    # 0.5 * (1 + erf(z / sqrt(2)))
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def ewma_sigma_annual(log_returns_1h: np.ndarray, lam: float) -> float:
    """EWMA variance of 1h log-returns -> annualized sigma."""
    if len(log_returns_1h) == 0:
        return float("nan")
    # 1-index weights from oldest to newest; most recent has largest weight.
    n = len(log_returns_1h)
    weights = np.array([(1 - lam) * (lam ** (n - 1 - i)) for i in range(n)])
    weights /= weights.sum()
    var_hourly = float(np.sum(weights * (log_returns_1h ** 2)))
    # Annualize: sigma_annual = sigma_hourly * sqrt(HOURS_PER_YEAR)
    return math.sqrt(var_hourly * HOURS_PER_YEAR)


def main() -> None:
    con = duckdb.connect()

    # Load event-level metadata (close_time per event) + unique snapshots with
    # bucket bounds. We only need one (event, snapshot) row per bucket so the
    # fitter can return a q_i for each bucket.
    print("[1/3] loading ladder snapshots + event close times...")
    ladder = con.execute(f"""
        WITH events AS (
            SELECT
                event_ticker,
                MAX(snapshot_ts) AS last_snap
            FROM read_parquet('{LADDER_PATH}')
            GROUP BY event_ticker
        ),
        -- close_time isn't stored in the ladder; recover it from markets.
        closes AS (
            SELECT DISTINCT event_ticker, close_time
            FROM read_parquet('{REPO_ROOT}/data/kalshi_hf/markets-*.parquet')
            WHERE event_ticker LIKE 'KXBTC-%'
        )
        SELECT
            l.event_ticker,
            l.snapshot_ts,
            l.strike_mid,
            l.bucket_lower,
            l.bucket_upper,
            c.close_time
        FROM read_parquet('{LADDER_PATH}') l
        JOIN closes c USING (event_ticker)
        ORDER BY l.event_ticker, l.snapshot_ts, l.strike_mid
    """).fetchdf()
    print(f"      {len(ladder):,} (event, snapshot, bucket) rows")

    print("[2/3] loading BTC_PERP 1h OHLCV and computing EWMA sigma...")
    ohlcv = pd.read_parquet(OHLCV_PATH).sort_values("timestamp").reset_index(drop=True)
    ohlcv["log_close"] = np.log(ohlcv["close"])
    ohlcv["log_return"] = ohlcv["log_close"].diff()

    # Pre-compute rolling EWMA annualized sigma on the OHLCV grid itself.
    ohlcv["ewma_sigma_annual"] = np.nan
    for i in range(EWMA_LOOKBACK_HOURS, len(ohlcv)):
        rets = ohlcv["log_return"].iloc[
            i - EWMA_LOOKBACK_HOURS + 1 : i + 1
        ].dropna().to_numpy()
        if len(rets) < EWMA_LOOKBACK_HOURS // 2:
            continue
        ohlcv.loc[i, "ewma_sigma_annual"] = ewma_sigma_annual(rets, EWMA_LAMBDA)

    ohlcv_clean = ohlcv.dropna(subset=["ewma_sigma_annual"])
    print(
        f"      OHLCV {len(ohlcv):,} rows, "
        f"{len(ohlcv_clean):,} with valid EWMA sigma "
        f"(requires {EWMA_LOOKBACK_HOURS}h lookback)"
    )

    # Ladder snapshot_ts is TZ-aware (America/Los_Angeles). Convert to UTC to
    # align with OHLCV timestamp (UTC).
    ladder["snapshot_ts_utc"] = pd.to_datetime(
        ladder["snapshot_ts"], utc=True
    )
    ladder["close_time_utc"] = pd.to_datetime(
        ladder["close_time"], utc=True
    )

    # ASOF-join spot and sigma to each snapshot_ts.
    print("[3/3] asof-joining spot + sigma to each snapshot and computing q_i...")
    ohlcv_compact = ohlcv_clean[
        ["timestamp", "close", "ewma_sigma_annual"]
    ].rename(columns={"timestamp": "ts_utc", "close": "spot"})
    ohlcv_compact = ohlcv_compact.sort_values("ts_utc").reset_index(drop=True)

    # DuckDB ASOF for speed
    con.register("ladder_df", ladder)
    con.register("ohlcv_df", ohlcv_compact)
    joined = con.execute("""
        SELECT
            l.event_ticker,
            l.snapshot_ts,
            l.snapshot_ts_utc,
            l.close_time_utc,
            l.strike_mid,
            l.bucket_lower,
            l.bucket_upper,
            o.spot,
            o.ewma_sigma_annual
        FROM ladder_df l
        ASOF LEFT JOIN ohlcv_df o
            ON l.snapshot_ts_utc >= o.ts_utc
        ORDER BY l.event_ticker, l.snapshot_ts, l.strike_mid
    """).fetchdf()

    n_missing = joined["spot"].isna().sum()
    print(f"      {n_missing:,} rows with no spot/sigma (pre-OHLCV-coverage, dropped)")
    joined = joined.dropna(subset=["spot", "ewma_sigma_annual"]).reset_index(drop=True)

    # years_to_close (must be positive; if snapshot >= close, drop)
    hours_to_close = (
        (joined["close_time_utc"] - joined["snapshot_ts_utc"]).dt.total_seconds()
        / 3600.0
    )
    joined["years_to_close"] = hours_to_close / HOURS_PER_YEAR
    n_pre = len(joined)
    joined = joined[joined["years_to_close"] > 0].reset_index(drop=True)
    print(f"      {n_pre - len(joined):,} rows at/after close dropped")

    # Lognormal CDF at bucket edges; q_i = F(upper) - F(lower)
    sigma_sqrt_T = joined["ewma_sigma_annual"] * np.sqrt(joined["years_to_close"])
    log_spot = np.log(joined["spot"])
    # drift = 0 and no Ito correction by locked choice
    z_upper = (np.log(joined["bucket_upper"]) - log_spot) / sigma_sqrt_T
    z_lower = (np.log(joined["bucket_lower"]) - log_spot) / sigma_sqrt_T
    F_upper = norm_cdf(z_upper.to_numpy())
    F_lower = norm_cdf(z_lower.to_numpy())
    joined["q_raw"] = F_upper - F_lower

    # Renormalize per (event, snapshot) so that q sums to 1 across the buckets
    # actually present — apples-to-apples with the renormalized Kalshi ladder.
    joined["q_renorm"] = (
        joined["q_raw"]
        / joined.groupby(["event_ticker", "snapshot_ts"])["q_raw"].transform("sum")
    )

    out_cols = [
        "event_ticker",
        "snapshot_ts",
        "strike_mid",
        "bucket_lower",
        "bucket_upper",
        "spot",
        "ewma_sigma_annual",
        "years_to_close",
        "q_raw",
        "q_renorm",
    ]
    out = joined[out_cols].sort_values(
        ["event_ticker", "snapshot_ts", "strike_mid"]
    )
    out.to_parquet(OUT_PATH, index=False)
    n_events = out["event_ticker"].nunique()
    n_snaps = out.drop_duplicates(["event_ticker", "snapshot_ts"]).shape[0]
    print(
        f"\nwrote {OUT_PATH}\n"
        f"  rows: {len(out):,}\n"
        f"  events: {n_events:,}\n"
        f"  unique (event, snapshot) pairs: {n_snaps:,}\n"
        f"  spot range: ${out['spot'].min():,.0f} – ${out['spot'].max():,.0f}\n"
        f"  sigma (annualized): "
        f"p10={out['ewma_sigma_annual'].quantile(0.1):.2f}, "
        f"p50={out['ewma_sigma_annual'].median():.2f}, "
        f"p90={out['ewma_sigma_annual'].quantile(0.9):.2f}"
    )


if __name__ == "__main__":
    main()
