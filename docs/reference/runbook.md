# Runbook

> How to run scripts, install launchd jobs, recover from common failures.
> Operational reference, kept tight.

---

## Environment

```bash
source /Users/wgilman/workspace/prospector/.venv/bin/activate

PYTHONPATH=src pytest -q tests          # tests
ruff check src tests scripts             # lint
```

---

## Data layer

### Daily incremental cron

```bash
launchctl bootstrap gui/$UID scripts/launchd/com.prospector.data-incremental.plist
launchctl list | grep data-incremental
launchctl start com.prospector.data-incremental    # manual trigger
```

Pulls Kalshi incremental + Hyperliquid funding/OHLCV + Coinbase 1m
sequentially. Daily 03:00 local. Logs at
`data/incremental/logs/incremental-YYYYMMDD.log`.

See [`platform/data-pipeline.md`](../platform/data-pipeline.md) for
schema, retention map, gotchas.

### Manual backfills

```bash
PYTHONPATH=src python scripts/backfill_kalshi.py --series KXBTC FED --max-events 3 --verbose
PYTHONPATH=src python scripts/backfill_hyperliquid.py --verbose
python -m prospector.data.download_coinbase
```

### Calibration store rebuild

```bash
python scripts/refresh_calibration_store.py [--min-volume 10]
```

Writes new snapshot, swaps `current.json` pointer atomically. See
[`platform/calibration-store.md`](../platform/calibration-store.md).

### σ-table rebuild

```bash
python scripts/compute_sigma_table.py
```

Output: `data/calibration/sigma_table.json`. See [`components/equal-sigma-sizing.md`](../components/equal-sigma-sizing.md).

---

## Paper trading

### One-shot tick (smoke test)

```bash
python scripts/paper_trade.py --once                         # lottery book
python scripts/paper_trade.py --once \                       # insurance book
    --portfolio-db data/paper/pm_underwriting_insurance/portfolio.db \
    --entry-price-min 0.55 --entry-price-max 0.75 --min-edge-pp 3.0
```

Both PM books default to a 6-24h time-to-close window
(`--min-hours-to-close=6 --max-hours-to-close=24`); markets outside
this window are written to the shadow ledger as `ttc_lt_6h` /
`ttc_gt_24h` rather than entered. The window aligns the daemon with
the calibration's PIT-mid-life sampling distribution. See
[`../components/calibration-curves.md`](../components/calibration-curves.md)
"Implicit mid-life state-conditioning."

### Foreground daemon

```bash
python scripts/paper_trade.py --interval 900
```

### Production (launchd, 15-min cadence)

**Lottery book:**
```bash
cp scripts/launchd/com.prospector.paper-trade.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.prospector.paper-trade.plist
launchctl list | grep paper-trade
launchctl start com.prospector.paper-trade
tail -f data/paper/pm_underwriting/logs/paper_trade-$(date -u +%Y%m%d).log
```

**Insurance book:**
```bash
cp scripts/launchd/com.prospector.paper-trade-insurance.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.prospector.paper-trade-insurance.plist
launchctl list | grep paper-trade-insurance
tail -f data/paper/pm_underwriting_insurance/logs/paper_trade-$(date -u +%Y%m%d).log
```

**Elder triple-screen book** (4h cadence, candidate 16):
```bash
# manual one-shot
PYTHONPATH=src python scripts/paper_trade_elder.py --once

# foreground loop
PYTHONPATH=src python scripts/paper_trade_elder.py --interval 14400

# launchd
cp scripts/launchd/com.prospector.paper-trade-elder.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.prospector.paper-trade-elder.plist
launchctl list | grep paper-trade-elder
tail -f data/paper/elder_triple_screen/logs/paper_trade-$(date -u +%Y%m%d).log
```

The elder daemon refreshes Hyperliquid OHLCV at each tick, sweeps
open positions for stop/target hits, and opens new positions when the
locked triple-screen config (`slow_ema=15, fast_ema=5, RSI ≥ 93.7`)
fires on the just-printed 4h bar. Funding cost integrates from the
hourly funding-rate history at close time. See
[`docs/rd/candidates/16-triple-screen-midvol-crypto.md`](../rd/candidates/16-triple-screen-midvol-crypto.md).

Full daemon CLI surface in [`platform/paper-trade-daemon.md`](../platform/paper-trade-daemon.md).

### Stop a book

```bash
launchctl unload ~/Library/LaunchAgents/com.prospector.paper-trade-insurance.plist
```

The other book continues unaffected. Books are independent at the
launchd, portfolio-DB, and log-file levels.

---

## CLV scoring

```bash
python scripts/compute_clv.py                            # all positions, default lottery DB
python scripts/compute_clv.py --status closed            # closed only
python scripts/compute_clv.py --out clv-readout.parquet  # save per-trade
python scripts/compute_clv.py --db data/paper/pm_underwriting_insurance/portfolio.db
```

See [`components/clv-instrumentation.md`](../components/clv-instrumentation.md)
for math and interpretation.

---

## Dashboard

```bash
pip install -e .[dashboard]              # one-time
streamlit run scripts/dashboard.py        # localhost:8501

# Override manifest for smoke-testing
PROSPECTOR_MANIFEST=/tmp/test_manifest.toml streamlit run scripts/dashboard.py
```

Layout: single strategy → direct render; 2+ → top-level tabs with
"Compare" first. See [`platform/dashboard.md`](../platform/dashboard.md).

---

## Common failure modes

### "Kalshi API key not provided"

The user owns `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` in `.env`.
Agents do not read or write `.env`. If the env is missing for a
launchd-driven daemon, check the wrapper script's `cd` + venv activation.

### "Schema mismatch reading parquet"

Likely a partial backfill wrote with an older schema. Cause: a partition
written before a `Market` dataclass field addition. Fix: re-pull or
schema-retrofit the partition. See [`platform/data-pipeline.md`](../platform/data-pipeline.md)
§12.4 for the canonical fix-up pattern.

### "Daemon ticks but no entries"

Most likely the calibration store is empty or out of date. Check
`data/calibration/store/current.json` exists and points at a recent
snapshot. Rebuild if needed (see above).

Also check: `daily trade cap reached; skipping scan` in the log → cap
already hit for the day; not a bug.

### "Insurance daemon DB not found"

The DB is created on first tick. If the daemon hasn't ticked yet (15-min
cadence + `RunAtLoad: false`), wait or manually trigger via `launchctl
start`.

### "Tests pass locally but launchd shows non-zero exit"

Wrapper script likely has a path issue or missing venv activation. Check
`data/paper/pm_underwriting/logs/launchd.log` — bootstrap failures land
there.

---

## Backups (informal)

The user's machine is always-on per [`charter/operational-limits.md`](../charter/operational-limits.md).
There's no formal backup of the paper portfolio DBs; if the machine fails:

- The Kalshi data tree (`data/kalshi/`) is reproducible from the API
  (~hours of wall time to re-pull) plus the TrevorJS HF source
- The portfolio DBs (`data/paper/<book>/portfolio.db`) are NOT
  reproducible — they are the live state of paper experiments
- The git repo holds all code + docs; everything else is gitignored

A formal backup story is a Phase 4 prerequisite (when live capital lives
in real exchange accounts, not local SQLite).

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Runbook reorganized to track docs reorg | Pointers updated to new platform/ + components/ locations; obsolete sections removed |
| 2026-04-28 | Elder triple-screen daemon section added | Candidate 16 advanced to paper-portfolio; new daemon, plist, log location, OHLCV-refresh-on-tick semantics that differ from the PM books |
