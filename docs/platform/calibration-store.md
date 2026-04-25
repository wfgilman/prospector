# Calibration Store

> Versioned on-disk snapshots of the calibration curves the paper-trade
> daemon reads at startup. The `current.json` pointer model.

---

## Layout

```
data/calibration/store/
├── current.json                            # Pointer file
├── calibration-2026-04-20T120000.json      # Versioned snapshots
├── calibration-2026-04-23T030500.json
└── ...
```

`current.json` contains a single field naming the active snapshot file.
Recalibration is a two-step process:

1. Build a new snapshot file (immutable once written)
2. Atomically swap the `current.json` pointer to it

Daemons load whatever `current.json` points to at startup. Hot-swap
behavior is **not** implemented — a running daemon keeps the calibration
it loaded; the next launchd tick (15 min later) picks up the new pointer.

This pattern means a botched calibration build can be reverted by
swapping the pointer back without rebuilding anything.

---

## Snapshot contents

Each calibration snapshot is a JSON file with:

```json
{
  "built_at": "2026-04-20T12:00:00+00:00",
  "data_window_start": "2021-06-30",
  "data_window_end": "2026-04-19",
  "min_volume": 10,
  "curves": {
    "sports": [{ "bin_low": 0, "bin_high": 5, "n": 1234, "yes_count": 67, ... }, ...],
    "crypto": [...],
    "aggregate": [...]
  }
}
```

One curve per category plus an `aggregate` fallback used when a
category-specific bin has insufficient data.

For the math behind how curves are built (PIT pricing, ASOF join, time-
offset filter, binning, Wilson CIs, fee-adjusted edge, signal detection),
see [`../components/calibration-curves.md`](../components/calibration-curves.md).

---

## How it's built

`scripts/refresh_calibration_store.py` reads the unified Kalshi tree at
`data/kalshi/`, runs the calibration pipeline, writes the snapshot file,
updates the pointer.

```bash
python scripts/refresh_calibration_store.py [--min-volume 10]
```

Cadence: monthly is a reasonable default. The system tolerates stale
calibration well — the curves don't decay quickly — but a monthly refresh
catches regime drift.

---

## What's adjacent but separate

- **σ-table** at `data/calibration/sigma_table.json` — built by
  `scripts/compute_sigma_table.py`. Same general pattern (immutable
  snapshot of empirical σ by bin) but lives outside the calibration store
  because it's regenerated on a different cadence and serves a different
  purpose. See [equal-σ sizing](../components/equal-sigma-sizing.md).
- **Walk-forward output** at `data/calibration/walk_forward_*.png` — visual
  artifacts from `scripts/walk_forward_backtest.py`. Reference, not used by
  any daemon.

---

## Module surface (Python)

```python
from prospector.strategies.pm_underwriting.calibration import (
    Calibration, CalibrationStore
)

store = CalibrationStore("data/calibration/store")
calibration = store.load_current()        # Calibration dataclass
bin = calibration.lookup("sports", 0.87)  # CalibrationBin or None
```

`Calibration.lookup(category, price)` returns the matching bin (with side,
actual_rate, n) or None if the category bin has insufficient data and the
aggregate fallback also doesn't qualify.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (Phase 3 launch) | Versioned-snapshot + pointer model | Atomic recalibration with rollback path; no hot-swap risk |
| 2026-04-25 | Doc consolidated into platform/ | Was scattered across calibration.py docstring + runbook + methodology |
