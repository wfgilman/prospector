# Shadow Rejection Ledger

> Append-only log of candidates rejected by structural screens (not
> portfolio constraints). Enables counterfactual replay — "what would the
> book look like if we hadn't applied this screen?"

**Status:** In production. Shipped 2026-04-23 alongside the 28d expiry screen.

---

## What it does

When the runner rejects a candidate for **structural reasons** (e.g.,
"resolution date is past the validation horizon"), the candidate's full
metadata is written to a parquet file rather than discarded. A later
script can replay the rejected candidates against a shadow portfolio to
compute the counterfactual book — the one we would have had without the
screen.

This is not the same as portfolio-constraint rejections (per-position cap,
per-event cap, etc.) which are working-as-intended caps and don't need
counterfactual replay. The ledger only catches *structural* rejections
that change the strategy's universe.

---

## Schema

`data/paper/<book>/shadow/shadow_rejections.parquet`:

| Column | Type | Notes |
|---|---|---|
| `ticker` | string | Market ticker |
| `event_ticker` | string | |
| `series_ticker` | string | |
| `category` | string | |
| `side` | string | sell_yes / buy_yes |
| `entry_price` | float | What we would have entered at |
| `edge_pp` | float | Fee-adjusted edge in pp |
| `sigma_bin` | float | σ that would have been used |
| `risk_budget` | float | Dollar risk the sizer would have assigned |
| `close_time` | timestamp | Market close time (the reason for rejection) |
| `entry_time` | timestamp | When we saw the candidate |
| `reject_reason` | string | E.g., `"expiry_gt_28d"` |

Deduped on `(ticker, reject_date)` — first-seen per day wins, so re-scans
of the same long-dated market don't bloat the file.

---

## Current screen — 28-day expiry

`RunnerConfig.max_days_to_close = 28` (default). Candidates whose
`close_time - now > 28 days` are shadow-rejected.

**Why:** A paper-trade validation run has a narrow signal horizon —
positions resolving 6+ months out return no information within the paper
window. They crowd out the book without contributing to validation.

**Counterfactual question:** If we lifted the 28-day screen and let
long-dated markets enter, would the resulting book outperform? The shadow
ledger lets us answer this empirically once enough rejections have
accumulated and resolved.

---

## Replay (script not yet built)

Expected: ~150 LOC. Reads the shadow parquet, instantiates a separate
`ShadowPaperPortfolio` with the same calibration/sizing as the live book,
walks the rejection rows in order, simulates entries against current
calibration + σ-table, simulates resolutions when each `close_time`
fires, reports the shadow book's NAV trajectory next to the live book's.

This is the basis for the "slow book" candidate ([T7 / candidate
10](../rd/candidates/10-slow-book-shadow-rejections.md)) — if the
counterfactual replay shows the long-dated rejections aggregate to a
positive book, that's empirical evidence to actually run them as a
parallel slow-cadence book rather than just shadow-log them.

---

## Implementation pointer

| File | Role |
|---|---|
| `src/prospector/strategies/pm_underwriting/shadow.py` | `ShadowRejection` dataclass + `write_rejections()` parquet writer |
| `src/prospector/strategies/pm_underwriting/runner.py` | Calls `write_rejections()` at end of each tick when rows accumulated |

---

## Where it's applied

- **PM Underwriting · Lottery** — yes, default 28d screen
- **PM Underwriting · Insurance** — yes, default 28d screen

The screen and ledger are orthogonal to entry-price band filtering — both
are RunnerConfig-level filters applied before the daily-cap entry loop.

---

## Trade-offs

**Why this works:** Reject without losing data. The screen serves the
short-term goal (paper validation horizon); the ledger serves the
long-term goal (we may want to know what we missed). Cheap to maintain —
parquet append, no new daemon.

**What it gives up:**
- **Replay isn't free.** The replay script needs to be built (~150 LOC)
  and the shadow-portfolio simulation needs to handle resolution events
  for long-dated markets that haven't resolved yet (means partial replay).
- **Calibration drift between rejection and replay.** A market rejected
  today and replayed in 6 months sees a different calibration curve —
  appropriate if we're answering "would today's calibration pick this?"
  but worth flagging when interpreting.
- **Only catches one class of rejection.** Portfolio constraints
  (per-position cap, daily cap) are working-as-intended and not logged.
  If we ever want to know "would more capital have changed the book?"
  that's a different counterfactual that needs different instrumentation.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-23 | Shadow ledger added with the 28-day expiry screen | The screen serves paper validation; the ledger preserves the rejected universe for later replay |
| 2026-04-23 | Dedup on `(ticker, reject_date)` | Re-scans of the same long-dated market would otherwise blow up the file |
| 2026-04-25 | Doc consolidated into components/ | Was inline in plan.md §expiry-screen + runner.py |
