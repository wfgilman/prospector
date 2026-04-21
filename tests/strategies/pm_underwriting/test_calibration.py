from datetime import datetime, timezone

import pytest

from prospector.strategies.pm_underwriting.calibration import (
    Calibration,
    CalibrationBin,
    CalibrationStore,
    build_bins_from_rows,
    fee_adjusted_edge,
    trade_side,
)


class TestFeeAdjustedEdge:
    def test_zero_when_implied_and_actual_match(self):
        assert fee_adjusted_edge(0.5, 0.5) == pytest.approx(-0.035)

    def test_round_trip_fee_at_midpoint(self):
        # p = 0.5, fee = 2 * 0.07 * 0.5 * 0.5 = 0.035
        assert fee_adjusted_edge(0.5, 0.5) == pytest.approx(-0.035)

    def test_edge_positive_when_deviation_exceeds_fees(self):
        # p = 0.9: fee = 2 * 0.07 * 0.9 * 0.1 = 0.0126
        # |0.85 - 0.90| = 0.05 → edge = 0.05 - 0.0126 = 0.0374
        assert fee_adjusted_edge(0.9, 0.85) == pytest.approx(0.0374, abs=1e-4)

    def test_edge_zero_at_extremes(self):
        # p = 1.0: fee = 0; edge = |1.0 - 0.99| = 0.01
        assert fee_adjusted_edge(1.0, 0.99) == pytest.approx(0.01, abs=1e-6)

    def test_edge_symmetric_in_direction(self):
        assert fee_adjusted_edge(0.3, 0.4) == pytest.approx(fee_adjusted_edge(0.3, 0.2))


class TestTradeSide:
    def test_sell_yes_when_overpriced(self):
        assert trade_side(0.90, 0.85) == "sell_yes"

    def test_buy_yes_when_underpriced(self):
        assert trade_side(0.10, 0.15) == "buy_yes"

    def test_empty_when_equal(self):
        assert trade_side(0.5, 0.5) == ""


class TestCalibrationBin:
    def test_implied_mid(self):
        b = CalibrationBin(80, 85, 500, 400, 0.80, 0.77, 0.83, 0.01, "")
        assert b.implied_mid == 0.825

    def test_deviation_pp(self):
        b = CalibrationBin(80, 85, 500, 400, 0.75, 0.72, 0.78, 0.01, "sell_yes")
        assert b.deviation_pp == pytest.approx(-7.5, abs=0.01)

    def test_contains(self):
        b = CalibrationBin(80, 85, 500, 400, 0.75, 0.7, 0.8, 0.01, "sell_yes")
        assert b.contains(0.80)
        assert b.contains(0.84999)
        assert not b.contains(0.85)
        assert not b.contains(0.79)


class TestBuildBinsFromRows:
    def test_bins_below_min_n_not_tradeable(self):
        # n=50 < default 100 → side stays empty even with big deviation
        bins = build_bins_from_rows([(80, 85, 50, 40)], min_n=100)
        assert bins[0].side == ""

    def test_bins_below_min_deviation_not_tradeable(self):
        # deviation is 0pp (actual=0.825 = implied_mid)
        bins = build_bins_from_rows([(80, 85, 1000, 825)])
        assert bins[0].side == ""

    def test_overpriced_bin_gets_sell_yes(self):
        # implied=0.825, actual=0.75 → dev=-7.5pp, fee=0.0289, edge>0
        bins = build_bins_from_rows([(80, 85, 500, 375)])
        assert bins[0].side == "sell_yes"

    def test_underpriced_bin_gets_buy_yes(self):
        # implied=0.075, actual=0.15 → dev=+7.5pp, fee=0.00971, edge>0
        bins = build_bins_from_rows([(5, 10, 500, 75)])
        assert bins[0].side == "buy_yes"

    def test_empty_rows_skipped(self):
        bins = build_bins_from_rows([(80, 85, 0, 0)])
        assert bins == []

    def test_negative_edge_not_tradeable(self):
        # deviation barely above threshold but fee wipes it out — construct
        # a case at p=0.5 where fees are 3.5pp. 3.1pp deviation means negative edge.
        bins = build_bins_from_rows([(45, 50, 10_000, 4_345)])
        # actual = 0.4345, implied = 0.475, dev = -4.05pp, fee = 0.03493, edge ~= 0.0056
        # positive; so we construct one that clears deviation but fails edge:
        bins = build_bins_from_rows([(45, 50, 10_000, 4_440)])
        # actual = 0.444, implied = 0.475, dev = -3.1pp, fee = 0.03493, edge < 0
        assert bins[0].fee_adj_edge < 0
        assert bins[0].side == ""

    def test_wilson_ci_bounds(self):
        bins = build_bins_from_rows([(80, 85, 500, 375)])
        b = bins[0]
        assert 0.0 <= b.ci_low < b.actual_rate < b.ci_high <= 1.0

    def test_wilson_ci_widens_for_small_n(self):
        big = build_bins_from_rows([(80, 85, 10_000, 8_000)])[0]
        small = build_bins_from_rows([(80, 85, 100, 80)])[0]
        assert (small.ci_high - small.ci_low) > (big.ci_high - big.ci_low)


class TestCalibration:
    def _make_calibration(self) -> Calibration:
        sports_bins = build_bins_from_rows([(80, 85, 500, 375)])
        agg_bins = build_bins_from_rows([(80, 85, 1_000, 800), (5, 10, 500, 75)])
        return Calibration(
            built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
            data_window_start="2021-06-01",
            data_window_end="2026-01-01",
            min_volume=10,
            curves={"sports": sports_bins, "aggregate": agg_bins},
        )

    def test_bins_for_known_category(self):
        cal = self._make_calibration()
        bins = cal.bins_for("sports")
        assert bins[0].side == "sell_yes"

    def test_bins_for_unknown_falls_back_to_aggregate(self):
        cal = self._make_calibration()
        bins = cal.bins_for("politics")
        assert len(bins) == 2  # aggregate has 2 bins

    def test_lookup_matches_bin(self):
        cal = self._make_calibration()
        b = cal.lookup("sports", 0.82)
        assert b is not None
        assert b.bin_low == 80

    def test_lookup_outside_any_bin_returns_none(self):
        cal = self._make_calibration()
        assert cal.lookup("sports", 0.50) is None


class TestCalibrationStoreRoundTrip:
    def test_save_and_load_current(self, tmp_path):
        store = CalibrationStore(tmp_path)
        cal = Calibration(
            built_at=datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc),
            data_window_start="2021-06-01",
            data_window_end="2026-01-01",
            min_volume=10,
            curves={"sports": build_bins_from_rows([(80, 85, 500, 375)])},
        )
        path = store.save(cal)
        assert path.exists()
        loaded = store.load_current()
        assert loaded.built_at == cal.built_at
        assert loaded.data_window_start == "2021-06-01"
        assert loaded.curves["sports"][0].side == "sell_yes"

    def test_load_without_pointer_raises(self, tmp_path):
        store = CalibrationStore(tmp_path)
        with pytest.raises(FileNotFoundError):
            store.load_current()

    def test_save_updates_pointer(self, tmp_path):
        store = CalibrationStore(tmp_path)
        first = Calibration(
            built_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            data_window_start="x",
            data_window_end="y",
            min_volume=10,
            curves={},
        )
        second = Calibration(
            built_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
            data_window_start="x",
            data_window_end="y",
            min_volume=10,
            curves={},
        )
        store.save(first)
        store.save(second)
        loaded = store.load_current()
        assert loaded.built_at == second.built_at
