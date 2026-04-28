# CLV (Closing-Line Value) Instrumentation

> Per-trade signed gap between entry price and the market's closing line.
> A faster edge signal than realized P&L for low-WR / high-payoff books.

**Status:** In production. Shipped 2026-04-24.

---

## What it does

Sports sharps at Pinnacle use CLV — the difference between entry price
and the market's closing price — as a leading indicator of edge. Decades
of validation. Translated to Kalshi:

- For each closed (or open) paper position, find the market's last
  bid/ask snapshot before resolution
- Compute the signed CLV: positive = we beat the closing line, negative =
  we got worse pricing than the market settled at
- Aggregate by side, category, price bin, status

Why this matters for our paper book: the lottery book entered at 9:1
payoffs has a 29% expected WR. Realized P&L stabilizes at N ~ thousands
of trades. CLV is a price-based statistic and stabilizes at N ~ hundreds.
**~10× faster signal**.

---

## Math

```
sell_yes entered at p:  CLV_pp = (p - closing_line) × 100
buy_yes  entered at p:  CLV_pp = (closing_line - p) × 100
```

Both normalize to "positive = we beat the line."

`closing_line` = mid of the latest bid/ask snapshot at-or-before the
position's `close_time` (resolved positions) or `as_of_time` (open
positions). Falls back to `last_price` when bid/ask aren't both populated.

---

## The snapshot table

The monitor writes one row per market fetch into a `clv_snapshots` table
on the paper portfolio:

```sql
CREATE TABLE clv_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    yes_bid REAL,
    yes_ask REAL,
    last_price REAL,
    market_status TEXT
);
CREATE INDEX idx_clv_ticker_time ON clv_snapshots(ticker, snapshot_time);
```

Cheap (single insert per fetch) and append-only. The monitor already
fetches every open market every tick, so coverage grows ~19/tick on a
typical lottery book.

The CLV scoring script also falls back to the unified Kalshi trade tree
(`data/kalshi/trades/`) for positions whose tickers happen to have trades
in our partitioned data. The trade tree is sparse for thin sports prop
markets, which is why the snapshot table is the primary source.

---

## Implementation pointer

| File | Role |
|---|---|
| `src/prospector/strategies/pm_underwriting/portfolio.py` | `clv_snapshots` table schema + `record_clv_snapshot()` method |
| `src/prospector/strategies/pm_underwriting/monitor.py` | `sweep()` writes one snapshot per market fetch |
| `scripts/compute_clv.py` | CLV scoring script (snapshot primary, trade-tree fallback); stdout report + optional parquet output |

---

## Where it's applied

- **PM Underwriting · Lottery** — every monitor tick records snapshots
- **PM Underwriting · Insurance** — same daemon, same monitor, same
  snapshot capture (effective at first tick)

The component is opt-in by being a table on the paper portfolio. Any
future kalshi_binary book gets it for free.

---

## Reading the output

`python scripts/compute_clv.py` reports:

- **Aggregate** — n scored, mean, median, σ in pp, beat-line rate
- **By status** — open vs. closed (open uses current snapshot as
  closing line; closed uses last snapshot before resolution)
- **By side** — sell_yes vs. buy_yes (current book is sell_yes-heavy)
- **By category** — sports / crypto / etc.
- **By 5¢ entry-price bin** — where CLV is best/worst
- **`corr(edge_pp, clv_pp)`** — ideal: strongly positive (high-edge picks
  beat the line more often)

First-run reading on the live paper book (2026-04-24):

```
Open-book median CLV  −2.5pp     beat-line  24%
edge_pp / clv_pp corr +0.144     n_scoreable 28
```

T+72h delta read (2026-04-27):

```
Open-book median CLV  −2.5pp     beat-line  24%   (unchanged)
Aggregate median      −0.50pp    beat-line  22.4%
Closed subset         median +0.00pp / mean +3.64pp (n=42)
edge_pp / clv_pp corr +0.056     n_scoreable 67
85-90¢ bin worst      median −6.50pp / 22.9% beat
```

The open-subset CLV regime is persistent, not transient. The
scanner-edge correlation is decaying toward noise (+0.144 → +0.056); at
this N still inside variance, but it is the metric to track against the
Phase-4 gate. The scanner's `edge_pp` is at best a noisy CLV proxy.

---

## Trade-offs

**Why this works:** Price-based statistic; stabilizes at N ~ hundreds vs.
realized P&L's N ~ thousands. Catches scanner mis-selection 10× faster.
Zero risk to the live book — snapshots are append-only, separate from
positions.

**What it gives up:**
- **Coverage depends on the monitor.** The snapshot table populates
  forward in time only; positions entered before CLV instrumentation
  shipped have only the trade-tree fallback (sparse for thin markets).
- **CLV itself is a forecast.** Beating the closing line doesn't
  guarantee positive realized P&L — but over enough trades, CLV-positive
  books realize positive P&L. The relationship is statistical, not
  deterministic.
- **Closing-line definition is flexible.** "Last bid/ask before
  resolution" works for sports props that resolve when a game ends; it's
  less obvious for markets that resolve via slow settlement. Worth
  refining if a strategy proposes a more nuanced definition.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-24 | T3 ranked first priority in fresh-eyes review | Lowest effort, highest leverage; cuts effective Phase-3 validation horizon ~10× |
| 2026-04-24 | Snapshot capture wired into monitor (not a separate cron) | Piggybacks on the monitor's per-position fetch; no new daemon, no new API quota |
| 2026-04-24 | Trade-tree fallback for tickers with sparse coverage | First-pass scoring reads any available source |
| 2026-04-25 | Doc consolidated into components/ | Was inline in compute_clv.py docstring + fresh-eyes-review doc |
| 2026-04-27 | T+72h delta read added (n=67) | Open-subset CLV regime stable at first-run levels; scanner edge↔CLV correlation decaying toward noise — promotes the MVT rolling-threshold component as the natural next implementation if the trend persists |
