"""
Coinbase Exchange historical-candle downloader.

Storage layout:
    data/coinbase/<product>/<interval>.parquet

Schema (matches our Hyperliquid OHLCV schema for drop-in compatibility):
    timestamp  datetime64[ms, UTC]   bar open time
    open       float64
    high       float64
    low        float64
    close      float64
    volume     float64

Usage (library):
    from prospector.data.download_coinbase import download_candles
    download_candles("BTC-USD", 60, lookback_days=30)

Usage (CLI):
    python -m prospector.data.download_coinbase --products BTC-USD ETH-USD \
        --granularity 60 --lookback-days 365
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from prospector.data.coinbase_client import CoinbaseClient

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "coinbase"
DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD"]
DEFAULT_GRANULARITY = 60  # 1m
DEFAULT_LOOKBACK_DAYS = 365
CANDLES_PER_REQUEST = 300

_INTERVAL_LABEL = {
    60: "1m", 300: "5m", 900: "15m", 3600: "1h",
    21600: "6h", 86400: "1d",
}


def _parquet_path(product_id: str, granularity_s: int, base: Path = DATA_DIR) -> Path:
    label = _INTERVAL_LABEL.get(granularity_s, f"{granularity_s}s")
    return base / product_id / f"{label}.parquet"


def _candles_to_df(raw: list[list]) -> pd.DataFrame:
    """Normalize Coinbase's [time, low, high, open, close, volume] descending-
    time list into our canonical timestamp/open/high/low/close/volume frame.
    """
    if not raw:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
    df = pd.DataFrame(
        raw, columns=["time", "low", "high", "open", "close", "volume"]
    )
    df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _append_and_save(path: Path, new_df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="timestamp").sort_values("timestamp")
    else:
        combined = new_df.sort_values("timestamp")
    combined.to_parquet(path, index=False)


def _last_timestamp(path: Path) -> datetime | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["timestamp"])
    if df.empty:
        return None
    return df["timestamp"].max().to_pydatetime()


def download_candles(
    product_id: str,
    granularity_s: int = DEFAULT_GRANULARITY,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
    client: CoinbaseClient | None = None,
) -> pd.DataFrame:
    """Download + persist candles for one product at one granularity.

    Incremental on re-run: starts from `last_timestamp + bar_size`.
    Paginates forward in CANDLES_PER_REQUEST windows (~5h for 1m)."""
    if client is None:
        client = CoinbaseClient()

    path = _parquet_path(product_id, granularity_s, base)
    now = datetime.now(timezone.utc)
    last = _last_timestamp(path)
    if last is not None:
        start = last + timedelta(seconds=granularity_s)
        log.info("%s/%ds: incremental from %s", product_id, granularity_s, start.isoformat())
    else:
        start = now - timedelta(days=lookback_days)
        log.info("%s/%ds: fresh download from %s", product_id, granularity_s, start.isoformat())

    window_size = timedelta(seconds=granularity_s * CANDLES_PER_REQUEST)
    all_rows: list[list] = []
    cur = start
    while cur < now:
        end = min(cur + window_size, now)
        batch = client.candles(product_id, granularity_s, cur, end)
        if not batch:
            # Empty response could mean we're past product launch (fresh pull
            # with absurd lookback) or at the exchange's retention boundary.
            # Advance the window and keep trying; if we go a full day with no
            # data, stop.
            cur = end
            continue
        all_rows.extend(batch)
        cur = end

    if not all_rows:
        if last is None:
            log.warning("%s/%ds: no candles returned for lookback %d days",
                        product_id, granularity_s, lookback_days)
        else:
            log.info("%s/%ds: already up to date", product_id, granularity_s)
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    new_df = _candles_to_df(all_rows)
    _append_and_save(path, new_df)
    log.info("%s/%ds: saved %d candles → %s",
             product_id, granularity_s, len(new_df), path)
    return pd.read_parquet(path)


def download_all(
    products: list[str] = DEFAULT_PRODUCTS,
    granularity_s: int = DEFAULT_GRANULARITY,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
) -> None:
    client = CoinbaseClient()
    for i, product in enumerate(products, 1):
        log.info("[%d/%d] %s/%ds", i, len(products), product, granularity_s)
        try:
            download_candles(product, granularity_s, lookback_days, base, client)
        except Exception:
            log.exception("Failed to download %s", product)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Download Coinbase historical candles")
    parser.add_argument("--products", nargs="+", default=DEFAULT_PRODUCTS)
    parser.add_argument("--granularity", type=int, default=DEFAULT_GRANULARITY,
                        help="Seconds per bar: 60, 300, 900, 3600, 21600, 86400")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    download_all(
        products=args.products,
        granularity_s=args.granularity,
        lookback_days=args.lookback_days,
        base=args.data_dir,
    )
