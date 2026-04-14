"""
OHLCV download pipeline: fetches candle history from Hyperliquid and stores
it as local parquet files, one file per (coin, interval) pair.

Storage layout:
    data/ohlcv/<coin>/<interval>.parquet

Schema (all columns):
    timestamp  datetime64[ms, UTC]   bar open time
    open       float64
    high       float64
    low        float64
    close      float64
    volume     float64
    trades     int64                  number of trades in the bar

Usage (CLI):
    python -m prospector.data.download

Usage (library):
    from prospector.data.download import download_all, download_pair
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from prospector.data.client import HyperliquidClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "ohlcv"

# Pairs to download. Extend as the securities universe grows.
DEFAULT_COINS = ["BTC-PERP", "ETH-PERP", "SOL-PERP"]

# Intervals required by the strategy templates.
# triple_screen needs 1w/1d and 1d/4h; others need 4h or 1h.
DEFAULT_INTERVALS = ["1w", "1d", "4h", "1h"]

# How far back to fetch on a fresh download.
DEFAULT_LOOKBACK_DAYS = 730  # ~2 years; enough for walk-forward splits

# Hyperliquid returns at most this many candles per request.
MAX_CANDLES_PER_REQUEST = 5000

# Interval string → milliseconds per bar (used for pagination arithmetic).
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _parquet_path(coin: str, interval: str, base: Path = DATA_DIR) -> Path:
    safe_coin = coin.replace("-", "_")
    return base / safe_coin / f"{interval}.parquet"


def _last_timestamp_ms(path: Path) -> int | None:
    """Return the most recent bar timestamp in an existing parquet file, or None."""
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["timestamp"])
    if df.empty:
        return None
    ts = df["timestamp"].max()
    return int(ts.timestamp() * 1000)


def _candles_to_df(candles: list[dict]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                             "l": "low", "c": "close", "v": "volume", "n": "trades"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["trades"] = df["trades"].astype(int)
    return df[["timestamp", "open", "high", "low", "close", "volume", "trades"]]


def _append_and_save(path: Path, new_df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="timestamp").sort_values("timestamp")
    else:
        combined = new_df.sort_values("timestamp")
    combined.to_parquet(path, index=False)


def download_pair(
    coin: str,
    interval: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
    client: HyperliquidClient | None = None,
) -> pd.DataFrame:
    """
    Download and store OHLCV history for a single (coin, interval) pair.

    If a local parquet file already exists, only new candles since the last
    stored timestamp are fetched (incremental update). Otherwise fetches
    `lookback_days` of history.

    Returns the complete local DataFrame after updating.
    """
    if client is None:
        client = HyperliquidClient()

    path = _parquet_path(coin, interval, base)
    bar_ms = _INTERVAL_MS.get(interval)
    if bar_ms is None:
        raise ValueError(f"Unknown interval: {interval!r}")

    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    last_ms = _last_timestamp_ms(path)

    if last_ms is not None:
        # Fetch from the bar after the last stored one.
        start_ms = last_ms + bar_ms
        log.info("%s/%s: incremental update from %s", coin, interval,
                 datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat())
    else:
        # Clamp lookback to the API's 5000-candle limit per interval.
        # Requesting older than available returns an empty response silently.
        max_api_lookback_ms = (MAX_CANDLES_PER_REQUEST - 1) * bar_ms
        desired_start_ms = now_ms - lookback_days * 86_400_000
        start_ms = max(desired_start_ms, now_ms - max_api_lookback_ms)
        if start_ms > desired_start_ms:
            log.warning(
                "%s/%s: lookback capped to %d candles (~%.0f days); API limit",
                coin, interval, MAX_CANDLES_PER_REQUEST - 1,
                max_api_lookback_ms / 86_400_000,
            )
        log.info("%s/%s: fresh download from %s", coin, interval,
                 datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat())

    all_candles: list[dict] = []
    window_start = start_ms

    while window_start < now_ms:
        window_end = min(window_start + MAX_CANDLES_PER_REQUEST * bar_ms, now_ms)
        batch = client.candles(coin, interval, window_start, window_end)
        if not batch:
            break
        all_candles.extend(batch)
        last_in_batch = batch[-1]["t"]
        log.debug("%s/%s: fetched %d candles up to %s",
                  coin, interval, len(batch),
                  datetime.fromtimestamp(last_in_batch / 1000, tz=timezone.utc).isoformat())
        window_start = last_in_batch + bar_ms

    if all_candles:
        new_df = _candles_to_df(all_candles)
        _append_and_save(path, new_df)
        log.info("%s/%s: saved %d new candles → %s", coin, interval, len(new_df), path)
    elif last_ms is not None:
        log.info("%s/%s: already up to date", coin, interval)
    else:
        log.warning("%s/%s: fresh download returned no data — check interval/pair availability", coin, interval)

    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def download_all(
    coins: list[str] = DEFAULT_COINS,
    intervals: list[str] = DEFAULT_INTERVALS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
) -> None:
    """Download/update OHLCV for all (coin, interval) combinations."""
    client = HyperliquidClient()
    total = len(coins) * len(intervals)
    done = 0
    for coin in coins:
        for interval in intervals:
            done += 1
            log.info("[%d/%d] %s/%s", done, total, coin, interval)
            try:
                download_pair(coin, interval, lookback_days, base, client)
            except Exception:
                log.exception("Failed to download %s/%s", coin, interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Download Hyperliquid OHLCV data")
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS,
                        help="Coins to download, e.g. BTC-PERP ETH-PERP")
    parser.add_argument("--intervals", nargs="+", default=DEFAULT_INTERVALS,
                        help="Intervals to download, e.g. 1d 4h 1h")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help="Days of history for a fresh download")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help="Root directory for parquet files")
    args = parser.parse_args()

    download_all(
        coins=args.coins,
        intervals=args.intervals,
        lookback_days=args.lookback_days,
        base=args.data_dir,
    )
