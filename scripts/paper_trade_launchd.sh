#!/bin/bash
# launchd wrapper for the paper-trading daemon.
#
# Each tick appends to a UTC-dated log file under data/paper/logs/, so logs
# rotate naturally at midnight UTC without a separate logrotate process.
# Ticks that fail (Kalshi outage, bad creds, etc.) leave a stack trace in
# the log; launchd will fire the next tick on schedule regardless.

set -u

REPO_DIR="/Users/wgilman/workspace/prospector"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/data/paper/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/paper_trade-$(date -u +%Y%m%d).log"

exec .venv/bin/python scripts/paper_trade.py --once >> "$LOG_FILE" 2>&1
