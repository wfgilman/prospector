"""Phase 1 diagnostic for strategy #10 (post Week-1 failure).

Four pure measurements on the current HF panel. No new hyperparameters beyond
the interpretation thresholds locked below. Outputs written to
    data/vol_surface/diagnostic/{d1,d2,d3,d4}.{parquet,txt}
and a combined summary at `data/vol_surface/diagnostic/summary.txt`.

Each diagnostic answers one specific question about why Week-1 failed:

  D1: Is the gap a structural wedge (consistent sign by bucket position
      relative to spot) or random noise?
  D2: Do gaps converge mechanically in the last N% of event life (masked by
      pooling across the full lifetime)?
  D3: Is the lognormal reference family the problem? Compare vs. an
      empirical-bootstrap reference drawn from rolling 25h BTC returns.
  D4: Does the edge live in moderate-volume events (n_trades 100-500) that
      the min_trades=500 filter excluded?

Pre-registered interpretation rules (see §13.4):
  D1 PASS = any relative-position bucket has |mean signed gap| > 0.03 AND
           t-stat > 3 (structural wedge, tradeable with calibration)
  D2 PASS = regression of mean_abs_gap on life-decile has slope < -0.005
           per decile (terminal convergence present)
  D3 PASS = empirical-bootstrap median gap < 50% of lognormal median gap
           (lognormal reference family was the problem)
  D4 PASS = moderate-volume median gap > 2x high-volume AND reversion
           beta < -0.1 (edge lives in the filtered-out universe)

At least one PASS = continue to Phase 2. Zero PASS = pivot to #4.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# --- Pre-registered interpretation thresholds (see §13.4) ---------------------
D1_MIN_WEDGE_MAGNITUDE = 0.03       # 3pp signed gap at some relative position
D1_MIN_T_STAT = 3.0
D2_MAX_SLOPE_FOR_CONVERGENCE = -0.005  # gap shrinks at least 5pp across 10 deciles
D3_MAX_EMPIRICAL_RATIO = 0.50       # empirical median < 50% of lognormal median
D4_MIN_GAP_RATIO = 2.0              # moderate/high median gap ratio
D4_MAX_REVERSION_BETA = -0.10       # meaningful mean reversion

# D4 universe bounds
D4_MIN_TRADES = 100
D4_MAX_TRADES = 500                 # exclusive upper bound

# D3 bootstrap window
BOOTSTRAP_LOOKBACK_DAYS = 30
EVENT_HORIZON_HOURS = 25            # Kalshi BTC intraday events are ~25h
HOURS_PER_YEAR = 24 * 365.25

# Shared
MIN_LADDER_COMPLETENESS = 0.75      # same as divergence_study.py
# --------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LADDER_PATH = REPO_ROOT / "data" / "vol_surface" / "kalshi_ladder.parquet"
PERP_PATH = REPO_ROOT / "data" / "vol_surface" / "perp_implied.parquet"
OHLCV_PATH = REPO_ROOT / "data" / "ohlcv" / "BTC_PERP" / "1h.parquet"
# D2 needs event open/close times. Source migrated to unified tree 2026-04-23.
KALSHI_DIR = REPO_ROOT / "data" / "kalshi"
OUT_DIR = REPO_ROOT / "data" / "vol_surface" / "diagnostic"


def load_joined(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load ladder ⨝ perp filtered to completeness ≥ 0.75.

    Includes both raw and renormalized p/q so D1 can report both spaces.
    Renorm space is the primary D1 signal (compares two probability measures
    over the same visible support). Raw space is the robustness check —
    tells us whether the wedge exists in prices-you-actually-trade, not
    just in our analytical renormalization."""
    return con.execute(f"""
        SELECT
            l.event_ticker,
            l.snapshot_ts,
            l.strike_mid,
            l.bucket_lower,
            l.bucket_upper,
            l.yes_mid_renorm AS p,
            l.yes_mid_raw AS p_raw,
            q.q_renorm AS q,
            q.q_raw AS q_raw,
            q.spot,
            q.ewma_sigma_annual,
            q.years_to_close,
            l.ladder_completeness
        FROM read_parquet('{LADDER_PATH}') l
        JOIN read_parquet('{PERP_PATH}') q
          USING (event_ticker, snapshot_ts, strike_mid)
        WHERE l.ladder_completeness >= {MIN_LADDER_COMPLETENESS}
        ORDER BY event_ticker, snapshot_ts, strike_mid
    """).fetchdf()


def load_event_meta(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """open_time + close_time per event — for D2's life-fraction."""
    return con.execute(f"""
        SELECT DISTINCT event_ticker, open_time, close_time
        FROM read_parquet('{KALSHI_DIR}/markets/date=*/part.parquet')
        WHERE event_ticker LIKE 'KXBTC-%'
    """).fetchdf()


def norm_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# D1 — Per-bucket-position signed gap
# ---------------------------------------------------------------------------

def _signed_gap_table(
    df: pd.DataFrame, p_col: str, q_col: str, space: str
) -> tuple[pd.DataFrame, dict]:
    """Compute signed gap (p - q) per relative position. Returns the full
    table plus a summary of the max |mean_signed_gap| with ≥100 obs."""
    sg = df[p_col] - df[q_col]
    agg = (
        pd.DataFrame({"rel_position": df["rel_position"], "sg": sg})
        .groupby("rel_position")
        .agg(n=("sg", "size"), mean=("sg", "mean"), std=("sg", "std"),
             median=("sg", "median"))
        .reset_index()
    )
    agg["t_stat"] = agg["mean"] / (agg["std"] / np.sqrt(agg["n"]))
    agg["abs_mean"] = agg["mean"].abs()
    agg["space"] = space
    trim = agg[agg["n"] >= 100]
    max_row = (
        trim.loc[trim["abs_mean"].idxmax()] if len(trim) else None
    )
    summary = {
        "n_positions_with_100plus": int(len(trim)),
        "max_abs_mean_signed_gap": float(trim["abs_mean"].max()) if len(trim) else 0.0,
        "at_rel_position": int(max_row["rel_position"]) if max_row is not None else None,
        "t_stat_at_max": float(max_row["t_stat"]) if max_row is not None else float("nan"),
        "n_at_max": int(max_row["n"]) if max_row is not None else 0,
    }
    return agg, summary


def diagnostic_d1(df: pd.DataFrame) -> dict:
    """Signed gap (p - q) by relative bucket position vs. spot.

    Reports both renormalized and raw spaces:
      - Renorm: compares two probability measures over the same visible
        support (our analytical object). Primary signal.
      - Raw: tests whether the wedge exists in the prices you'd actually
        trade at (robustness check; rules out renormalization artifact)."""
    df = df.copy()
    df["bucket_width"] = df["bucket_upper"] - df["bucket_lower"]
    df["rel_position"] = np.round(
        (df["strike_mid"] - df["spot"]) / df["bucket_width"]
    ).astype(int)

    renorm_tbl, renorm_summary = _signed_gap_table(df, "p", "q", "renorm")
    raw_tbl, raw_summary = _signed_gap_table(df, "p_raw", "q_raw", "raw")

    combined = pd.concat([renorm_tbl, raw_tbl], ignore_index=True)
    combined.to_parquet(OUT_DIR / "d1_signed_gap_by_rel_position.parquet", index=False)

    # Pass rule: require both the renorm and raw space to clear the threshold,
    # so the signal isn't a renormalization artifact.
    renorm_pass = (
        renorm_summary["max_abs_mean_signed_gap"] > D1_MIN_WEDGE_MAGNITUDE
        and abs(renorm_summary["t_stat_at_max"]) > D1_MIN_T_STAT
    )
    raw_pass = (
        raw_summary["max_abs_mean_signed_gap"] > D1_MIN_WEDGE_MAGNITUDE
        and abs(raw_summary["t_stat_at_max"]) > D1_MIN_T_STAT
    )

    return {
        "label": "D1 per-bucket-position signed gap",
        "renorm_space": renorm_summary,
        "raw_space": raw_summary,
        "renorm_pass": bool(renorm_pass),
        "raw_pass": bool(raw_pass),
        "pass": bool(renorm_pass and raw_pass),
    }


# ---------------------------------------------------------------------------
# D2 — Terminal convergence
# ---------------------------------------------------------------------------

def diagnostic_d2(df: pd.DataFrame, events: pd.DataFrame) -> dict:
    """Compute per-snapshot |gap| and KL, then aggregate by life decile.

    Life fraction = (snapshot_ts - open_time) / (close_time - open_time).
    Regress mean_abs_gap on life_decile. Negative slope steeper than the
    pre-registered threshold indicates terminal convergence."""
    df = df.copy()
    eps = 1e-12
    df["abs_gap"] = np.abs(df["p"] - df["q"])
    df["kl_term"] = np.where(
        df["p"] > eps,
        df["p"] * np.log((df["p"] + eps) / (df["q"] + eps)),
        0.0,
    )
    # Collapse to (event, snapshot).
    snap = df.groupby(["event_ticker", "snapshot_ts"], as_index=False).agg(
        max_abs_gap=("abs_gap", "max"),
        mean_abs_gap=("abs_gap", "mean"),
        kl_divergence=("kl_term", "sum"),
    )
    snap["snapshot_ts"] = pd.to_datetime(snap["snapshot_ts"], utc=True)
    # Attach event open/close times.
    events = events.copy()
    events["open_time"] = pd.to_datetime(events["open_time"], utc=True)
    events["close_time"] = pd.to_datetime(events["close_time"], utc=True)
    merged = snap.merge(events, on="event_ticker", how="left")
    denom = (
        (merged["close_time"] - merged["open_time"]).dt.total_seconds()
    )
    numer = (merged["snapshot_ts"] - merged["open_time"]).dt.total_seconds()
    merged["life_fraction"] = numer / denom
    merged = merged[
        (merged["life_fraction"] >= 0) & (merged["life_fraction"] <= 1)
    ]
    merged["life_decile"] = np.minimum(
        (merged["life_fraction"] * 10).astype(int), 9
    )

    agg = merged.groupby("life_decile").agg(
        n=("mean_abs_gap", "size"),
        mean_abs_gap=("mean_abs_gap", "mean"),
        median_abs_gap=("mean_abs_gap", "median"),
        mean_kl=("kl_divergence", "mean"),
    ).reset_index()

    # Linear regression: mean_abs_gap = alpha + beta * life_decile.
    if len(agg) >= 2:
        beta, alpha = np.polyfit(agg["life_decile"], agg["mean_abs_gap"], 1)
    else:
        beta = float("nan")
        alpha = float("nan")

    passing = (
        not math.isnan(beta) and beta < D2_MAX_SLOPE_FOR_CONVERGENCE
    )

    agg.to_parquet(OUT_DIR / "d2_gap_by_life_decile.parquet", index=False)

    return {
        "label": "D2 terminal convergence",
        "slope_gap_vs_life_decile": float(beta),
        "intercept": float(alpha),
        "gap_decile_0": float(agg.iloc[0]["mean_abs_gap"]) if len(agg) else float("nan"),
        "gap_decile_9": float(agg.iloc[-1]["mean_abs_gap"]) if len(agg) else float("nan"),
        "pass": bool(passing),
    }


# ---------------------------------------------------------------------------
# D3 — Empirical-bootstrap reference
# ---------------------------------------------------------------------------

def diagnostic_d3(df: pd.DataFrame, ohlcv: pd.DataFrame) -> dict:
    """Replace lognormal q_i with an empirical-bootstrap reference.

    For each snapshot:
      1. Compute spot = current BTC_PERP close at snapshot_ts (already in df).
      2. Take the preceding BOOTSTRAP_LOOKBACK_DAYS of 1h closes;
         compute rolling 25h log-returns; use as bootstrap sample.
      3. For each bucket, q_emp = empirical fraction of sampled terminal
         prices landing in [bucket_lower, bucket_upper). Renormalize over
         visible buckets.
      4. Compute per-snapshot max |p - q_emp| and median gap.

    Compare to lognormal gaps from the existing panel.
    """
    df = df.copy()
    ohlcv = ohlcv.copy().sort_values("timestamp").reset_index(drop=True)
    ohlcv["timestamp"] = pd.to_datetime(ohlcv["timestamp"], utc=True)
    ohlcv["log_close"] = np.log(ohlcv["close"])
    # 25h-ahead log return for every 1h bar.
    ohlcv["log_ret_25h"] = ohlcv["log_close"].shift(-EVENT_HORIZON_HOURS) - ohlcv["log_close"]

    # Build a lookup of (timestamp -> preceding N days of 25h returns).
    lookback_hours = BOOTSTRAP_LOOKBACK_DAYS * 24

    df["snapshot_ts_utc"] = pd.to_datetime(df["snapshot_ts"], utc=True)
    # Per (event, snapshot), compute empirical q at each bucket using
    # bootstrap sample from [snapshot_ts - 30d, snapshot_ts]. This is a per-
    # snapshot loop but the sample size is small (~720 returns) so tractable.

    # Pre-extract bar times as tz-naive UTC int64 ns for fast searches
    # (avoids the tz-aware-vs-naive comparison error in searchsorted).
    # Force ns unit explicitly — OHLCV parquet is stored as datetime64[ms,UTC]
    # and astype("int64") on that returns ms since epoch, not ns.
    bar_times_ns = (
        ohlcv["timestamp"].dt.tz_convert("UTC").astype("datetime64[ns, UTC]")
        .astype("int64").to_numpy()
    )
    log_rets_25h = ohlcv["log_ret_25h"].to_numpy()

    # Unique snapshots (one sample per snapshot; bucket loop is vectorized).
    snaps = df[["event_ticker", "snapshot_ts_utc", "spot"]].drop_duplicates(
        subset=["event_ticker", "snapshot_ts_utc"]
    ).sort_values("snapshot_ts_utc").reset_index(drop=True)

    records = []
    n_dropped = 0
    for _, row in snaps.iterrows():
        ts = row["snapshot_ts_utc"]
        spot = row["spot"]
        start = ts - pd.Timedelta(hours=lookback_hours)
        ts_ns = ts.value
        start_ns = start.value
        i0 = np.searchsorted(bar_times_ns, start_ns)
        i1 = np.searchsorted(bar_times_ns, ts_ns)
        sample = log_rets_25h[i0:i1]
        sample = sample[~np.isnan(sample)]
        if len(sample) < 30:
            n_dropped += 1
            continue
        terminal_prices = spot * np.exp(sample)
        records.append({
            "event_ticker": row["event_ticker"],
            "snapshot_ts_utc": ts,
            "terminal_prices": terminal_prices,
        })

    if not records:
        return {
            "label": "D3 empirical-bootstrap reference",
            "error": "no bootstrap samples available (insufficient OHLCV history)",
            "pass": False,
        }

    # Now join the per-snapshot terminal_prices back with the bucket rows to
    # compute q_emp.
    snap_samples = {
        (r["event_ticker"], r["snapshot_ts_utc"]): r["terminal_prices"]
        for r in records
    }

    df_emp = df.copy()
    df_emp["snapshot_ts_utc"] = pd.to_datetime(df_emp["snapshot_ts"], utc=True)
    q_emp = np.full(len(df_emp), np.nan)
    for idx, row in df_emp.iterrows():
        key = (row["event_ticker"], row["snapshot_ts_utc"])
        sample = snap_samples.get(key)
        if sample is None:
            continue
        hits = ((sample >= row["bucket_lower"]) & (sample < row["bucket_upper"])).sum()
        q_emp[idx] = hits / len(sample)
    df_emp["q_emp_raw"] = q_emp
    df_emp = df_emp.dropna(subset=["q_emp_raw"])
    # Renormalize per snapshot.
    df_emp["q_emp_renorm"] = (
        df_emp["q_emp_raw"]
        / df_emp.groupby(["event_ticker", "snapshot_ts"])["q_emp_raw"].transform("sum")
    )
    df_emp = df_emp.dropna(subset=["q_emp_renorm"])
    df_emp["abs_gap_emp"] = np.abs(df_emp["p"] - df_emp["q_emp_renorm"])
    df_emp["abs_gap_lognormal"] = np.abs(df_emp["p"] - df_emp["q"])

    snap_emp = df_emp.groupby(
        ["event_ticker", "snapshot_ts"], as_index=False
    ).agg(
        max_gap_emp=("abs_gap_emp", "max"),
        max_gap_lognormal=("abs_gap_lognormal", "max"),
    )

    emp_median = float(snap_emp["max_gap_emp"].median())
    lognormal_median = float(snap_emp["max_gap_lognormal"].median())
    ratio = emp_median / lognormal_median if lognormal_median > 0 else float("nan")
    passing = ratio < D3_MAX_EMPIRICAL_RATIO

    snap_emp.to_parquet(OUT_DIR / "d3_gap_emp_vs_lognormal.parquet", index=False)

    return {
        "label": "D3 empirical-bootstrap reference",
        "n_snapshots": int(len(snap_emp)),
        "emp_median_gap": emp_median,
        "lognormal_median_gap": lognormal_median,
        "emp_over_lognormal": float(ratio),
        "n_snapshots_dropped_no_bootstrap": int(n_dropped),
        "pass": bool(passing),
    }


# ---------------------------------------------------------------------------
# D4 — Moderate-volume event universe
# ---------------------------------------------------------------------------

def diagnostic_d4(con: duckdb.DuckDBPyConnection) -> dict:
    """Re-run ladder reconstruction for events with n_trades in [100, 500),
    then compute gap statistics. Reuses the lognormal q from the perp fitter
    (which only needs spot/sigma/years, not event-specific).

    Approximation: we compute gaps using the ladder's p values vs. a fresh
    lognormal q evaluated at each bucket using current spot+sigma. Using the
    full perp_implied.parquet isn't possible because it's scoped to the
    high-volume event universe."""
    markets_glob = str(KALSHI_DIR / "markets" / "date=*" / "part.parquet")
    trades_glob = str(KALSHI_DIR / "trades" / "date=*" / "part.parquet")

    # Find moderate-volume events and their B-type tickers.
    con.execute(f"""
        CREATE TEMP TABLE d4_events AS
        WITH parsed AS (
            SELECT
                ticker,
                event_ticker,
                yes_sub_title,
                open_time,
                close_time,
                regexp_extract(yes_sub_title,
                    '\\$([\\d,]+(?:\\.\\d+)?)\\s*to\\s*([\\d,]+(?:\\.\\d+)?)', 1) AS lo_str,
                regexp_extract(yes_sub_title,
                    '\\$([\\d,]+(?:\\.\\d+)?)\\s*to\\s*([\\d,]+(?:\\.\\d+)?)', 2) AS hi_str
            FROM read_parquet('{markets_glob}')
            WHERE event_ticker LIKE 'KXBTC-%'
              AND ticker LIKE '%-B%'
              AND status = 'finalized'
              AND close_time >= TIMESTAMP '2025-09-17'
              AND close_time <= TIMESTAMP '2026-04-23'
        ),
        by_event AS (
            SELECT event_ticker, COUNT(*) AS n_tickers
            FROM parsed
            WHERE lo_str <> '' AND hi_str <> ''
            GROUP BY event_ticker
        ),
        trade_counts AS (
            SELECT p.event_ticker, COUNT(*) AS n_trades
            FROM parsed p
            JOIN read_parquet('{trades_glob}') t ON t.ticker = p.ticker
            GROUP BY p.event_ticker
        ),
        moderate AS (
            SELECT event_ticker
            FROM trade_counts
            WHERE n_trades >= {D4_MIN_TRADES} AND n_trades < {D4_MAX_TRADES}
        )
        SELECT
            p.ticker,
            p.event_ticker,
            p.yes_sub_title,
            p.open_time,
            p.close_time,
            CAST(replace(p.lo_str, ',', '') AS DOUBLE) AS bucket_lower,
            CAST(replace(p.hi_str, ',', '') AS DOUBLE) AS bucket_upper,
            (CAST(replace(p.lo_str, ',', '') AS DOUBLE)
             + CAST(replace(p.hi_str, ',', '') AS DOUBLE)) / 2.0 AS strike_mid
        FROM parsed p
        JOIN moderate m USING (event_ticker)
        WHERE p.lo_str <> '' AND p.hi_str <> ''
    """)

    n_events = con.execute(
        "SELECT COUNT(DISTINCT event_ticker) FROM d4_events"
    ).fetchone()[0]
    if n_events == 0:
        return {
            "label": "D4 moderate-volume universe",
            "n_events": 0,
            "error": "no events in moderate-volume range",
            "pass": False,
        }

    # Reconstruct ladder — same logic as reconstruct_kalshi_ladder.py, condensed.
    con.execute("""
        CREATE TEMP TABLE d4_snaps AS
        SELECT e.event_ticker, e.ticker, e.bucket_lower, e.bucket_upper,
               e.strike_mid, e.open_time, e.close_time, gs AS snapshot_ts
        FROM d4_events e
        CROSS JOIN LATERAL (
            SELECT unnest(generate_series(
                date_trunc('hour', e.open_time)
                    + INTERVAL '15' MINUTE * ceil(date_part('minute', e.open_time) / 15.0),
                e.close_time,
                INTERVAL '15' MINUTE
            )) AS gs
        )
    """)
    con.execute(f"""
        CREATE TEMP TABLE d4_trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM read_parquet('{trades_glob}') t
        JOIN (SELECT DISTINCT ticker FROM d4_events) e USING (ticker)
    """)
    df_raw = con.execute("""
        WITH joined AS (
            SELECT s.event_ticker, s.snapshot_ts, s.ticker, s.bucket_lower,
                   s.bucket_upper, s.strike_mid, s.close_time, t.yes_price
            FROM d4_snaps s
            ASOF LEFT JOIN d4_trades t
              ON s.ticker = t.ticker AND s.snapshot_ts >= t.created_time
        )
        SELECT * FROM joined WHERE yes_price IS NOT NULL
    """).fetchdf()

    # Renormalize per (event, snapshot).
    # Prices in unified tree are already [0, 1]; no /100 scaling.
    df_raw["p_raw"] = df_raw["yes_price"].astype(float)
    grouped_sum = df_raw.groupby(
        ["event_ticker", "snapshot_ts"]
    )["p_raw"].transform("sum")
    df_raw["p"] = df_raw["p_raw"] / grouped_sum
    df_raw = df_raw[grouped_sum > 0]

    # Ladder completeness per snapshot
    df_raw["n_strikes_in_snap"] = df_raw.groupby(
        ["event_ticker", "snapshot_ts"]
    )["strike_mid"].transform("size")
    df_raw["max_strikes_in_event"] = df_raw.groupby("event_ticker")[
        "n_strikes_in_snap"
    ].transform("max")
    df_raw["ladder_completeness"] = (
        df_raw["n_strikes_in_snap"] / df_raw["max_strikes_in_event"]
    )
    df_raw = df_raw[df_raw["ladder_completeness"] >= MIN_LADDER_COMPLETENESS]
    if len(df_raw) == 0:
        return {
            "label": "D4 moderate-volume universe",
            "n_events": int(n_events),
            "n_buckets_after_filter": 0,
            "error": "no snapshots pass completeness filter",
            "pass": False,
        }

    # Attach spot + sigma via OHLCV
    ohlcv = pd.read_parquet(OHLCV_PATH).sort_values("timestamp").reset_index(drop=True)
    ohlcv["timestamp"] = pd.to_datetime(ohlcv["timestamp"], utc=True)
    ohlcv["log_close"] = np.log(ohlcv["close"])
    ohlcv["log_return"] = ohlcv["log_close"].diff()
    LAM = 0.94
    LOOKBACK = 48
    ohlcv["ewma_sigma_annual"] = np.nan
    for i in range(LOOKBACK, len(ohlcv)):
        rets = ohlcv["log_return"].iloc[
            i - LOOKBACK + 1 : i + 1
        ].dropna().to_numpy()
        if len(rets) < LOOKBACK // 2:
            continue
        n = len(rets)
        weights = np.array([(1 - LAM) * (LAM ** (n - 1 - i)) for i in range(n)])
        weights /= weights.sum()
        var_h = float(np.sum(weights * (rets ** 2)))
        ohlcv.loc[i, "ewma_sigma_annual"] = math.sqrt(var_h * HOURS_PER_YEAR)
    ohlcv_clean = ohlcv.dropna(subset=["ewma_sigma_annual"])

    df_raw["snapshot_ts_utc"] = pd.to_datetime(df_raw["snapshot_ts"], utc=True)
    df_raw["close_time_utc"] = pd.to_datetime(df_raw["close_time"], utc=True)
    df_raw = df_raw.sort_values("snapshot_ts_utc").reset_index(drop=True)

    ohlcv_compact = ohlcv_clean[
        ["timestamp", "close", "ewma_sigma_annual"]
    ].rename(columns={"timestamp": "ts_utc", "close": "spot"})
    ohlcv_compact = ohlcv_compact.sort_values("ts_utc").reset_index(drop=True)

    con.register("df_raw", df_raw)
    con.register("ohlcv_df", ohlcv_compact)
    joined = con.execute("""
        SELECT l.*, o.spot, o.ewma_sigma_annual
        FROM df_raw l
        ASOF LEFT JOIN ohlcv_df o ON l.snapshot_ts_utc >= o.ts_utc
    """).fetchdf()
    joined = joined.dropna(subset=["spot", "ewma_sigma_annual"]).reset_index(drop=True)
    hours = (
        joined["close_time_utc"] - joined["snapshot_ts_utc"]
    ).dt.total_seconds() / 3600.0
    joined["years_to_close"] = hours / HOURS_PER_YEAR
    joined = joined[joined["years_to_close"] > 0].reset_index(drop=True)

    sigma_sqrt_T = joined["ewma_sigma_annual"] * np.sqrt(joined["years_to_close"])
    log_spot = np.log(joined["spot"])
    z_upper = (np.log(joined["bucket_upper"]) - log_spot) / sigma_sqrt_T
    z_lower = (np.log(joined["bucket_lower"]) - log_spot) / sigma_sqrt_T
    q_raw = norm_cdf(z_upper.to_numpy()) - norm_cdf(z_lower.to_numpy())
    joined["q_raw"] = q_raw
    joined["q"] = (
        joined["q_raw"]
        / joined.groupby(["event_ticker", "snapshot_ts"])["q_raw"].transform("sum")
    )
    joined["abs_gap"] = np.abs(joined["p"] - joined["q"])

    snap = joined.groupby(["event_ticker", "snapshot_ts"], as_index=False).agg(
        max_abs_gap=("abs_gap", "max"),
    )
    snap["snapshot_ts"] = pd.to_datetime(snap["snapshot_ts"], utc=True)

    # Mean reversion: 1h ahead
    snap = snap.sort_values(["event_ticker", "snapshot_ts"]).reset_index(drop=True)
    target = snap[["event_ticker", "snapshot_ts"]].copy()
    target["snapshot_ts_future"] = target["snapshot_ts"] + pd.Timedelta(hours=1)
    lookup = snap[["event_ticker", "snapshot_ts", "max_abs_gap"]].rename(
        columns={"snapshot_ts": "snapshot_ts_future",
                 "max_abs_gap": "gap_t_plus_1h"}
    )
    merged = target.merge(
        lookup, on=["event_ticker", "snapshot_ts_future"], how="left"
    )
    snap["gap_t_plus_1h"] = merged["gap_t_plus_1h"].to_numpy()
    snap["delta_gap"] = snap["gap_t_plus_1h"] - snap["max_abs_gap"]

    pair = snap.dropna(subset=["delta_gap"])
    if len(pair) >= 30:
        beta, _ = np.polyfit(pair["max_abs_gap"], pair["delta_gap"], 1)
    else:
        beta = float("nan")

    moderate_median = float(snap["max_abs_gap"].median())
    snap.to_parquet(OUT_DIR / "d4_moderate_volume_gaps.parquet", index=False)

    # High-volume median from existing panel for ratio calc
    con2 = duckdb.connect()
    high_median = con2.execute(f"""
        WITH snap AS (
            SELECT event_ticker, snapshot_ts, MAX(ABS(p - q)) AS max_abs_gap
            FROM (
                SELECT l.event_ticker, l.snapshot_ts,
                       l.yes_mid_renorm AS p, q.q_renorm AS q
                FROM read_parquet('{LADDER_PATH}') l
                JOIN read_parquet('{PERP_PATH}') q
                  USING (event_ticker, snapshot_ts, strike_mid)
                WHERE l.ladder_completeness >= {MIN_LADDER_COMPLETENESS}
            )
            GROUP BY event_ticker, snapshot_ts
        )
        SELECT quantile_cont(max_abs_gap, 0.5) FROM snap
    """).fetchone()[0]

    ratio = moderate_median / high_median if high_median > 0 else float("nan")
    passing = ratio > D4_MIN_GAP_RATIO and beta < D4_MAX_REVERSION_BETA

    return {
        "label": "D4 moderate-volume universe",
        "n_events": int(n_events),
        "n_snapshots_after_filter": int(len(snap)),
        "moderate_median_gap": moderate_median,
        "high_median_gap": float(high_median),
        "moderate_over_high_ratio": float(ratio),
        "reversion_beta": float(beta),
        "n_reversion_pairs": int(len(pair)),
        "pass": bool(passing),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    print("[1/5] loading joined panel (ladder + perp implied)...")
    df = load_joined(con)
    print(f"      {len(df):,} bucket rows (completeness ≥ {MIN_LADDER_COMPLETENESS})")

    print("[2/5] D1 — per-bucket-position signed gap...")
    d1 = diagnostic_d1(df)

    print("[3/5] D2 — terminal convergence by event-life decile...")
    events = load_event_meta(con)
    d2 = diagnostic_d2(df, events)

    print("[4/5] D3 — empirical-bootstrap reference (lookback "
          f"{BOOTSTRAP_LOOKBACK_DAYS}d)...")
    ohlcv = pd.read_parquet(OHLCV_PATH)
    d3 = diagnostic_d3(df, ohlcv)

    print("[5/5] D4 — moderate-volume universe "
          f"(n_trades ∈ [{D4_MIN_TRADES}, {D4_MAX_TRADES}))...")
    d4 = diagnostic_d4(con)

    # --- report ---
    lines = [
        "=" * 72,
        "#10 Phase 1 Diagnostic — Summary",
        "=" * 72,
        "",
    ]
    def _fmt(d: dict, indent: int = 2) -> list[str]:
        out = []
        pad = " " * indent
        for k, v in d.items():
            if k == "label":
                continue
            if isinstance(v, dict):
                out.append(f"{pad}{k}:")
                out.extend(_fmt(v, indent + 2))
            elif isinstance(v, float):
                out.append(f"{pad}{k}: {v:.4f}")
            else:
                out.append(f"{pad}{k}: {v}")
        return out

    for d in (d1, d2, d3, d4):
        lines.append(d["label"])
        lines.extend(_fmt(d))
        lines.append("")
    n_pass = sum(int(d.get("pass", False)) for d in (d1, d2, d3, d4))
    lines.append(f"PASSES: {n_pass} / 4")
    lines.append("")
    if n_pass >= 1:
        lines.append("DECISION: at least one diagnostic points to tradeable structure.")
        lines.append("          Proceed to Phase 2 (in-house data pipeline) per §13.")
    else:
        lines.append("DECISION: all four diagnostics negative. Pivot to #4 per §8.")
    lines.append("=" * 72)

    report = "\n".join(lines)
    print("\n" + report)
    (OUT_DIR / "summary.txt").write_text(report)


if __name__ == "__main__":
    main()
