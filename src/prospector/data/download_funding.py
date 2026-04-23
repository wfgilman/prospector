"""
Hyperliquid funding-rate download pipeline. Mirrors the structure of
`download.py` for OHLCV candles but pulls hourly funding + premium-index
history per coin.

Storage layout:
    data/hyperliquid/funding/<coin>.parquet

Schema:
    time          datetime64[ms, UTC]   funding tick time (hourly on Hyperliquid)
    coin          str                   bare ticker (e.g. "BTC")
    funding_rate  float64               per-hour rate as decimal (e.g. 0.0000125)
    premium       float64               mark-vs-index basis as decimal

Usage (CLI):
    python -m prospector.data.download_funding --coins BTC ETH SOL

Usage (library):
    from prospector.data.download_funding import download_funding_pair, download_funding_all
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from prospector.data.client import HyperliquidClient

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "hyperliquid" / "funding"
DEFAULT_COINS = ["BTC", "ETH", "SOL"]
DEFAULT_LOOKBACK_DAYS = 730

# Hyperliquid caps each fundingHistory response. 500 hours = ~20 days is
# safely under the cap; page through to cover longer windows.
HOURS_PER_PAGE = 500
MS_PER_HOUR = 3_600_000
MS_PER_DAY = 86_400_000


def _parquet_path(coin: str, base: Path = DATA_DIR) -> Path:
    safe = coin.replace("-", "_").upper()
    return base / f"{safe}.parquet"


def _last_time_ms(path: Path) -> int | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["time"])
    if df.empty:
        return None
    ts = df["time"].max()
    return int(ts.timestamp() * 1000)


def _funding_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=["time", "coin", "funding_rate", "premium"]
        )
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float)
    return df[["time", "coin", "funding_rate", "premium"]]


def _append_and_save(path: Path, new_df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["time", "coin"]).sort_values("time")
    else:
        combined = new_df.sort_values("time")
    combined.to_parquet(path, index=False)


def download_funding_pair(
    coin: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
    client: HyperliquidClient | None = None,
) -> pd.DataFrame:
    """Download and persist funding-rate history for a single coin.

    Incremental: if a parquet already exists, only new ticks since the last
    stored `time` are fetched. Otherwise fetches `lookback_days` of history.
    """
    if client is None:
        client = HyperliquidClient()

    path = _parquet_path(coin, base)
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    last_ms = _last_time_ms(path)

    if last_ms is not None:
        start_ms = last_ms + MS_PER_HOUR
        log.info(
            "%s: incremental funding update from %s",
            coin,
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        )
    else:
        start_ms = now_ms - lookback_days * MS_PER_DAY
        log.info(
            "%s: fresh funding download from %s",
            coin,
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        )

    all_rows: list[dict] = []
    window_start = start_ms
    while window_start < now_ms:
        window_end = min(
            window_start + HOURS_PER_PAGE * MS_PER_HOUR, now_ms
        )
        batch = client.funding_history(coin, window_start, window_end)
        if not batch:
            break
        all_rows.extend(batch)
        last_in_batch = batch[-1]["time"]
        window_start = last_in_batch + MS_PER_HOUR
        log.debug("%s: fetched %d funding ticks up to %d", coin, len(batch), last_in_batch)

    if all_rows:
        new_df = _funding_to_df(all_rows)
        _append_and_save(path, new_df)
        log.info("%s: saved %d funding ticks → %s", coin, len(new_df), path)
    elif last_ms is not None:
        log.info("%s: funding already up to date", coin)
    else:
        log.warning(
            "%s: fresh funding download returned no data — check coin name",
            coin,
        )
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def download_funding_all(
    coins: list[str] = DEFAULT_COINS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    base: Path = DATA_DIR,
) -> None:
    client = HyperliquidClient()
    for i, coin in enumerate(coins, 1):
        log.info("[%d/%d] funding: %s", i, len(coins), coin)
        try:
            download_funding_pair(coin, lookback_days, base, client)
        except Exception:
            log.exception("Failed to download funding for %s", coin)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Download Hyperliquid funding-rate history"
    )
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    parser.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    download_funding_all(
        coins=args.coins,
        lookback_days=args.lookback_days,
        base=args.data_dir,
    )
