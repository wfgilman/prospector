#!/bin/bash
# launchd wrapper for the daily data-incremental pulls.
#
# Runs two idempotent pulls sequentially:
#   1. Kalshi incremental — appends trades since per-ticker watermark for
#      all configured series (KXBTC, KXFED, KXMVENFL, etc.)
#   2. Hyperliquid incremental — appends funding ticks + 1m/1h/1d candles
#      since last stored timestamp for BTC/ETH/SOL
#
# Both scripts are idempotent: re-running doesn't duplicate data, and a
# crash during the Hyperliquid step leaves the Kalshi output intact.
# Logs rotate daily under data/incremental/logs/ by UTC date.

set -u

REPO_DIR="/Users/wgilman/workspace/prospector"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/data/incremental/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/incremental-$(date -u +%Y%m%d).log"

{
    echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) starting incremental run ==="

    echo "--- kalshi incremental ---"
    .venv/bin/python scripts/pull_kalshi_incremental.py --verbose
    kalshi_rc=$?
    echo "kalshi exit $kalshi_rc"

    echo "--- hyperliquid incremental ---"
    .venv/bin/python scripts/backfill_hyperliquid.py --verbose
    hl_rc=$?
    echo "hyperliquid exit $hl_rc"

    # Coinbase is the only US-accessible source of historical 1m BTC/ETH
    # (Binance global blocks US IPs, Hyperliquid's 1m retention is only
    # ~3 days). Running daily keeps 1m flowing forward for #4-style studies.
    echo "--- coinbase incremental (1m BTC-USD, ETH-USD) ---"
    .venv/bin/python -m prospector.data.download_coinbase \
        --products BTC-USD ETH-USD --granularity 60
    cb_rc=$?
    echo "coinbase exit $cb_rc"

    echo "=== done ==="
} >> "$LOG_FILE" 2>&1
