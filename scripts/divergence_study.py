"""Compare Kalshi-implied and perp-implied distributions; test the Week-1 thesis.

Week-1 spike for strategy #10. Hyperparameters locked per deep-dive §5.0.

Pipeline:
  1. Join ladder (p_i) with perp-implied (q_i) on (event_ticker, snapshot_ts,
     strike_mid). Apply min-ladder-completeness filter.
  2. Compute per-snapshot divergence metrics:
       - max_abs_gap  (primary)        = max_i |p_i - q_i|
       - kl_divergence (secondary)     = sum p_i log(p_i / q_i)
  3. Compute 1h-ahead mean-reversion: Δgap = gap(t+1h) - gap(t); regress on gap(t).
  4. Split train (2025-09-17 → 2026-01-31) vs. test (2026-02-01 → 2026-04-22).
  5. Null-shuffle benchmark on test: permute event↔snapshot_ts pairing within
     test fold and re-run steps 2+3. Report real vs. null passing rates.

Pass criteria (pre-registered, §5.0):
  (a) Test fold: ≥30% of tuples have max_abs_gap > 0.03 (300bp).
  (b) Mean-reversion half-life < 30% of remaining event life.
  (c) Null-shuffle passing rate on criterion (a) < 10% (so real ≥ 3× null).

All pre-registered thresholds are module-level constants below.
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# --- Pre-registered hyperparameters (see §5.0) ---------------------------------
# NOTE: Phase 3 (2026-04-23) extends TEST_END from 2026-01-30 to 2026-04-23.
# Train boundary stays locked at 2026-01-10 (per the original §5.0 pre-reg,
# "If/when more data arrives, re-run with the wider window without refitting
# train"). With the TrevorJS migration + /historical/* pulls, the test fold
# now covers ~3 additional months of out-of-sample data — ~5× expansion.
TRAIN_START = "2025-09-17"
TRAIN_END = "2026-01-10"
TEST_START = "2026-01-10"
TEST_END = "2026-04-23"

MIN_LADDER_COMPLETENESS = 0.75     # added after train-fold ladder inspection
MAX_GAP_THRESHOLD = 0.03           # 300bp; primary decision threshold
MEAN_REVERSION_HORIZON_HOURS = 1
SNAPSHOT_CADENCE_MIN = 15

# Pass criteria
MIN_PASSING_FRACTION = 0.30        # ≥30% of tuples > τ
MAX_NULL_PASSING_FRACTION = 0.10   # null < 10% (real must be ≥ 3× null in spirit)
MAX_HALF_LIFE_FRAC_OF_REMAINING_EVENT_LIFE = 0.30

NULL_SHUFFLE_SEED = 20260422       # deterministic null benchmark
# --------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LADDER_PATH = REPO_ROOT / "data" / "vol_surface" / "kalshi_ladder.parquet"
PERP_PATH = REPO_ROOT / "data" / "vol_surface" / "perp_implied.parquet"
OUT_DIR = REPO_ROOT / "data" / "vol_surface"


def join_and_filter(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Join ladder (p) with perp (q), apply completeness filter."""
    df = con.execute(f"""
        WITH joined AS (
            SELECT
                l.event_ticker,
                l.snapshot_ts,
                l.strike_mid,
                l.bucket_lower,
                l.bucket_upper,
                l.yes_mid_renorm AS p,
                q.q_renorm AS q,
                q.q_raw,
                l.ladder_completeness,
                l.n_strikes_in_snap,
                l.max_strikes_in_event,
                q.spot,
                q.ewma_sigma_annual,
                q.years_to_close
            FROM read_parquet('{LADDER_PATH}') l
            JOIN read_parquet('{PERP_PATH}') q
              USING (event_ticker, snapshot_ts, strike_mid)
            WHERE l.ladder_completeness >= {MIN_LADDER_COMPLETENESS}
        )
        SELECT * FROM joined
        ORDER BY event_ticker, snapshot_ts, strike_mid
    """).fetchdf()
    return df


def compute_q_for_row(
    bucket_lower: np.ndarray,
    bucket_upper: np.ndarray,
    spot: np.ndarray,
    sigma: np.ndarray,
    years: np.ndarray,
) -> np.ndarray:
    """Vectorized lognormal bucket probability — matches fit_perp_implied_dist."""
    sigma_sqrt_T = sigma * np.sqrt(years)
    log_spot = np.log(spot)
    z_upper = (np.log(bucket_upper) - log_spot) / sigma_sqrt_T
    z_lower = (np.log(bucket_lower) - log_spot) / sigma_sqrt_T
    return norm_cdf_arr(z_upper) - norm_cdf_arr(z_lower)


def norm_cdf_arr(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def null_shuffle_buckets(df_joined: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Proper null: keep each (event, snapshot, bucket)'s p and bucket grid,
    but replace (spot, sigma, years_to_close) with those drawn from a random
    *different* (event, snapshot) pair in the same fold. Recompute q.

    If gaps persist under this null, the divergence is a structural lognormal-
    vs-Kalshi model mismatch, not event-specific signal.
    If gaps collapse, the real-data divergence carries event-specific info."""
    rng = np.random.default_rng(seed)
    # Unique (event, snapshot) pairs in the fold with their perp-side params.
    pairs = df_joined[
        ["event_ticker", "snapshot_ts", "spot", "ewma_sigma_annual",
         "years_to_close"]
    ].drop_duplicates(subset=["event_ticker", "snapshot_ts"]).reset_index(drop=True)
    # Derangement-ish: for each pair, sample a random row index for the null.
    # (Not a strict derangement; with ~1000+ pairs the self-assignment rate is
    # <0.1% and doesn't affect the passing-fraction estimate.)
    src_idx = np.arange(len(pairs))
    dst_idx = rng.permutation(len(pairs))
    shuffle_map = pairs.iloc[src_idx][
        ["event_ticker", "snapshot_ts"]
    ].reset_index(drop=True)
    shuffle_map["null_spot"] = pairs["spot"].iloc[dst_idx].to_numpy()
    shuffle_map["null_sigma"] = pairs["ewma_sigma_annual"].iloc[dst_idx].to_numpy()
    shuffle_map["null_years"] = pairs["years_to_close"].iloc[dst_idx].to_numpy()
    merged = df_joined.merge(
        shuffle_map, on=["event_ticker", "snapshot_ts"], how="left"
    )
    q_null_raw = compute_q_for_row(
        merged["bucket_lower"].to_numpy(),
        merged["bucket_upper"].to_numpy(),
        merged["null_spot"].to_numpy(),
        merged["null_sigma"].to_numpy(),
        merged["null_years"].to_numpy(),
    )
    merged["q_null_raw"] = q_null_raw
    merged["q_null_renorm"] = (
        merged["q_null_raw"]
        / merged.groupby(["event_ticker", "snapshot_ts"])["q_null_raw"]
               .transform("sum")
    )
    merged["q"] = merged["q_null_renorm"]
    return merged


def snapshot_metrics(df_joined: pd.DataFrame) -> pd.DataFrame:
    """Collapse bucket-level rows to one row per (event, snapshot) with
    divergence metrics + event-life context."""
    # KL: handle p=0 by dropping those terms (0*log(0/q) = 0).
    eps = 1e-12
    df_joined = df_joined.copy()
    df_joined["abs_gap"] = np.abs(df_joined["p"] - df_joined["q"])
    df_joined["kl_term"] = np.where(
        df_joined["p"] > eps,
        df_joined["p"] * np.log((df_joined["p"] + eps) / (df_joined["q"] + eps)),
        0.0,
    )
    agg = df_joined.groupby(
        ["event_ticker", "snapshot_ts"], as_index=False
    ).agg(
        max_abs_gap=("abs_gap", "max"),
        kl_divergence=("kl_term", "sum"),
        n_buckets=("abs_gap", "size"),
        spot=("spot", "first"),
        ewma_sigma_annual=("ewma_sigma_annual", "first"),
        years_to_close=("years_to_close", "first"),
    )
    agg["snapshot_ts"] = pd.to_datetime(agg["snapshot_ts"], utc=True)
    return agg


def add_mean_reversion(snap_df: pd.DataFrame) -> pd.DataFrame:
    """Attach gap(t + 1h) to each row for the mean-reversion regression.

    Joins by (event_ticker, snapshot_ts) as strings to avoid tz-aware vs
    tz-naive dtype mismatches during reindex."""
    snap_df = snap_df.sort_values(
        ["event_ticker", "snapshot_ts"]
    ).reset_index(drop=True)
    lookup = snap_df[["event_ticker", "snapshot_ts", "max_abs_gap"]].rename(
        columns={
            "snapshot_ts": "snapshot_ts_future",
            "max_abs_gap": "gap_t_plus_1h",
        }
    )
    target = snap_df[["event_ticker", "snapshot_ts"]].copy()
    target["snapshot_ts_future"] = target["snapshot_ts"] + pd.Timedelta(
        hours=MEAN_REVERSION_HORIZON_HOURS
    )
    merged = target.merge(
        lookup, on=["event_ticker", "snapshot_ts_future"], how="left"
    )
    snap_df["gap_t_plus_1h"] = merged["gap_t_plus_1h"].to_numpy()
    snap_df["delta_gap"] = snap_df["gap_t_plus_1h"] - snap_df["max_abs_gap"]
    return snap_df


def regress_mean_reversion(snap_df: pd.DataFrame) -> dict:
    """OLS: delta_gap = alpha + beta * gap_t. Report beta, intercept, and
    half-life if beta in (-1, 0).

    Half-life converts discrete-step AR(1) coefficient phi = 1 + beta into
    continuous half-life = ln(0.5) / ln(phi) * MEAN_REVERSION_HORIZON_HOURS."""
    pair = snap_df.dropna(subset=["delta_gap", "max_abs_gap"])
    if len(pair) < 30:
        return {"n": len(pair), "beta": float("nan"),
                "alpha": float("nan"), "half_life_hours": float("nan")}
    x = pair["max_abs_gap"].to_numpy()
    y = pair["delta_gap"].to_numpy()
    beta, alpha = np.polyfit(x, y, 1)
    phi = 1.0 + beta
    half_life = (
        math.log(0.5) / math.log(phi) * MEAN_REVERSION_HORIZON_HOURS
        if 0 < phi < 1 else float("nan")
    )
    return {
        "n": len(pair),
        "beta": float(beta),
        "alpha": float(alpha),
        "half_life_hours": float(half_life),
    }


def summarize(snap_df: pd.DataFrame, label: str) -> dict:
    """Compute pass-criteria stats for a fold."""
    n = len(snap_df)
    if n == 0:
        return {"label": label, "n": 0,
                "passing_fraction": float("nan"),
                "median_gap": float("nan"),
                "p90_gap": float("nan"),
                "mean_kl": float("nan"),
                "reversion_beta": float("nan"),
                "reversion_half_life_hours": float("nan"),
                "reversion_n_pairs": 0}
    passing = (snap_df["max_abs_gap"] > MAX_GAP_THRESHOLD).sum()
    passing_fraction = passing / n
    regr = regress_mean_reversion(snap_df)
    stats = {
        "label": label,
        "n": n,
        "passing_fraction": passing_fraction,
        "median_gap": float(snap_df["max_abs_gap"].median()),
        "p90_gap": float(snap_df["max_abs_gap"].quantile(0.90)),
        "mean_kl": float(snap_df["kl_divergence"].mean()),
        "reversion_beta": regr["beta"],
        "reversion_half_life_hours": regr["half_life_hours"],
        "reversion_n_pairs": regr["n"],
    }
    return stats


def main() -> None:
    con = duckdb.connect()
    print("[1/5] joining ladder and perp-implied, applying completeness filter...")
    df = join_and_filter(con)
    print(f"      {len(df):,} bucket rows after completeness ≥ "
          f"{MIN_LADDER_COMPLETENESS:.2f}")

    print("[2/5] computing per-snapshot divergence metrics...")
    snap = snapshot_metrics(df)
    snap = add_mean_reversion(snap)
    print(f"      {len(snap):,} unique (event, snapshot) rows with divergence")

    # Date split
    train = snap[
        (snap["snapshot_ts"] >= pd.Timestamp(TRAIN_START, tz="UTC"))
        & (snap["snapshot_ts"] < pd.Timestamp(TEST_START, tz="UTC"))
    ].copy()
    test = snap[
        (snap["snapshot_ts"] >= pd.Timestamp(TEST_START, tz="UTC"))
        & (snap["snapshot_ts"] <= pd.Timestamp(TEST_END, tz="UTC"))
    ].copy()
    print(f"      train: {len(train):,} snapshots, "
          f"test: {len(test):,} snapshots")

    print("[3/5] summarizing train fold (exploration only)...")
    train_stats = summarize(train, "train")

    print("[4/5] summarizing test fold (seen-once, pre-registered)...")
    test_stats = summarize(test, "test")

    print("[5/5] null-shuffle benchmark on test fold...")
    # Null is done at the *bucket* level (re-deriving q from shuffled
    # spot/sigma/years), then collapsed to per-snapshot metrics.
    df_test_buckets = df[
        pd.to_datetime(df["snapshot_ts"], utc=True) >= pd.Timestamp(TEST_START, tz="UTC")
    ].copy()
    df_test_null = null_shuffle_buckets(df_test_buckets, NULL_SHUFFLE_SEED)
    test_null = snapshot_metrics(df_test_null)
    test_null = add_mean_reversion(test_null)
    null_stats = summarize(test_null, "test_null")

    # Write the per-snapshot panel for downstream plotting.
    snap.to_parquet(OUT_DIR / "divergence_panel.parquet", index=False)

    # Assemble the pre-registered pass/fail decision.
    median_remaining_life_hours = float(
        test["years_to_close"].median() * 24 * 365.25
    )
    pass_a = test_stats["passing_fraction"] >= MIN_PASSING_FRACTION
    pass_b_possible = not math.isnan(test_stats["reversion_half_life_hours"])
    if pass_b_possible:
        pass_b = (
            test_stats["reversion_half_life_hours"]
            < MAX_HALF_LIFE_FRAC_OF_REMAINING_EVENT_LIFE
            * median_remaining_life_hours
        )
    else:
        pass_b = False
    pass_c = null_stats["passing_fraction"] < MAX_NULL_PASSING_FRACTION
    overall = pass_a and pass_b and pass_c

    # Secondary, non-decision-gating: gap magnitude ratio real vs. null.
    # Smaller ratio = more event-specific alignment.
    gap_ratio = (
        test_stats["median_gap"] / null_stats["median_gap"]
        if null_stats["median_gap"] > 0 else float("nan")
    )

    # Report
    rows = [train_stats, test_stats, null_stats]
    report = pd.DataFrame(rows).set_index("label")
    print("\n" + "=" * 70)
    print("DIVERGENCE STUDY — Week-1 Spike Results")
    print("=" * 70)
    print(report.to_string(float_format=lambda v: f"{v:.4f}"))
    print()
    print(f"Median remaining event life (test): "
          f"{median_remaining_life_hours:.2f}h")
    print()
    print("Pre-registered pass criteria:")
    print(f"  (a) test passing fraction ≥ {MIN_PASSING_FRACTION:.2f}: "
          f"{'PASS' if pass_a else 'FAIL'} "
          f"({test_stats['passing_fraction']:.4f})")
    print(f"  (b) reversion half-life < "
          f"{MAX_HALF_LIFE_FRAC_OF_REMAINING_EVENT_LIFE:.2f} × "
          f"{median_remaining_life_hours:.2f}h = "
          f"{MAX_HALF_LIFE_FRAC_OF_REMAINING_EVENT_LIFE * median_remaining_life_hours:.2f}h: "
          f"{'PASS' if pass_b else 'FAIL'} "
          f"({test_stats['reversion_half_life_hours']:.2f}h)")
    print(f"  (c) null passing fraction < {MAX_NULL_PASSING_FRACTION:.2f}: "
          f"{'PASS' if pass_c else 'FAIL'} "
          f"({null_stats['passing_fraction']:.4f})")
    print()
    print()
    print("Secondary (non-decision-gating):")
    print(f"  real / null median-gap ratio: {gap_ratio:.3f} "
          f"(lower = more event-specific alignment)")
    print()
    verdict = (
        "PASS — proceed to §7 prototype"
        if overall
        else "FAIL — see findings for whether pivot or reformulate"
    )
    print(f"OVERALL: {verdict}")
    print("=" * 70)

    # Persist the decision to disk for auditability.
    (OUT_DIR / "week1_decision.txt").write_text(
        report.to_string(float_format=lambda v: f"{v:.4f}")
        + f"\n\nmedian_remaining_event_life_hours: {median_remaining_life_hours:.2f}\n"
        + f"pass_a (passing_frac ≥ {MIN_PASSING_FRACTION}): {pass_a}\n"
        + f"pass_b (half_life < frac × life): {pass_b}\n"
        + f"pass_c (null_frac < {MAX_NULL_PASSING_FRACTION}): {pass_c}\n"
        + f"overall: {'PASS' if overall else 'FAIL'}\n"
    )


if __name__ == "__main__":
    main()
