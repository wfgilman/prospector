#!/bin/bash
# launchd wrapper for the *insurance-slice* paper-trading book.
#
# Same daemon as the lottery book (`paper_trade.py`) but scoped to the
# 0.55-0.75 entry-price band and writing to a separate portfolio DB.
# Both books share the calibration store + σ-table; they differ only in
# (a) which slice of the price surface they trade and (b) where they
# log NAV / positions / shadow rejections.
#
# Each tick appends to a UTC-dated log file under
# data/paper/pm_underwriting_insurance/logs/, rotating naturally at
# midnight UTC. Failures leave a stack trace in the log; launchd will
# fire the next tick on schedule regardless.

set -u

REPO_DIR="/Users/wgilman/workspace/prospector"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/data/paper/pm_underwriting_insurance/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_trade-$(date -u +%Y%m%d).log"

exec .venv/bin/python scripts/paper_trade.py --once \
    --portfolio-db "$REPO_DIR/data/paper/pm_underwriting_insurance/portfolio.db" \
    --entry-price-min 0.55 \
    --entry-price-max 0.75 \
    --min-edge-pp 3.0 \
    >> "$LOG_FILE" 2>&1
