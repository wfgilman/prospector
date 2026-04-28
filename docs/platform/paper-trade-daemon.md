# Paper-Trade Daemon

> `scripts/paper_trade.py` — the single runner that powers every PM
> Underwriting paper book. Multi-book by parametrization, not by fork.

**Status:** Two PM Underwriting books in production via this daemon:
Lottery (full price range) and Insurance (0.55-0.75 entry-price band).
Both share calibration store and σ-table; books are independent at the
portfolio-DB level.

The Elder Triple-Screen perp book (candidate 16) runs as a *separate*
daemon — `scripts/paper_trade_elder.py` — because its position schema
(`crypto_perp`), execution venue (Hyperliquid), and signal model
(triple-screen on 1d/4h bars) all differ. See
[`../rd/candidates/16-triple-screen-midvol-crypto.md`](../rd/candidates/16-triple-screen-midvol-crypto.md)
and the `Elder triple-screen book` section of
[`../reference/runbook.md`](../reference/runbook.md).

---

## What it does

Once per tick (default 15-min cadence under launchd):

1. **Sweep** open positions: re-fetch each market, resolve settled ones,
   void cancelled ones, leave still-open ones in place. Records a CLV
   snapshot per fetched market for [CLV instrumentation](../components/clv-instrumentation.md).
2. **Scan** active markets: for each market in the configured categories,
   evaluate against the [calibration curve](../components/calibration-curves.md) and emit candidates whose
   fee-adjusted edge clears the floor.
3. **Rank + size** candidates by `edge_pp / σ_bin` (bin-level Sharpe
   proxy); compute risk_budget via [equal-σ sizing](../components/equal-sigma-sizing.md).
4. **Filter + enter** until the daily cap is hit, respecting per-position,
   per-event, per-bin, per-subseries, per-series caps. Reject candidates
   outside the entry-price band ([component](../components/calibration-curves.md) §entry-price filter).
5. **Snapshot** the daily NAV / cash / locked-risk / position-count.

---

## Multi-book pattern

A "book" is just a different invocation of `paper_trade.py` with:

- A separate `--portfolio-db` path
- A different `--entry-price-min` / `--entry-price-max` band (or other
  parametric scope)
- A different launchd plist + wrapper script

Two PM Underwriting books currently:

| Book | DB path | Band | Min edge | Wrapper | Plist |
|---|---|---|---|---|---|
| **Lottery** | `data/paper/pm_underwriting/portfolio.db` | 0.0-1.0 (no filter) | 5pp | `scripts/paper_trade_launchd.sh` | `com.prospector.paper-trade` |
| **Insurance** | `data/paper/pm_underwriting_insurance/portfolio.db` | 0.55-0.75 | 3pp | `scripts/paper_trade_insurance_launchd.sh` | `com.prospector.paper-trade-insurance` |

Adding a third book is a 30-min exercise: copy the wrapper + plist, change
DB path + filter args, register in `data/paper/manifest.toml`. No code
changes.

The lottery + insurance books test different slices of the same calibration
surface — the lottery picks 85-99¢ extremes (where edge/σ pulls naturally),
the insurance pins 55-75¢ where the original "underwriting" thesis applies.

---

## CLI surface

```bash
python scripts/paper_trade.py --once    # one tick (recommended under launchd)
python scripts/paper_trade.py --interval 900    # foreground daemon

# Multi-book parametrization
python scripts/paper_trade.py --once \
    --portfolio-db data/paper/pm_underwriting_insurance/portfolio.db \
    --entry-price-min 0.55 --entry-price-max 0.75 \
    --min-edge-pp 3.0
```

All knobs:

| Flag | Default | Purpose |
|---|---|---|
| `--once` | (off) | Run one tick and exit (use under launchd) |
| `--interval` | 900 | Seconds between ticks (foreground mode) |
| `--portfolio-db` | `data/paper/pm_underwriting/portfolio.db` | Where this book's positions live |
| `--calibration-dir` | `data/calibration/store` | Where to load the current calibration snapshot from |
| `--sigma-table` | `data/calibration/sigma_table.json` | σ lookup |
| `--initial-nav` | 10000.0 | First-run seed; ignored on subsequent runs |
| `--book-sigma-target` | 0.02 | Target daily σ as fraction of NAV |
| `--n-target` | 150 | Target concurrent independent positions |
| `--max-position-frac` | 0.01 | Per-position safety net |
| `--max-event-frac` | 0.05 | Per-event-ticker correlation cap |
| `--max-bin-frac` | 0.15 | Per (side, 5¢ bin) concentration cap |
| `--max-trades-per-day` | 20 | Daily throughput cap |
| `--min-edge-pp` | 5.0 | Fee-adjusted edge floor |
| `--max-days-to-close` | 28 | Reject markets resolving more than N days out (logged to shadow ledger); 0 to disable |
| `--categories` | `sports crypto` | Filter to these; pass `all` to disable |
| `--entry-price-min` | 0.0 | Lower bound on entry price (insurance book uses 0.55) |
| `--entry-price-max` | 1.0 | Upper bound on entry price (insurance book uses 0.75) |

---

## Module layout

```
src/prospector/strategies/pm_underwriting/
├── runner.py        # The orchestration loop (run_once, run_forever, RunnerConfig)
├── scanner.py       # Walks active events, computes edge, emits Candidates
├── monitor.py       # Sweeps open positions, resolves/voids
├── portfolio.py     # SQLite-backed paper book (positions, snapshots, CLV table)
├── calibration.py   # Calibration store + curve lookup
├── categorize.py    # event_ticker → category
├── shadow.py        # Shadow-rejection ledger writer
└── sizing.py        # σ-table loader
```

`scripts/paper_trade.py` is the entry point; it parses CLI, wires
dependencies, and calls `runner.run_once()` or `run_forever()`.

---

## launchd integration

Each book has a plist at `scripts/launchd/` and a shell wrapper at
`scripts/`. The plist references the wrapper; the wrapper sources the venv,
sets `PYTHONPATH`, and invokes `python scripts/paper_trade.py --once` with
the book-specific flags.

Logs rotate naturally at UTC midnight via the wrapper:

```bash
LOG_FILE="$LOG_DIR/paper_trade-$(date -u +%Y%m%d).log"
exec .venv/bin/python scripts/paper_trade.py --once >> "$LOG_FILE" 2>&1
```

`StartInterval: 900` + `RunAtLoad: false` means the first tick fires 15 min
after launchctl load (avoids duplicating a manual run).

To install / refresh / tail:

```bash
cp scripts/launchd/com.prospector.paper-trade.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.prospector.paper-trade.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.prospector.paper-trade.plist

launchctl list | grep paper-trade            # status
launchctl start com.prospector.paper-trade   # manual tick
tail -f data/paper/pm_underwriting/logs/paper_trade-$(date -u +%Y%m%d).log
```

---

## Constraint hierarchy at entry

Applied in order at portfolio.enter(); first failing check rejects with a
reason logged. Other candidates in the tick still get their turn.

1. Per-position $ cap (`max_position_frac`)
2. Available cash (hard budget)
3. Per-event $ cap (`max_event_frac`)
4. Per-bin $ cap (`max_bin_frac`) — finest grain, replaces retired
   `max_category_frac`
5. Per-event count (`max_positions_per_event = 1`)
6. Per-subseries count (`max_positions_per_subseries = 1`)
7. Per-series count (`max_positions_per_series = 3`)
8. Daily trade cap (`max_trades_per_day`)
9. No duplicate open ticker

The runner additionally applies the entry-price-band filter (RunnerConfig
level) and the expiry screen (markets resolving > `max_days_to_close` out
get logged to the [shadow rejection ledger](../components/shadow-rejection-ledger.md) instead).

---

## Operational notes

- **Fees.** Live book charges round-trip `0.14 × P × (1-P) × contracts` at
  entry and deducts at resolution — models paper execution as conservatively
  taker-priced; a maker fill in production would refund.
- **Voided markets.** Some Kalshi markets finalize without a binary
  outcome. Monitor treats these as zero-P&L closures and refunds risk + fees.
  Idempotent.
- **Schema migrations.** New columns added to `positions` use `ALTER TABLE`
  in `_apply_migrations()` so existing live DBs upgrade in place. The
  `clv_snapshots` table is `CREATE IF NOT EXISTS` so existing books pick it
  up at next startup.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-20 | Phase 3 paper book launched | Walk-forward Sharpe 7.44; ready for live calibration validation |
| 2026-04-21 | Switched from fractional Kelly to equal-σ sizing | Per-bet σ varies 30× across bins; Kelly under-sized by 4-14× |
| 2026-04-23 | Expiry screen + shadow ledger added | Markets resolving > 28 days don't return signal in time to validate |
| 2026-04-24 | CLV snapshot capture wired into monitor | Faster edge-validation signal than realized P&L at 4-day horizon |
| 2026-04-25 | Insurance book launched | Same daemon, parametrized to 0.55-0.75 band; tests the original "underwriting" thesis on appropriate bins |
| 2026-04-25 | Doc consolidated into platform/ from prior implementation/plan.md | Reorg: this is the daemon's documentation, not a one-time implementation plan |
