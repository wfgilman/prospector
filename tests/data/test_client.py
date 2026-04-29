"""Tests for the Hyperliquid client coin-name normalization.

The elder triple-screen runner stores parquet files under underscore-
suffixed names (`BIGTIME_PERP`) and passes them straight to
`download_pair`. Without underscore-suffix stripping, the names reach
the Hyperliquid `/info` endpoint literally and the endpoint returns
HTTP 500 — which the runner catches as a warning and continues,
silently leaving OHLCV stale.
"""

from prospector.data.client import _coin


def test_coin_strips_dash_perp_suffix():
    assert _coin("BTC-PERP") == "BTC"


def test_coin_strips_underscore_perp_suffix():
    assert _coin("BIGTIME_PERP") == "BIGTIME"


def test_coin_passes_through_bare_symbol():
    assert _coin("BTC") == "BTC"


def test_coin_handles_kprefix_with_underscore():
    """`kPEPE_PERP` (Hyperliquid's k-shifted PEPE) must keep the lowercase k."""
    assert _coin("kPEPE_PERP") == "kPEPE"
