"""Unit tests for the Kalshi client. No real API calls."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from prospector.kalshi import KalshiClient, KalshiError, Market, Orderbook
from prospector.kalshi.client import (
    _parse_market,
    _parse_orderbook,
    _parse_position,
    _parse_price,
    _parse_trade,
)


@pytest.fixture
def rsa_pem() -> bytes:
    """Generate an ephemeral RSA key for tests."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def client(rsa_pem: bytes, monkeypatch) -> KalshiClient:
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
    return KalshiClient(key_id="test-key-id", private_key_pem=rsa_pem.decode())


class TestAuth:
    def test_missing_key_id_raises(self, rsa_pem, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        with pytest.raises(KalshiError, match="key_id"):
            KalshiClient(private_key_pem=rsa_pem.decode())

    def test_missing_private_key_raises(self, monkeypatch):
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        with pytest.raises(KalshiError, match="private key"):
            KalshiClient(key_id="x")

    def test_both_path_and_pem_raises(self, rsa_pem, tmp_path):
        pem_file = tmp_path / "key.pem"
        pem_file.write_bytes(rsa_pem)
        with pytest.raises(KalshiError, match="not both"):
            KalshiClient(
                key_id="x",
                private_key_path=str(pem_file),
                private_key_pem=rsa_pem.decode(),
            )

    def test_env_var_loading(self, rsa_pem, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "env-key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", rsa_pem.decode())
        c = KalshiClient()
        assert c._key_id == "env-key"

    def test_signature_verifies(self, client, rsa_pem):
        headers = client._sign("GET", "/trade-api/v2/markets?status=open")
        ts = headers["KALSHI-ACCESS-TIMESTAMP"]
        sig = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        # Path in signature MUST exclude query string
        message = f"{ts}GET/trade-api/v2/markets".encode()
        public_key = serialization.load_pem_private_key(rsa_pem, password=None).public_key()
        # verify() raises if the signature is invalid
        public_key.verify(
            sig,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )


class TestRequestRetry:
    def test_retries_on_429_then_succeeds(self, client, monkeypatch):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(429)
            return httpx.Response(200, json={"ok": True})

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        assert client.get("/x") == {"ok": True}
        assert calls["n"] == 2

    def test_raises_after_max_retries(self, client, monkeypatch):
        def handler(_req):
            return httpx.Response(500)

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        with pytest.raises(KalshiError, match="failed after"):
            client.get("/x")

    def test_raises_on_network_failure(self, client, monkeypatch):
        def handler(_req):
            raise httpx.ConnectError("boom")

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        with pytest.raises(KalshiError):
            client.get("/x")


class TestPriceParsing:
    def test_dollars_string_preferred(self):
        assert _parse_price("0.54", default_scale_if_gt_one=False) == 0.54

    def test_cents_integer_scaled(self):
        assert _parse_price(54) == 0.54

    def test_already_fractional_not_scaled(self):
        assert _parse_price(0.54) == 0.54

    def test_clamps_above_one(self):
        assert _parse_price("1.5", default_scale_if_gt_one=False) == 1.0

    def test_clamps_below_zero(self):
        assert _parse_price("-0.5", default_scale_if_gt_one=False) == 0.0

    def test_none_returns_none(self):
        assert _parse_price(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_price("") is None


class TestMarketParsing:
    def test_parses_dollars_fields(self):
        raw = {
            "ticker": "KXNFL-2026-TEAM1",
            "event_ticker": "KXNFL-2026",
            "series_ticker": "KXNFL",
            "title": "Will Team 1 win?",
            "status": "active",
            "result": "",
            "open_time": "2026-01-01T00:00:00Z",
            "close_time": "2026-02-01T00:00:00Z",
            "yes_bid_dollars": "0.35",
            "yes_ask_dollars": "0.40",
            "no_bid_dollars": "0.60",
            "no_ask_dollars": "0.65",
            "last_price_dollars": "0.37",
            "volume": 1000,
            "open_interest": 500,
            "category": "Sports",
        }
        market = _parse_market(raw)
        assert market.ticker == "KXNFL-2026-TEAM1"
        assert market.yes_bid == 0.35
        assert market.yes_ask == 0.40
        assert market.last_price == 0.37
        assert market.volume == 1000
        assert market.close_time == datetime(2026, 2, 1, tzinfo=timezone.utc)
        assert market.is_open

    def test_falls_back_to_cents_fields(self):
        raw = {
            "ticker": "X",
            "status": "active",
            "yes_bid": 35,
            "yes_ask": 40,
            "last_price": 37,
        }
        market = _parse_market(raw)
        assert market.yes_bid == 0.35
        assert market.last_price == 0.37

    def test_settled_market(self):
        raw = {"ticker": "X", "status": "settled", "result": "yes"}
        m = _parse_market(raw)
        assert m.is_resolved
        assert not m.is_open
        assert m.result == "yes"

    def test_missing_prices_are_none(self):
        raw = {"ticker": "X", "status": "active"}
        m = _parse_market(raw)
        assert m.yes_bid is None
        assert m.yes_ask is None


class TestOrderbookParsing:
    def test_parses_both_sides(self):
        raw = {
            "yes_dollars": [["0.35", 100], ["0.34", 200]],
            "no_dollars": [["0.60", 50]],
        }
        ob = _parse_orderbook("X", raw)
        assert len(ob.yes) == 2
        assert ob.yes[0].price == 0.35
        assert ob.yes[0].size == 100
        assert ob.yes_best_bid == 0.35
        assert ob.no_best_bid == 0.60

    def test_empty_sides(self):
        ob = _parse_orderbook("X", {})
        assert ob.yes == []
        assert ob.no == []
        assert ob.yes_best_bid is None

    def test_skips_zero_size_levels(self):
        raw = {"yes_dollars": [["0.35", 0], ["0.34", 100]]}
        ob = _parse_orderbook("X", raw)
        assert len(ob.yes) == 1
        assert ob.yes[0].price == 0.34


class TestPositionParsing:
    def test_yes_position(self):
        raw = {
            "ticker": "X",
            "position_fp": 10,
            "average_price_dollars": "0.40",
            "market_exposure_dollars": "4.00",
            "realized_pnl_dollars": "0.50",
        }
        p = _parse_position(raw)
        assert p.ticker == "X"
        assert p.contracts == 10
        assert p.side == "yes"
        assert p.average_price == 0.40
        assert p.market_exposure == 4.00
        assert p.realized_pnl == 0.50

    def test_no_position(self):
        raw = {"ticker": "X", "position_fp": -5}
        p = _parse_position(raw)
        assert p.contracts == 5
        assert p.side == "no"


class TestPlaceOrderValidation:
    def test_rejects_bad_side(self, client):
        with pytest.raises(ValueError, match="side"):
            client.place_order("X", "maybe", 10, 50, "cid")

    def test_rejects_bad_action(self, client):
        with pytest.raises(ValueError, match="action"):
            client.place_order("X", "yes", 10, 50, "cid", action="short")

    def test_rejects_price_out_of_range(self, client):
        with pytest.raises(ValueError, match="price_cents"):
            client.place_order("X", "yes", 10, 100, "cid")
        with pytest.raises(ValueError, match="price_cents"):
            client.place_order("X", "yes", 10, 0, "cid")


class TestEndpoints:
    def test_fetch_market_returns_dataclass(self, client, monkeypatch):
        def handler(_req):
            return httpx.Response(
                200,
                json={
                    "market": {
                        "ticker": "X",
                        "event_ticker": "E",
                        "status": "active",
                        "yes_bid_dollars": "0.42",
                    }
                },
            )

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        m = client.fetch_market("X")
        assert isinstance(m, Market)
        assert m.yes_bid == 0.42

    def test_fetch_orderbook_returns_dataclass(self, client, monkeypatch):
        def handler(_req):
            return httpx.Response(
                200,
                json={
                    "orderbook_fp": {
                        "yes_dollars": [["0.35", 100]],
                        "no_dollars": [["0.60", 50]],
                    }
                },
            )

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        ob = client.fetch_orderbook("X")
        assert isinstance(ob, Orderbook)
        assert ob.yes_best_bid == 0.35

    def test_iter_markets_paginates(self, client, monkeypatch):
        page1 = [{"ticker": f"T{i}", "status": "active"} for i in range(200)]
        pages = iter(
            [
                {"markets": page1, "cursor": "abc"},
                {"markets": [{"ticker": "T200", "status": "active"}], "cursor": ""},
            ]
        )

        def handler(_req):
            return httpx.Response(200, json=next(pages))

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        tickers = [m.ticker for m in client.iter_markets()]
        assert len(tickers) == 201
        assert tickers[0] == "T0"
        assert tickers[-1] == "T200"

    def test_get_balance_prefers_dollars(self, client, monkeypatch):
        def handler(_req):
            return httpx.Response(200, json={"balance_dollars": "1234.56", "balance": 999999})

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        assert client.get_balance() == 1234.56

    def test_get_balance_falls_back_to_cents(self, client, monkeypatch):
        def handler(_req):
            return httpx.Response(200, json={"balance": 123456})

        client._http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        monkeypatch.setattr("prospector.kalshi.client.time.sleep", lambda _x: None)
        assert client.get_balance() == 1234.56


class TestParseTrade:
    def test_parses_cent_prices(self):
        raw = {
            "trade_id": "t-1",
            "ticker": "KXBTC-25JAN0117-B84500",
            "count": 10,
            "yes_price": 42,
            "no_price": 58,
            "taker_side": "yes",
            "created_time": "2025-01-01T10:30:45.123Z",
        }
        trade = _parse_trade(raw)
        assert trade.trade_id == "t-1"
        assert trade.count == 10
        assert trade.yes_price == 0.42
        assert trade.no_price == 0.58
        assert trade.taker_side == "yes"
        assert trade.created_time.year == 2025

    def test_prefers_dollar_fields_when_present(self):
        raw = {
            "trade_id": "t-2", "ticker": "X", "count": 1,
            "yes_price": 42, "yes_price_dollars": "0.4237",
            "no_price": 58, "no_price_dollars": "0.5763",
            "taker_side": "no", "created_time": "2026-01-01T00:00:00Z",
        }
        trade = _parse_trade(raw)
        assert trade.yes_price == 0.4237
        assert trade.no_price == 0.5763

    def test_missing_created_time_raises(self):
        raw = {
            "trade_id": "t-3", "ticker": "X", "count": 1,
            "yes_price": 50, "no_price": 50, "taker_side": "yes",
        }
        with pytest.raises(KalshiError, match="created_time"):
            _parse_trade(raw)


class TestIterTrades:
    def test_paginates_and_stops_on_empty_cursor(self, client, monkeypatch):
        page1 = {
            "trades": [
                {"trade_id": f"t{i}", "ticker": "X", "count": 1,
                 "yes_price": 50, "no_price": 50, "taker_side": "yes",
                 "created_time": "2026-01-01T00:00:00Z"}
                for i in range(200)
            ],
            "cursor": "abc",
        }
        page2 = {
            "trades": [
                {"trade_id": "t-last", "ticker": "X", "count": 1,
                 "yes_price": 50, "no_price": 50, "taker_side": "yes",
                 "created_time": "2026-01-02T00:00:00Z"}
            ],
            "cursor": None,
        }
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=page1 if calls["n"] == 1 else page2)

        client._http = httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://t"
        )
        monkeypatch.setattr(
            "prospector.kalshi.client.time.sleep", lambda _x: None
        )
        trades = list(client.iter_trades(ticker="X"))
        assert len(trades) == 201
        assert trades[-1].trade_id == "t-last"
        assert calls["n"] == 2

    def test_respects_min_max_ts_in_url(self, client, monkeypatch):
        seen_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200, json={"trades": [], "cursor": None})

        client._http = httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://t"
        )
        monkeypatch.setattr(
            "prospector.kalshi.client.time.sleep", lambda _x: None
        )
        list(client.iter_trades(ticker="X", min_ts=1000, max_ts=2000))
        assert any("min_ts=1000" in u for u in seen_urls)
        assert any("max_ts=2000" in u for u in seen_urls)


class TestIterEventsSeriesFilter:
    def test_series_ticker_query_param(self, client, monkeypatch):
        seen_urls = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200, json={"events": [], "cursor": None})

        client._http = httpx.Client(
            transport=httpx.MockTransport(handler), base_url="http://t"
        )
        monkeypatch.setattr(
            "prospector.kalshi.client.time.sleep", lambda _x: None
        )
        list(client.iter_events(status="settled", series_ticker="KXBTC"))
        assert any("series_ticker=KXBTC" in u for u in seen_urls)
        assert any("status=settled" in u for u in seen_urls)
