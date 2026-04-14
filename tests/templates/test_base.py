"""Tests for Signal validation and base types."""

import pytest
from prospector.templates.base import Direction, Signal, MIN_REWARD_RISK


def test_long_signal_valid():
    sig = Signal(bar_index=5, direction=Direction.LONG,
                 entry=100.0, stop=95.0, target=115.0)
    assert sig.risk == pytest.approx(5.0)
    assert sig.reward == pytest.approx(15.0)
    assert sig.reward_risk_ratio == pytest.approx(3.0)


def test_short_signal_valid():
    sig = Signal(bar_index=5, direction=Direction.SHORT,
                 entry=100.0, stop=105.0, target=85.0)
    assert sig.risk == pytest.approx(5.0)
    assert sig.reward == pytest.approx(15.0)
    assert sig.reward_risk_ratio == pytest.approx(3.0)


def test_long_signal_bad_geometry():
    with pytest.raises(ValueError, match="stop < entry < target"):
        Signal(bar_index=0, direction=Direction.LONG,
               entry=100.0, stop=110.0, target=120.0)  # stop > entry


def test_short_signal_bad_geometry():
    with pytest.raises(ValueError, match="target < entry < stop"):
        Signal(bar_index=0, direction=Direction.SHORT,
               entry=100.0, stop=90.0, target=85.0)  # stop < entry


def test_signal_zero_price():
    with pytest.raises(ValueError, match="positive"):
        Signal(bar_index=0, direction=Direction.LONG,
               entry=0.0, stop=-5.0, target=10.0)


def test_min_reward_risk_constant():
    assert MIN_REWARD_RISK == 2.0
