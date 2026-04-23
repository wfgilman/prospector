"""Kalshi REST API client.

Authentication is RSA-PSS-SHA256 on a `{ts_ms}{METHOD}{path_without_qs}` message.
Headers: KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP.

Credentials can be supplied via constructor arguments or environment variables
KALSHI_API_KEY_ID plus one of (KALSHI_PRIVATE_KEY_PATH | KALSHI_PRIVATE_KEY_PEM).
"""

from __future__ import annotations

import base64
import logging
import os
import time
from datetime import datetime
from typing import Iterator

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from prospector.kalshi.models import Market, Orderbook, OrderbookLevel, Position, Trade

logger = logging.getLogger(__name__)

API_BASE = "https://api.elections.kalshi.com"
API_PREFIX = "/trade-api/v2"
_TIMEOUT = 30.0
_MAX_RETRIES = 3
_PAGE_LIMIT = 200


class KalshiError(RuntimeError):
    """Raised when a Kalshi request fails after all retries."""


class KalshiClient:
    """Synchronous client for the Kalshi trade API."""

    def __init__(
        self,
        key_id: str | None = None,
        private_key_path: str | None = None,
        private_key_pem: str | None = None,
        base_url: str = API_BASE,
        timeout: float = _TIMEOUT,
    ) -> None:
        key_id = key_id or os.environ.get("KALSHI_API_KEY_ID")
        if not key_id:
            raise KalshiError("Kalshi key_id not provided and KALSHI_API_KEY_ID unset")
        pem_bytes = _load_private_key_pem(private_key_path, private_key_pem)
        self._key_id = key_id
        self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _sign(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        path_no_qs = path.split("?", 1)[0]
        message = f"{ts}{method}{path_no_qs}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._http.request(
                    method,
                    path,
                    headers=self._sign(method, path),
                    json=body,
                )
                if response.status_code == 429:
                    logger.warning(
                        "Kalshi 429 on %s %s (attempt %d/%d)",
                        method,
                        path,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt + 1 == _MAX_RETRIES:
                    break
                time.sleep(1 + attempt)
        raise KalshiError(f"{method} {path} failed after {_MAX_RETRIES} attempts") from last_exc

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    def fetch_market(self, ticker: str) -> Market:
        data = self.get(f"{API_PREFIX}/markets/{ticker}")
        raw = data.get("market") or data
        return _parse_market(raw)

    def fetch_event(self, event_ticker: str) -> tuple[dict, list[Market]]:
        """Fetch an event and its embedded markets in one call.

        Returns (event_dict, [Market, ...]). Use this for backfill —
        the list endpoint `/markets?event_ticker=X` does not reliably
        return markets for already-resolved events, but `/events/{tkr}`
        always does."""
        data = self.get(f"{API_PREFIX}/events/{event_ticker}")
        event = data.get("event", data)
        markets_raw = data.get("markets") or event.get("markets") or []
        markets = [_parse_market(m) for m in markets_raw]
        return event, markets

    def fetch_orderbook(self, ticker: str, depth: int = 10) -> Orderbook:
        data = self.get(f"{API_PREFIX}/markets/{ticker}/orderbook?depth={depth}")
        ob = data.get("orderbook_fp", data.get("orderbook", data))
        return _parse_orderbook(ticker, ob)

    def iter_events(
        self,
        status: str = "open",
        series_ticker: str | None = None,
    ) -> Iterator[dict]:
        """Page through events. `status` may be 'open', 'closed', 'settled',
        or a comma-separated combination (Kalshi's API accepts multiple).

        `series_ticker` narrows to a single series (e.g., 'KXBTC', 'FED') —
        essential for backfill so we don't iterate the full universe."""
        cursor: str | None = None
        while True:
            path = f"{API_PREFIX}/events?status={status}&limit={_PAGE_LIMIT}"
            if series_ticker:
                path += f"&series_ticker={series_ticker}"
            if cursor:
                path += f"&cursor={cursor}"
            data = self.get(path)
            events = data.get("events", [])
            for event in events:
                yield event
            cursor = data.get("cursor") or None
            if not cursor or len(events) < _PAGE_LIMIT:
                return
            time.sleep(0.3)

    def iter_markets(
        self,
        *,
        status: str = "open",
        event_ticker: str | None = None,
        series_ticker: str | None = None,
    ) -> Iterator[Market]:
        cursor: str | None = None
        while True:
            path = f"{API_PREFIX}/markets?limit={_PAGE_LIMIT}&status={status}"
            if event_ticker:
                path += f"&event_ticker={event_ticker}"
            if series_ticker:
                path += f"&series_ticker={series_ticker}"
            if cursor:
                path += f"&cursor={cursor}"
            data = self.get(path)
            markets = data.get("markets", [])
            for market in markets:
                yield _parse_market(market)
            cursor = data.get("cursor") or None
            if not cursor or len(markets) < _PAGE_LIMIT:
                return
            time.sleep(0.3)

    def iter_trades(
        self,
        ticker: str | None = None,
        *,
        min_ts: int | None = None,
        max_ts: int | None = None,
    ) -> Iterator[Trade]:
        """Page through historical trades.

        Kalshi's `/markets/trades` accepts optional `ticker`, `min_ts`,
        `max_ts` (seconds since epoch), and cursor pagination. Trades are
        returned newest-first. Without a ticker filter the endpoint walks
        the global trade stream — useful for sanity checks but wrong for
        backfill; callers typically pass a ticker."""
        cursor: str | None = None
        while True:
            path = f"{API_PREFIX}/markets/trades?limit={_PAGE_LIMIT}"
            if ticker:
                path += f"&ticker={ticker}"
            if min_ts is not None:
                path += f"&min_ts={min_ts}"
            if max_ts is not None:
                path += f"&max_ts={max_ts}"
            if cursor:
                path += f"&cursor={cursor}"
            data = self.get(path)
            trades = data.get("trades", [])
            for raw in trades:
                yield _parse_trade(raw)
            cursor = data.get("cursor") or None
            if not cursor or len(trades) < _PAGE_LIMIT:
                return
            time.sleep(0.3)

    def iter_positions(self, settlement_status: str = "unsettled") -> Iterator[Position]:
        cursor: str | None = None
        while True:
            path = (
                f"{API_PREFIX}/portfolio/positions?limit={_PAGE_LIMIT}"
                f"&count_filter=position&settlement_status={settlement_status}"
            )
            if cursor:
                path += f"&cursor={cursor}"
            data = self.get(path)
            positions = data.get("market_positions", [])
            for raw in positions:
                yield _parse_position(raw)
            cursor = data.get("cursor") or None
            if not cursor or len(positions) < _PAGE_LIMIT:
                return
            time.sleep(0.3)

    def get_balance(self) -> float:
        data = self.get(f"{API_PREFIX}/portfolio/balance")
        if "balance_dollars" in data:
            return round(float(data["balance_dollars"]), 2)
        cents = data.get("balance", 0)
        return round(cents / 100, 2)

    def place_order(
        self,
        ticker: str,
        side: str,
        contracts: int,
        price_cents: int,
        client_order_id: str,
        action: str = "buy",
    ) -> dict:
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
        if action not in ("buy", "sell"):
            raise ValueError(f"action must be 'buy' or 'sell', got {action!r}")
        if not 1 <= price_cents <= 99:
            raise ValueError(f"price_cents must be in [1, 99], got {price_cents}")
        price_field = f"{side}_price_dollars"
        body = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "type": "limit",
            "action": action,
            "side": side,
            "count": contracts,
            price_field: f"{price_cents / 100:.2f}",
        }
        return self.post(f"{API_PREFIX}/portfolio/orders", body)

    def cancel_order(self, order_id: str) -> dict:
        return self.post(
            f"{API_PREFIX}/portfolio/orders/{order_id}/decrease",
            {"reduce_by": 1_000_000},
        )

    def get_order(self, order_id: str) -> dict:
        data = self.get(f"{API_PREFIX}/portfolio/orders/{order_id}")
        return data.get("order") or data


def _load_private_key_pem(path: str | None, pem: str | None) -> bytes:
    path = path or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    pem = pem or os.environ.get("KALSHI_PRIVATE_KEY_PEM")
    if path and pem:
        raise KalshiError("provide either private_key_path or private_key_pem, not both")
    if path:
        with open(path, "rb") as f:
            return f.read()
    if pem:
        return pem.encode()
    raise KalshiError(
        "Kalshi private key missing: set KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM"
    )


def _parse_price(raw, default_scale_if_gt_one: bool = True) -> float | None:
    """Parse a Kalshi price to [0, 1]. Accepts dollar strings or cent ints."""
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if default_scale_if_gt_one and value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


def _get_price(raw: dict, side: str) -> float | None:
    """Prefer *_dollars fields (post-Jan 2026 API), fall back to cents."""
    dollars = _parse_price(raw.get(f"{side}_dollars"), default_scale_if_gt_one=False)
    if dollars is not None:
        return dollars
    return _parse_price(raw.get(side))


def _parse_timestamp(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_market(raw: dict) -> Market:
    event_ticker = raw.get("event_ticker", "") or ""
    # Kalshi's /markets response often omits series_ticker; derive from the
    # first dash-separated segment of event_ticker so downstream consumers
    # (notably the portfolio's series-level diversity cap) always have it.
    series_ticker = raw.get("series_ticker") or ""
    if not series_ticker and event_ticker:
        series_ticker = event_ticker.split("-", 1)[0]
    return Market(
        ticker=raw.get("ticker", ""),
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        title=raw.get("title", "") or raw.get("subtitle", ""),
        status=raw.get("status", ""),
        result=raw.get("result", "") or "",
        open_time=_parse_timestamp(raw.get("open_time")),
        close_time=_parse_timestamp(raw.get("close_time")),
        expiration_time=_parse_timestamp(raw.get("expiration_time")),
        yes_bid=_get_price(raw, "yes_bid"),
        yes_ask=_get_price(raw, "yes_ask"),
        no_bid=_get_price(raw, "no_bid"),
        no_ask=_get_price(raw, "no_ask"),
        last_price=_get_price(raw, "last_price"),
        volume=int(raw.get("volume", 0) or 0),
        open_interest=int(raw.get("open_interest", 0) or 0),
        category=raw.get("category", "") or "",
        raw=raw,
    )


def _parse_trade(raw: dict) -> Trade:
    """Normalize a Kalshi trade record. Prices are stored in [0, 1] floats;
    Kalshi publishes `yes_price`/`no_price` as cent integers and may also
    publish `*_dollars` string fields in the post-2026 API.

    Count field: legacy API exposed integer `count`; the 2026 API also
    exposes `count_fp` (fractional) for partial fills. Prefer count if
    present; otherwise parse count_fp and round to nearest int (trades
    at Kalshi are contract-integer at execution, count_fp uses fractional
    representation as a quirk of the new API)."""
    yes = _parse_price(raw.get("yes_price")) or 0.0
    no = _parse_price(raw.get("no_price")) or 0.0
    yes_dollars = _parse_price(raw.get("yes_price_dollars"), default_scale_if_gt_one=False)
    if yes_dollars is not None:
        yes = yes_dollars
    no_dollars = _parse_price(raw.get("no_price_dollars"), default_scale_if_gt_one=False)
    if no_dollars is not None:
        no = no_dollars
    created = _parse_timestamp(raw.get("created_time"))
    if created is None:
        raise KalshiError(f"trade missing created_time: {raw}")
    count_raw = raw.get("count")
    if count_raw is None:
        count_fp_raw = raw.get("count_fp")
        if count_fp_raw is None:
            count = 0
        else:
            try:
                count = int(round(float(count_fp_raw)))
            except (TypeError, ValueError):
                count = 0
    else:
        count = int(count_raw or 0)
    return Trade(
        trade_id=str(raw.get("trade_id", "")),
        ticker=str(raw.get("ticker", "")),
        count=count,
        yes_price=yes,
        no_price=no,
        taker_side=str(raw.get("taker_side", "")),
        created_time=created,
    )


def _parse_orderbook(ticker: str, raw: dict) -> Orderbook:
    def parse_side(side_key: str) -> list[OrderbookLevel]:
        levels_raw = raw.get(f"{side_key}_dollars") or raw.get(side_key) or []
        levels: list[OrderbookLevel] = []
        for level in levels_raw:
            price = _parse_price(level[0], default_scale_if_gt_one=True)
            if price is None:
                continue
            try:
                size = int(float(level[1]))
            except (TypeError, ValueError):
                continue
            if size <= 0:
                continue
            levels.append(OrderbookLevel(price=price, size=size))
        return levels

    return Orderbook(ticker=ticker, yes=parse_side("yes"), no=parse_side("no"))


def _parse_position(raw: dict) -> Position:
    contracts_signed = int(raw.get("position_fp", raw.get("position", 0)) or 0)
    side = "yes" if contracts_signed >= 0 else "no"
    contracts = abs(contracts_signed)
    avg_price = _parse_price(raw.get("average_price_dollars"), default_scale_if_gt_one=False)
    if avg_price is None:
        avg_price = _parse_price(raw.get("average_price"))
    exposure = raw.get("market_exposure_dollars")
    if exposure is None:
        exposure_cents = raw.get("market_exposure", 0) or 0
        exposure = float(exposure_cents) / 100.0
    else:
        exposure = float(exposure)
    realized = raw.get("realized_pnl_dollars")
    if realized is None:
        realized_cents = raw.get("realized_pnl", 0) or 0
        realized = float(realized_cents) / 100.0
    else:
        realized = float(realized)
    return Position(
        ticker=raw.get("ticker", ""),
        contracts=contracts,
        side=side,
        average_price=avg_price,
        market_exposure=float(exposure),
        realized_pnl=float(realized),
    )
