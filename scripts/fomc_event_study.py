"""Event study for strategy #4 (Kalshi × crypto narrative spread).

Phase 1 (2026-04-22): hourly granularity; failed all four pre-registered
criteria. Verdict was data-granularity-limited, not thesis-falsifying —
Hyperliquid 1h couldn't resolve the 10–60 min transmission lag the
thesis hypothesized.

Phase 3 (2026-04-23): 15-minute granularity on Coinbase 1m candles.
- Kalshi: unified tree (data/kalshi/), prices already [0, 1].
- Crypto: Coinbase BTC-USD / ETH-USD 1m. Hyperliquid can't provide
  historical 1m (3-day retention); Coinbase's global BTC price tracks
  Hyperliquid's perp at >0.99 correlation on sub-hour bars.

Pre-registration for Phase 3 (refinements over Phase 1 §12 re-locked
before running, not after seeing data):
  - SNAPSHOT_CADENCE_MINUTES = 15 (finer than Phase 1's 1h)
  - LAG_MINUTES = 15 (matches cadence; sub-hour per thesis §1)
  - Event split unchanged: train = FED-25SEP/OCT/DEC, test = KXFED-26JAN
  - Pass criteria unchanged: |t| > 3, R² > 0.002, sign negative,
    null/real t-stat ratio < 1/3
  - Source: data/kalshi/ unified tree + data/coinbase/{BTC,ETH}-USD/1m.parquet
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# --- Pre-registered hyperparameters (§12 + Phase 3 refinements) ---------------
TRAIN_EVENTS = ("FED-25SEP", "FED-25OCT", "FED-25DEC")
TEST_EVENTS = ("KXFED-26JAN",)
COINS = ("BTC-USD", "ETH-USD")

PRE_MEETING_DAYS = 30
SNAPSHOT_CADENCE_MINUTES = 15       # Phase 3: finer than original 1h
LAG_MINUTES = 15                    # BTC return over [t, t+15m] vs. ΔP at [t-15m, t]
MIN_LADDER_COMPLETENESS = 0.75

# Pass criteria (same as Phase 1)
MIN_ABS_T_STAT = 3.0
MIN_R2 = 0.002
EXPECTED_BETA_SIGN = -1.0           # dovish (rate falling) -> BTC up
MAX_NULL_T_STAT_RATIO = 1.0 / 3.0

NULL_SHUFFLE_SEED = 20260422
# --------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
KALSHI_DIR = REPO_ROOT / "data" / "kalshi"
COINBASE_DIR = REPO_ROOT / "data" / "coinbase"
OUT_DIR = REPO_ROOT / "data" / "fomc"

STRIKE_RE = re.compile(r"Above\s+(\d+(?:\.\d+)?)\s*%")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    markets_glob = str(KALSHI_DIR / "markets" / "date=*" / "part.parquet")
    trades_glob = str(KALSHI_DIR / "trades" / "date=*" / "part.parquet")
    all_events = TRAIN_EVENTS + TEST_EVENTS
    events_sql_list = ", ".join(f"'{e}'" for e in all_events)

    print(f"[1/6] loading FED rate-threshold contracts for events: "
          f"{all_events}")
    # Note: we don't filter on status here. The HF snapshot froze FED-25DEC
    # and KXFED-26JAN at status='active' (snapshotted mid-event); trades are
    # present through close regardless. Filtering to 'finalized' would drop
    # half the events. Another reason the in-house data pipeline matters.
    con.execute(f"""
        CREATE TEMP TABLE fed_markets AS
        SELECT
            ticker,
            event_ticker,
            yes_sub_title,
            open_time,
            close_time,
            status
        FROM read_parquet('{markets_glob}')
        WHERE event_ticker IN ({events_sql_list})
          AND yes_sub_title LIKE 'Above %'
    """)
    n = con.execute("SELECT COUNT(*) FROM fed_markets").fetchone()[0]
    print(f"      {n} rate-threshold contracts across {len(all_events)} events")

    print("[2/6] parsing strikes from yes_sub_title...")
    rows = con.execute(
        "SELECT ticker, event_ticker, yes_sub_title, open_time, close_time "
        "FROM fed_markets"
    ).fetchdf()
    rows["strike_pct"] = rows["yes_sub_title"].apply(
        lambda s: float(STRIKE_RE.search(s).group(1))
        if STRIKE_RE.search(s) else None
    )
    rows = rows.dropna(subset=["strike_pct"]).reset_index(drop=True)
    print(f"      {len(rows)} contracts parsed; strike range "
          f"{rows['strike_pct'].min():.2f}% – {rows['strike_pct'].max():.2f}%")
    con.register("fed_markets_parsed", rows)

    print(f"[3/6] generating {SNAPSHOT_CADENCE_MINUTES}-min snapshot grid and "
          f"ASOF-joining trades (last {PRE_MEETING_DAYS}d per event)...")
    # Snapshots aligned to clean 15-min boundaries so Coinbase 1m aggregation
    # is unambiguous.
    con.execute(f"""
        CREATE TEMP TABLE snapshots AS
        SELECT
            f.event_ticker,
            f.ticker,
            f.strike_pct,
            f.close_time,
            gs AS snapshot_ts
        FROM fed_markets_parsed f
        CROSS JOIN LATERAL (
            SELECT unnest(generate_series(
                date_trunc('hour', f.close_time - INTERVAL '{PRE_MEETING_DAYS}' DAY),
                date_trunc('hour', f.close_time),
                INTERVAL '{SNAPSHOT_CADENCE_MINUTES}' MINUTE
            )) AS gs
        )
    """)
    con.execute(f"""
        CREATE TEMP TABLE fed_trades AS
        SELECT t.ticker, t.yes_price, t.created_time
        FROM read_parquet('{trades_glob}') t
        JOIN (SELECT DISTINCT ticker FROM fed_markets_parsed) e USING (ticker)
    """)
    con.execute("""
        CREATE TEMP TABLE ladder_raw AS
        SELECT
            s.event_ticker,
            s.snapshot_ts,
            s.ticker,
            s.strike_pct,
            s.close_time,
            t.yes_price
        FROM snapshots s
        ASOF LEFT JOIN fed_trades t
          ON s.ticker = t.ticker AND s.snapshot_ts >= t.created_time
        WHERE t.yes_price IS NOT NULL
    """)
    n_rows = con.execute("SELECT COUNT(*) FROM ladder_raw").fetchone()[0]
    print(f"      {n_rows:,} (event, ticker, snapshot_ts) rows with prior trades")

    print("[4/6] reconstructing implied expected rate per snapshot...")
    df = con.execute("""
        SELECT event_ticker, snapshot_ts, strike_pct,
               yes_price AS p_above,
               close_time
        FROM ladder_raw
        ORDER BY event_ticker, snapshot_ts, strike_pct
    """).fetchdf()

    # For each (event, snapshot), build bucket probabilities from the
    # decreasing-in-strike "Above X%" prices, then compute weighted expected
    # rate = Σ bucket_prob * bucket_midpoint.
    implied_rates = []
    snap_keys = df.groupby(["event_ticker", "snapshot_ts"]).groups
    max_strikes_per_event = df.groupby("event_ticker")[
        "strike_pct"
    ].nunique().to_dict()

    for (event, ts), idx in snap_keys.items():
        sub = df.loc[idx].sort_values("strike_pct")
        strikes = sub["strike_pct"].to_numpy()
        p_above = np.clip(sub["p_above"].to_numpy(), 0.0, 1.0)

        # Ensure monotonic decreasing (buckets must have nonneg mass).
        # If the input has any noise, cap violations at the neighbor.
        p_above = np.minimum.accumulate(p_above)

        # Bucket midpoints: step below lowest strike = strike[0] - step/2,
        # step above highest strike = strike[-1] + step/2, between strikes
        # = (strike[i] + strike[i+1]) / 2.
        if len(strikes) < 2:
            implied_rates.append({
                "event_ticker": event, "snapshot_ts": ts,
                "implied_rate": float("nan"),
                "n_strikes_in_snap": len(strikes),
                "max_strikes_in_event": max_strikes_per_event.get(event, 0),
                "close_time": sub["close_time"].iloc[0],
            })
            continue

        step = np.median(np.diff(strikes))
        mid_below = strikes[0] - step / 2
        mid_above = strikes[-1] + step / 2
        between_mids = (strikes[:-1] + strikes[1:]) / 2

        # Bucket probabilities:
        # P(rate <= strike[0]) = 1 - p_above[0]
        # P(strike[i] < rate <= strike[i+1]) = p_above[i] - p_above[i+1]
        # P(rate > strike[-1]) = p_above[-1]
        p_below = 1.0 - p_above[0]
        p_between = p_above[:-1] - p_above[1:]
        p_top = p_above[-1]
        probs = np.concatenate([[p_below], p_between, [p_top]])
        mids = np.concatenate([[mid_below], between_mids, [mid_above]])
        total = probs.sum()
        if total <= 0:
            implied_rates.append({
                "event_ticker": event, "snapshot_ts": ts,
                "implied_rate": float("nan"),
                "n_strikes_in_snap": len(strikes),
                "max_strikes_in_event": max_strikes_per_event.get(event, 0),
                "close_time": sub["close_time"].iloc[0],
            })
            continue
        probs /= total
        implied_rate = float(np.sum(probs * mids))
        implied_rates.append({
            "event_ticker": event,
            "snapshot_ts": ts,
            "implied_rate": implied_rate,
            "n_strikes_in_snap": len(strikes),
            "max_strikes_in_event": max_strikes_per_event.get(event, 0),
            "close_time": sub["close_time"].iloc[0],
        })

    rate_df = pd.DataFrame(implied_rates).dropna(subset=["implied_rate"])
    rate_df["ladder_completeness"] = (
        rate_df["n_strikes_in_snap"] / rate_df["max_strikes_in_event"]
    )
    rate_df = rate_df[rate_df["ladder_completeness"] >= MIN_LADDER_COMPLETENESS]
    rate_df["snapshot_ts"] = pd.to_datetime(rate_df["snapshot_ts"], utc=True)
    rate_df["close_time"] = pd.to_datetime(rate_df["close_time"], utc=True)
    rate_df = rate_df.sort_values(
        ["event_ticker", "snapshot_ts"]
    ).reset_index(drop=True)
    print(f"      {len(rate_df):,} snapshots after completeness "
          f"≥ {MIN_LADDER_COMPLETENESS}")

    # Compute hourly Δ(implied_rate) per event.
    rate_df["delta_implied_rate"] = rate_df.groupby("event_ticker")[
        "implied_rate"
    ].diff()
    rate_df = rate_df.dropna(subset=["delta_implied_rate"]).reset_index(drop=True)
    print(f"      {len(rate_df):,} hourly Δ-rate observations")

    print(f"[5/6] joining BTC/ETH {LAG_MINUTES}m returns from Coinbase 1m...")
    # Coinbase 1m candles → resample to the snapshot cadence (15 min by
    # default), then shift(-1) on the resampled close for the forward return
    # over [t, t+LAG_MINUTES]. Anchor to clean 15-min boundaries.
    resample_rule = f"{SNAPSHOT_CADENCE_MINUTES}min"
    coin_returns: dict[str, pd.DataFrame] = {}
    for coin in COINS:
        path = COINBASE_DIR / coin / "1m.parquet"
        if not path.exists():
            print(f"      WARNING: {path} missing — skipping {coin}")
            continue
        ohlcv = pd.read_parquet(path)
        ohlcv["timestamp"] = pd.to_datetime(ohlcv["timestamp"], utc=True)
        ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)
        # Resample 1m close to 15m on the left edge (label='left') so the
        # timestamp aligns with the snapshot boundary (09:00 bar = close at
        # 09:15, i.e. the price at end of the 09:00-09:15 window).
        resampled = ohlcv.set_index("timestamp")["close"].resample(
            resample_rule, label="left", closed="left"
        ).last().rename(f"close_{coin}").reset_index()
        resampled["timestamp"] = pd.to_datetime(
            resampled["timestamp"], utc=True
        )
        ret_col = f"ret_{LAG_MINUTES}m_{coin}"
        # shift(-1) on the resampled series: return over the NEXT bar's
        # [t, t+LAG_MINUTES] window vs. the current close.
        resampled[ret_col] = (
            resampled[f"close_{coin}"].shift(-1) / resampled[f"close_{coin}"]
            - 1.0
        )
        coin_returns[coin] = resampled[["timestamp", ret_col]].rename(
            columns={"timestamp": "snapshot_ts"}
        )

    panel = rate_df.copy()
    for coin, cr in coin_returns.items():
        panel = panel.merge(cr, on="snapshot_ts", how="left")

    panel.to_parquet(OUT_DIR / "event_study_panel.parquet", index=False)

    def _regress(
        sub: pd.DataFrame, y_col: str, label: str
    ) -> dict:
        sub = sub.dropna(subset=["delta_implied_rate", y_col])
        if len(sub) < 30:
            return {
                "label": label, "n": len(sub),
                "beta": float("nan"), "alpha": float("nan"),
                "t_stat": float("nan"), "r2": float("nan"),
            }
        x = sub["delta_implied_rate"].to_numpy()
        y = sub[y_col].to_numpy()
        beta, alpha = np.polyfit(x, y, 1)
        y_hat = alpha + beta * x
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        residual_std = float(np.sqrt(ss_res / max(len(x) - 2, 1)))
        se_beta = residual_std / (np.std(x, ddof=1) * np.sqrt(len(x) - 1))
        t_stat = beta / se_beta if se_beta > 0 else float("nan")
        return {
            "label": label, "n": len(sub),
            "beta": float(beta), "alpha": float(alpha),
            "t_stat": float(t_stat), "r2": float(r2),
        }

    # Train = TRAIN_EVENTS, Test = TEST_EVENTS.
    train = panel[panel["event_ticker"].isin(TRAIN_EVENTS)]
    test = panel[panel["event_ticker"].isin(TEST_EVENTS)]

    results = []
    for coin in COINS:
        y_col = f"ret_{LAG_MINUTES}m_{coin}"
        results.append(_regress(train, y_col, f"train_{coin}"))
        results.append(_regress(test, y_col, f"test_{coin}"))
        # Null shuffle on test
        test_null = test.copy().reset_index(drop=True)
        rng = np.random.default_rng(NULL_SHUFFLE_SEED + hash(coin) % 1000)
        test_null[y_col] = rng.permutation(test_null[y_col].to_numpy())
        results.append(_regress(test_null, y_col, f"test_null_{coin}"))

    # Per-event breakdown on train (full-distribution discipline)
    for coin in COINS:
        y_col = f"ret_{LAG_MINUTES}m_{coin}"
        for event in TRAIN_EVENTS:
            sub = panel[panel["event_ticker"] == event]
            results.append(_regress(sub, y_col, f"per_event_{event}_{coin}"))

    report = pd.DataFrame(results).set_index("label")
    report.to_csv(OUT_DIR / "regression_results.csv")

    print("[6/6] evaluating pre-registered pass criteria...")
    pass_any_coin = False
    pass_detail = []
    for coin in COINS:
        test_row = report.loc[f"test_{coin}"]
        null_row = report.loc[f"test_null_{coin}"]
        pass_a = abs(test_row["t_stat"]) > MIN_ABS_T_STAT
        pass_b = test_row["r2"] > MIN_R2
        pass_c = np.sign(test_row["beta"]) == np.sign(EXPECTED_BETA_SIGN)
        if abs(test_row["t_stat"]) > 0 and abs(null_row["t_stat"]) > 0:
            ratio = abs(null_row["t_stat"]) / abs(test_row["t_stat"])
        else:
            ratio = float("nan")
        pass_d = not np.isnan(ratio) and ratio < MAX_NULL_T_STAT_RATIO
        coin_pass = bool(pass_a and pass_b and pass_c and pass_d)
        pass_any_coin = pass_any_coin or coin_pass
        pass_detail.append((coin, pass_a, pass_b, pass_c, pass_d, coin_pass))

    # --- report ---
    lines = [
        "=" * 72,
        "#4 Phase 1 FOMC Event Study — Summary",
        "=" * 72,
        "",
        report.to_string(float_format=lambda v: f"{v:+.5f}"),
        "",
        "Pre-registered pass criteria (ALL required per coin):",
        f"  (a) |t-stat β| > {MIN_ABS_T_STAT:.1f}",
        f"  (b) R² > {MIN_R2:.4f}",
        f"  (c) sign(β) = {EXPECTED_BETA_SIGN:+.0f} (dovish -> BTC up)",
        f"  (d) |null t-stat| < {MAX_NULL_T_STAT_RATIO:.3f} × |real t-stat|",
        "",
    ]
    for coin, pa, pb, pc, pd_, cp in pass_detail:
        lines.append(
            f"  {coin}: a={'✓' if pa else '✗'} "
            f"b={'✓' if pb else '✗'} "
            f"c={'✓' if pc else '✗'} "
            f"d={'✓' if pd_ else '✗'} "
            f"→ {'PASS' if cp else 'FAIL'}"
        )
    lines.append("")
    lines.append(
        f"OVERALL: {'PASS — proceed to §7 MVP' if pass_any_coin else 'FAIL — revisit per §12.5'}"
    )
    lines.append("=" * 72)
    out = "\n".join(lines)
    print("\n" + out)
    (OUT_DIR / "summary.txt").write_text(out)


if __name__ == "__main__":
    main()
