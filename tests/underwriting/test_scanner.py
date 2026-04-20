from datetime import datetime, timezone

import pytest

from prospector.kalshi.models import Market, Orderbook, OrderbookLevel
from prospector.underwriting.calibration import (
    Calibration,
    build_bins_from_rows,
)
from prospector.underwriting.scanner import (
    _executable_prices,
    evaluate_market,
    scan,
)


def _mkt(
    event_ticker: str = "KXNFL-2026-X",
    ticker: str = "KXNFL-2026-X-T1",
    volume: int = 100,
    yes_bid: float | None = None,
    no_bid: float | None = None,
) -> Market:
    return Market(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker="KXNFL",
        title="t",
        status="active",
        result="",
        open_time=datetime(2026, 4, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
        expiration_time=None,
        yes_bid=yes_bid,
        yes_ask=None,
        no_bid=no_bid,
        no_ask=None,
        last_price=None,
        volume=volume,
        open_interest=50,
        category="",
        raw={},
    )


def _ob(yes: list[tuple[float, int]], no: list[tuple[float, int]]) -> Orderbook:
    return Orderbook(
        ticker="T",
        yes=[OrderbookLevel(p, s) for p, s in yes],
        no=[OrderbookLevel(p, s) for p, s in no],
    )


def _sports_calibration_sell(implied_bin=(80, 85)) -> Calibration:
    # Sell-yes signal: implied 80-85%, actual rate 0.75 → -7.5pp deviation
    bins = build_bins_from_rows([(implied_bin[0], implied_bin[1], 500, 375)])
    assert bins[0].side == "sell_yes"
    return Calibration(
        built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        data_window_start="x",
        data_window_end="y",
        min_volume=10,
        curves={"sports": bins, "aggregate": bins},
    )


def _sports_calibration_buy() -> Calibration:
    # Buy-yes signal: implied 5-10%, actual 0.15 → +7.5pp
    bins = build_bins_from_rows([(5, 10, 500, 75)])
    assert bins[0].side == "buy_yes"
    return Calibration(
        built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        data_window_start="x",
        data_window_end="y",
        min_volume=10,
        curves={"sports": bins, "aggregate": bins},
    )


class TestExecutablePrices:
    def test_sell_yes_price_is_yes_bid(self):
        ob = _ob(yes=[(0.82, 100)], no=[(0.18, 200)])
        sell_yes, _, size, _ = _executable_prices(ob)
        assert sell_yes == 0.82
        assert size == 100

    def test_buy_yes_price_is_one_minus_no_bid(self):
        ob = _ob(yes=[(0.82, 100)], no=[(0.18, 200)])
        _, buy_yes, _, size = _executable_prices(ob)
        assert buy_yes == pytest.approx(0.82)
        assert size == 200

    def test_empty_book(self):
        ob = _ob(yes=[], no=[])
        result = _executable_prices(ob)
        assert result == (None, None, 0, 0)

    def test_only_yes_side(self):
        ob = _ob(yes=[(0.82, 100)], no=[])
        sell, buy, _, _ = _executable_prices(ob)
        assert sell == 0.82
        assert buy is None

    def test_only_no_side(self):
        ob = _ob(yes=[], no=[(0.18, 200)])
        sell, buy, _, _ = _executable_prices(ob)
        assert sell is None
        assert buy == pytest.approx(0.82)


class TestEvaluateMarket:
    def test_sell_yes_candidate_when_implied_above_calibration(self):
        cal = _sports_calibration_sell()
        # YES bid at 0.82 (implied 82%); calibration says actual ~75% → sell
        ob = _ob(yes=[(0.82, 100)], no=[(0.17, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        assert cand is not None
        assert cand.side == "sell_yes"
        assert cand.entry_price == 0.82
        assert cand.edge_pp > 2.0
        assert cand.risk_per_contract == pytest.approx(0.18)
        assert cand.reward_per_contract == pytest.approx(0.82)

    def test_buy_yes_candidate_when_implied_below_calibration(self):
        cal = _sports_calibration_buy()
        # NO bid at 0.92 → buy YES at 0.08 (implied 8%); calibration actual ~15%
        ob = _ob(yes=[(0.07, 200)], no=[(0.92, 100)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        assert cand is not None
        assert cand.side == "buy_yes"
        assert cand.entry_price == pytest.approx(0.08)
        assert cand.risk_per_contract == pytest.approx(0.08)

    def test_no_candidate_when_edge_below_threshold(self):
        cal = _sports_calibration_sell()
        # YES bid at 0.82 gives enough edge; require min_edge_pp larger than available
        ob = _ob(yes=[(0.82, 100)], no=[(0.17, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=99.0)
        assert cand is None

    def test_no_candidate_when_price_outside_bin(self):
        cal = _sports_calibration_sell()
        # YES at 0.50 → no bin in this calibration covers 50%
        ob = _ob(yes=[(0.50, 100)], no=[(0.49, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        assert cand is None

    def test_falls_back_to_aggregate_for_unknown_category(self):
        # Strip sports curve, keep aggregate
        bins = build_bins_from_rows([(80, 85, 500, 375)])
        cal = Calibration(
            built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
            data_window_start="x",
            data_window_end="y",
            min_volume=10,
            curves={"aggregate": bins},
        )
        ob = _ob(yes=[(0.82, 100)], no=[(0.17, 50)])
        cand = evaluate_market(_mkt(event_ticker="WEIRD-UNKNOWN"), ob, cal, min_edge_pp=2.0)
        assert cand is not None
        assert cand.category == "other"

    def test_ignores_side_that_disagrees_with_calibration(self):
        # Sell-yes calibration at implied 80-85%, but buy-yes side falls in
        # a bin with no signal — shouldn't surface as a buy candidate.
        cal = _sports_calibration_sell()
        # buy-yes price = 1 - 0.17 = 0.83 (same bin, sell-yes signal)
        # sell-yes price = 0.82 (same bin)
        ob = _ob(yes=[(0.82, 100)], no=[(0.17, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        # Should be the sell side — not the buy side, which doesn't match signal
        assert cand.side == "sell_yes"

    def test_empty_orderbook_returns_none(self):
        cal = _sports_calibration_sell()
        ob = _ob(yes=[], no=[])
        assert evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0) is None


class TestCandidateProperties:
    def test_sell_yes_risk_reward(self):
        cal = _sports_calibration_sell()
        ob = _ob(yes=[(0.80, 100)], no=[(0.19, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        # Risk = 1 - 0.80 = 0.20, Reward = 0.80 → ratio 4:1
        assert cand.reward_per_contract / cand.risk_per_contract == pytest.approx(4.0)

    def test_buy_yes_risk_reward(self):
        cal = _sports_calibration_buy()
        ob = _ob(yes=[(0.08, 100)], no=[(0.91, 50)])
        cand = evaluate_market(_mkt(), ob, cal, min_edge_pp=2.0)
        # Buy YES at 0.09: risk=0.09, reward=0.91 → ratio ~10.1:1
        assert cand.risk_per_contract == pytest.approx(0.09)
        assert cand.reward_per_contract == pytest.approx(0.91)


class _FakeClient:
    """Minimal client stub for scan() — records which tickers got orderbook calls."""

    def __init__(self, markets: list[Market], orderbook: Orderbook):
        self._markets = markets
        self._ob = orderbook
        self.orderbook_calls: list[str] = []

    def iter_markets(self, *, event_ticker: str | None = None, **_kwargs):
        for m in self._markets:
            if event_ticker is not None and m.event_ticker != event_ticker:
                continue
            yield m

    def iter_events(self, status: str = "open"):
        seen = set()
        for m in self._markets:
            if m.event_ticker and m.event_ticker not in seen:
                seen.add(m.event_ticker)
                yield {"event_ticker": m.event_ticker}

    def fetch_orderbook(self, ticker: str, depth: int = 1) -> Orderbook:
        self.orderbook_calls.append(ticker)
        return self._ob


class TestScanFilters:
    def test_skips_markets_with_no_bids_on_either_side(self):
        cal = _sports_calibration_sell()
        quoted = _mkt(ticker="Q", volume=100, yes_bid=0.82, no_bid=0.17)
        empty = _mkt(ticker="E", volume=100, yes_bid=None, no_bid=None)
        client = _FakeClient([quoted, empty], _ob(yes=[(0.82, 100)], no=[(0.17, 50)]))
        list(scan(client, cal, min_edge_pp=2.0))
        assert client.orderbook_calls == ["Q"]

    def test_one_sided_quote_still_fetched(self):
        cal = _sports_calibration_sell()
        yes_only = _mkt(ticker="YO", volume=100, yes_bid=0.82, no_bid=None)
        client = _FakeClient([yes_only], _ob(yes=[(0.82, 100)], no=[]))
        list(scan(client, cal, min_edge_pp=2.0))
        assert client.orderbook_calls == ["YO"]

    def test_event_first_skips_disallowed_categories(self):
        cal = _sports_calibration_sell()
        sport = _mkt(
            ticker="S",
            event_ticker="KXNFL-2026-A",
            volume=100,
            yes_bid=0.82,
            no_bid=0.17,
        )
        pol = _mkt(
            ticker="P",
            event_ticker="KXELONMARS-99",
            volume=100,
            yes_bid=0.82,
            no_bid=0.17,
        )
        client = _FakeClient([sport, pol], _ob(yes=[(0.82, 100)], no=[(0.17, 50)]))
        list(scan(client, cal, categories=("sports",), min_edge_pp=2.0))
        # Political event should never have been expanded to an orderbook call.
        assert client.orderbook_calls == ["S"]
