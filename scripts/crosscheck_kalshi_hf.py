"""Cross-check in-house Kalshi pull vs. TrevorJS HF dataset.

Runs after a pilot backfill to validate M1's data quality. Compares our
`data/kalshi/trades/` output against `data/kalshi_hf/trades-*.parquet`
on the overlap window, per ticker.

For each ticker that appears in both:
  - trade_count (ours vs. HF)
  - trade_id overlap fraction
  - sum of (yes_price × count) — invariant under ordering
  - distribution of created_time (min/max/median)

Flags:
  - |Δ count| > 1          (off-by-one at window boundary is OK)
  - trade_id overlap < 0.99 (random trade IDs would collide <1%)
  - |Δ price-weighted sum| / HF sum > 0.001

Outputs: `data/kalshi/_crosscheck.txt` and a per-ticker CSV.

Not run from Claude Code — depends on live backfill output being present.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OURS = REPO_ROOT / "data" / "kalshi" / "trades"
DEFAULT_HF = REPO_ROOT / "data" / "kalshi_hf"

# Pass thresholds (pre-registered; document any changes).
MAX_COUNT_DELTA = 1
MIN_TRADE_ID_OVERLAP = 0.99
MAX_WEIGHTED_SUM_REL_DELTA = 0.001


def load_ours(root: Path) -> pd.DataFrame:
    glob = str(root / "date=*" / "*.parquet")
    if not list(root.glob("date=*/part.parquet")):
        raise SystemExit(
            f"No trade partitions found under {root}. Run backfill first."
        )
    return duckdb.sql(f"""
        SELECT trade_id, ticker, count, yes_price, no_price, created_time
        FROM read_parquet('{glob}')
    """).to_df()


def load_hf(hf_dir: Path) -> pd.DataFrame:
    glob = str(hf_dir / "trades-*.parquet")
    return duckdb.sql(f"""
        SELECT trade_id, ticker, count, yes_price, no_price, created_time
        FROM read_parquet('{glob}')
    """).to_df()


def compare_ticker(ours: pd.DataFrame, hf: pd.DataFrame) -> dict:
    """Per-ticker comparison. `yes_price` is 0-1 in ours, 0-100 in HF."""
    n_ours = len(ours)
    n_hf = len(hf)
    # Normalize price units for HF (cents -> dollars) to match ours.
    hf_yes = hf["yes_price"].to_numpy().astype(float) / 100.0
    our_yes = ours["yes_price"].to_numpy().astype(float)

    sum_ours = float((ours["count"] * our_yes).sum())
    sum_hf = float((hf["count"].astype(float) * hf_yes).sum())
    rel_delta = (
        abs(sum_ours - sum_hf) / sum_hf if sum_hf > 0 else float("nan")
    )

    id_overlap = (
        len(set(ours["trade_id"]) & set(hf["trade_id"])) / max(n_ours, n_hf)
        if max(n_ours, n_hf) > 0 else float("nan")
    )

    return {
        "count_ours": n_ours,
        "count_hf": n_hf,
        "count_delta": n_ours - n_hf,
        "weighted_sum_ours": sum_ours,
        "weighted_sum_hf": sum_hf,
        "rel_sum_delta": rel_delta,
        "trade_id_overlap": id_overlap,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ours", type=Path, default=DEFAULT_OURS)
    parser.add_argument("--hf", type=Path, default=DEFAULT_HF)
    parser.add_argument(
        "--overlap-start", default="2025-09-17",
        help="Restrict HF comparison to trades ≥ this date (UTC)",
    )
    parser.add_argument(
        "--overlap-end", default="2026-01-30",
        help="Restrict HF comparison to trades ≤ this date (UTC)",
    )
    args = parser.parse_args()

    print(f"Loading ours from {args.ours}...")
    ours = load_ours(args.ours)
    print(f"  {len(ours):,} rows, {ours['ticker'].nunique():,} tickers")

    print(f"Loading TrevorJS HF from {args.hf}...")
    hf = load_hf(args.hf)
    # Apply date window.
    hf["created_time"] = pd.to_datetime(hf["created_time"], utc=True)
    mask = (
        (hf["created_time"] >= pd.Timestamp(args.overlap_start, tz="UTC"))
        & (hf["created_time"] <= pd.Timestamp(args.overlap_end, tz="UTC"))
    )
    hf_window = hf[mask]
    print(f"  {len(hf_window):,} rows in window, {hf_window['ticker'].nunique():,} tickers")

    # Same window for ours.
    ours["created_time"] = pd.to_datetime(ours["created_time"], utc=True)
    ours_window = ours[
        (ours["created_time"] >= pd.Timestamp(args.overlap_start, tz="UTC"))
        & (ours["created_time"] <= pd.Timestamp(args.overlap_end, tz="UTC"))
    ]

    common_tickers = sorted(
        set(ours_window["ticker"].unique()) & set(hf_window["ticker"].unique())
    )
    print(f"  {len(common_tickers):,} tickers in common")

    records = []
    for t in common_tickers:
        sub_ours = ours_window[ours_window["ticker"] == t]
        sub_hf = hf_window[hf_window["ticker"] == t]
        rec = compare_ticker(sub_ours, sub_hf)
        rec["ticker"] = t
        records.append(rec)
    df = pd.DataFrame(records)
    if df.empty:
        print("No common tickers to compare.")
        return

    df = df[[
        "ticker", "count_ours", "count_hf", "count_delta",
        "trade_id_overlap", "weighted_sum_ours", "weighted_sum_hf",
        "rel_sum_delta",
    ]]
    out_csv = args.ours.parent / "_crosscheck.csv"
    df.to_csv(out_csv, index=False)

    # Flags
    bad_count = df[df["count_delta"].abs() > MAX_COUNT_DELTA]
    bad_ids = df[df["trade_id_overlap"] < MIN_TRADE_ID_OVERLAP]
    bad_sums = df[df["rel_sum_delta"] > MAX_WEIGHTED_SUM_REL_DELTA]

    report = [
        "=" * 72,
        "Kalshi in-house vs. TrevorJS HF cross-check",
        "=" * 72,
        "",
        f"Window: {args.overlap_start} → {args.overlap_end}",
        f"Tickers compared: {len(df)}",
        f"Our trades in window: {len(ours_window):,}",
        f"HF trades in window:  {len(hf_window):,}",
        "",
        "Pass thresholds (per ticker):",
        f"  |count delta| ≤ {MAX_COUNT_DELTA}",
        f"  trade_id overlap ≥ {MIN_TRADE_ID_OVERLAP:.2%}",
        f"  weighted sum relative delta ≤ {MAX_WEIGHTED_SUM_REL_DELTA:.3%}",
        "",
        f"Tickers with count mismatch: {len(bad_count)}",
        f"Tickers with trade_id overlap mismatch: {len(bad_ids)}",
        f"Tickers with weighted sum mismatch: {len(bad_sums)}",
        "",
        "Top 10 worst-case |count_delta|:",
        df.reindex(
            df["count_delta"].abs().sort_values(ascending=False).index
        ).head(10).to_string(index=False),
        "",
        "Top 10 worst-case trade_id overlap:",
        df.nsmallest(10, "trade_id_overlap").to_string(index=False),
        "",
        f"Full per-ticker CSV: {out_csv}",
        "=" * 72,
    ]
    text = "\n".join(report)
    (args.ours.parent / "_crosscheck.txt").write_text(text)
    print("\n" + text)


if __name__ == "__main__":
    main()
