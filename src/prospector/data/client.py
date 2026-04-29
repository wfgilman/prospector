"""
Thin HTTP wrapper around the Hyperliquid Info API.

All public methods return raw dicts/lists straight from the API.
Higher-level concerns (pagination, parquet storage) live in download.py.

Coin naming: Hyperliquid's API uses bare tickers ("BTC", "ETH").
Callers may pass either "BTC" or "BTC-PERP"; this module normalises to
the bare form before sending requests.
"""

from __future__ import annotations

import httpx

INFO_URL = "https://api.hyperliquid.xyz/info"
_TIMEOUT = 30.0  # seconds


def _coin(name: str) -> str:
    """Normalise 'BTC-PERP' or 'BTC_PERP' → 'BTC' for API calls.

    The elder runner uses underscore-suffixed names (`BIGTIME_PERP`) as
    parquet-friendly identifiers and passes them straight through to
    `download_pair`. Without the underscore variant, those names reach
    the Hyperliquid API as-is and the endpoint returns HTTP 500.
    """
    return name.removesuffix("-PERP").removesuffix("_PERP")


class HyperliquidClient:
    """Synchronous client for the Hyperliquid Info API."""

    def __init__(self, base_url: str = INFO_URL, timeout: float = _TIMEOUT) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def _post(self, payload: dict) -> list | dict:
        with httpx.Client(timeout=self._timeout) as http:
            response = http.post(self._base_url, json=payload)
            response.raise_for_status()
            return response.json()

    def candles(
        self,
        coin: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict]:
        """
        Fetch up to 5000 OHLCV candles for a single time window.

        Args:
            coin:      Ticker, e.g. "BTC" or "BTC-PERP".
            interval:  One of "1m","3m","5m","15m","30m","1h","2h","4h",
                       "8h","12h","1d","3d","1w","1M".
            start_ms:  Window start, milliseconds since Unix epoch.
            end_ms:    Window end, milliseconds since Unix epoch.

        Returns:
            List of candle dicts with keys: t, T, o, h, l, c, v, n, i, s.
            Prices and volume are strings; cast downstream.
        """
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": _coin(coin),
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        result = self._post(payload)
        if not isinstance(result, list):
            raise ValueError(f"Unexpected candles response: {result}")
        return result

    def l2_snapshot(self, coin: str) -> dict:
        """
        Fetch the current L2 order book (top 20 levels per side).

        Returns a dict with keys "coin", "levels" (list of [bids, asks]),
        and "time".
        """
        payload = {"type": "l2Book", "coin": _coin(coin)}
        result = self._post(payload)
        if not isinstance(result, dict):
            raise ValueError(f"Unexpected l2Book response: {result}")
        return result

    def all_mids(self) -> dict[str, str]:
        """Return mid prices for all active perpetual markets."""
        result = self._post({"type": "allMids"})
        if not isinstance(result, dict):
            raise ValueError(f"Unexpected allMids response: {result}")
        return result

    def meta(self) -> dict:
        """Return exchange metadata including all listed perpetual assets."""
        result = self._post({"type": "meta"})
        if not isinstance(result, dict):
            raise ValueError(f"Unexpected meta response: {result}")
        return result

    def funding_history(
        self,
        coin: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[dict]:
        """
        Fetch funding-rate history for a single coin over a time window.

        Hyperliquid returns one row per funding tick (hourly on perp markets).
        Each entry has keys: coin, fundingRate (string decimal), premium
        (string decimal — mark-vs-index basis), time (ms since epoch).

        Args:
            coin:     Ticker, e.g. "BTC" or "BTC-PERP".
            start_ms: Window start, milliseconds since epoch.
            end_ms:   Optional window end; if None, Hyperliquid returns up
                      to the current time.

        Returns:
            List of funding dicts. Caller is responsible for pagination
            (Hyperliquid caps responses; 500-hour windows are safe).
        """
        payload: dict = {
            "type": "fundingHistory",
            "coin": _coin(coin),
            "startTime": start_ms,
        }
        if end_ms is not None:
            payload["endTime"] = end_ms
        result = self._post(payload)
        if not isinstance(result, list):
            raise ValueError(f"Unexpected fundingHistory response: {result}")
        return result
