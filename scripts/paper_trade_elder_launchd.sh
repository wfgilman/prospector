#!/bin/bash
# launchd wrapper for the elder triple-screen paper-trading daemon.
#
# Ticks at the 4h cadence aligned with the short_tf bar close. Each
# invocation refreshes Hyperliquid OHLCV for the cohort, sweeps open
# positions for stop/target hits, and opens new positions on fresh
# triple-screen signals at the just-printed bar.
#
# Logs land in data/paper/elder_triple_screen/logs/, rotated daily by
# UTC date. launchd fires the next tick regardless of any failure.

set -u

REPO_DIR="/Users/wgilman/workspace/prospector"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/data/paper/elder_triple_screen/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_trade-$(date -u +%Y%m%d).log"

exec .venv/bin/python scripts/paper_trade_elder.py --once >> "$LOG_FILE" 2>&1
