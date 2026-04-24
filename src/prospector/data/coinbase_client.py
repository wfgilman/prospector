"""
Thin HTTP wrapper around the public Coinbase Exchange candles endpoint.

Why Coinbase? Binance global is geo-blocked in the US (HTTP 451 on BTCUSDT).
Coinbase is US-compliant, liquid enough to be a meaningful BTC/ETH price
reference, and exposes 1-minute historical candles back to product launch
(BTC-USD goes to 2015).

Public endpoint, no auth required:
    GET https://api.exchange.coinbase.com/products/{product}/candles

Params:
    granularity: {60, 300, 900, 3600, 21600, 86400} seconds
    start:       ISO-8601 timestamp
    end:         ISO-8601 timestamp

Response shape: list of [time, low, high, open, close, volume] in DESCENDING
time order. Note the column ordering differs from Binance/Hyperliquid.

Coinbase rate limit: 10 req/s public, 15 req/s authenticated. We do ~2 req/s
to stay comfortable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

EXCHANGE_URL = "https://api.exchange.coinbase.com"
_TIMEOUT = 30.0
_MAX_CANDLES_PER_REQUEST = 300  # Coinbase cap
_MIN_SLEEP_S = 0.5


class CoinbaseClient:
    """Synchronous client for the Coinbase Exchange public API."""

    def __init__(self, base_url: str = EXCHANGE_URL, timeout: float = _TIMEOUT) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "CoinbaseClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def candles(
        self,
        product_id: str,
        granularity_s: int,
        start: datetime,
        end: datetime,
    ) -> list[list]:
        """Fetch a single window of candles (up to 300 bars).

        Args:
            product_id:    e.g. "BTC-USD", "ETH-USD"
            granularity_s: 60, 300, 900, 3600, 21600, 86400
            start/end:     UTC datetimes

        Returns:
            List of [time_s, low, high, open, close, volume] in DESCENDING
            time order. Caller normalizes + sorts downstream.
        """
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        params = {
            "granularity": granularity_s,
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
        }
        r = self._http.get(f"/products/{product_id}/candles", params=params)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise ValueError(f"Unexpected candles response: {data}")
        time.sleep(_MIN_SLEEP_S)
        return data
