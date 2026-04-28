# Dashboard

> Streamlit dashboard for paper-trading strategies. Manifest-driven,
> multi-strategy, with a comparison tab when 2+ books are enabled.

**Status:** In production. Three books live: Lottery + Insurance (both
`kalshi_binary` schema, 2026-04-25) and Elder Triple-Screen vol_q4 perps
(`crypto_perp` schema, 2026-04-28). Renderer dispatches by schema so each
book gets a layout matching its position model.

---

## What it shows

When run with `streamlit run scripts/dashboard.py`:

- **One strategy** — direct render, no tab chrome
- **Two or more strategies** — top-level tabs:
  - **Compare** (first tab): side-by-side stat cards, overlaid cumulative-P&L
    chart, KPI delta table
  - **Per-strategy** tabs: each book's full single-strategy view

Strategies whose portfolio DB doesn't exist yet (e.g., a freshly-loaded
daemon that hasn't ticked) render as "awaiting first tick" placeholder
cards rather than crashing the column.

---

## Per-strategy view

For each `kalshi_binary` book (Lottery, Insurance):

- **Stat card** — NAV, Δ from seed, ROI%, realized P&L, locked risk
  ($+%), open positions, trades today, last-tick timestamp
- **P&L trajectory** — area chart with positive/negative coloring;
  zero-rule overlay; renders after first resolution
- **By-category sections** — per-category open count, locked risk, upside,
  avg edge, win/loss record, realized P&L
- **Tabs** within the per-strategy view:
  - Open positions (with hours-to-expiry)
  - Closed positions (with realized P&L, market_result)
  - Recent ticks (last 20 from the log)

For the `crypto_perp` book (Elder Triple-Screen):

- **Stat card** — same shape as kalshi (NAV / Δ / ROI / open / today /
  last-tick), but "Realized P&L" reads `net_pnl` (gross − fees − funding)
- **Net P&L trajectory** — area chart over `exit_time`; replaces the
  by-category section since perps don't have a category dimension
- **Tabs** within the per-strategy view:
  - Open positions (coin, direction, units, entry/stop/target, risk,
    entry_time)
  - Closed positions (coin, direction, units, exit_reason, gross_pnl,
    fees_paid, funding_cost, net_pnl) with a header summary including
    total fees and net funding
  - Recent ticks (parses both `tick:` and `once:` log lines emitted by
    the elder daemon)

---

## Manifest

`data/paper/manifest.toml` is the discovery index. Daemons don't consult
it — they only know their own DB. The dashboard reads it.

```toml
[[strategy]]
name = "pm_underwriting"
display_name = "PM Underwriting · Lottery (0.85-1.0)"
schema = "kalshi_binary"
portfolio_db = "pm_underwriting/portfolio.db"
log_dir = "pm_underwriting/logs"
launchd_label = "com.prospector.paper-trade"
enabled = true

[[strategy]]
name = "pm_underwriting_insurance"
display_name = "PM Underwriting · Insurance (0.55-0.75)"
schema = "kalshi_binary"
portfolio_db = "pm_underwriting_insurance/portfolio.db"
log_dir = "pm_underwriting_insurance/logs"
launchd_label = "com.prospector.paper-trade-insurance"
enabled = true

[[strategy]]
name = "elder_triple_screen"
display_name = "Elder Triple-Screen · vol_q4 perps"
schema = "crypto_perp"
portfolio_db = "elder_triple_screen/portfolio.db"
log_dir = "elder_triple_screen/logs"
launchd_label = "com.prospector.paper-trade-elder"
enabled = true
```

Paths are resolved relative to the manifest. `enabled = false` hides a
strategy without deleting it (useful for archived books).

---

## Adding a new schema

The renderer dispatches by `schema`. Two are wired today: `kalshi_binary`
(PM books) and `crypto_perp` (elder triple-screen). Adding a third:

1. Add the schema name to `SUPPORTED_SCHEMAS` in `src/prospector/manifest.py`
2. Add per-schema loaders to `src/prospector/dashboard.py` that return the
   same `PortfolioSummary` shape — see `_load_summary_elder` /
   `_pnl_series_elder` for the pattern
3. Extend the `summary_for(entry)` and `pnl_series_for(entry)`
   dispatchers to route the new schema. These power the Compare tab
4. Add `_render_<schema>(entry)` and wire it into `render_strategy()`
5. Add a manifest entry with the new `schema = ...`

The Compare tab works across schemas as long as `summary_for` and
`pnl_series_for` know how to read every schema in the manifest.

---

## Theme

A "quant-terminal" aesthetic: dark charcoal background, Fraunces serif
display, JetBrains Mono for numbers (tabular), Geist sans for body. Color
palette is centrally defined in `_PALETTE` so retheming is a three-line
change.

CSS is injected once per Streamlit rerun via `inject_theme()`. Altair
charts use a registered theme matching the page palette.

---

## Module layout

```
scripts/dashboard.py        # Streamlit entry; routes to render_strategy / render_comparison
src/prospector/
├── dashboard.py            # Loaders + theme + renderers
└── manifest.py             # StrategyEntry + load_manifest
```

Loaders (`load_portfolio_summary`, `load_positions`, `load_category_breakdown`,
`build_pnl_series`, `load_tick_history` for kalshi; `_load_summary_elder`,
`_pnl_series_elder`, `_load_positions_elder`, `load_elder_tick_history`
for crypto_perp; plus the `summary_for` / `pnl_series_for` schema
dispatchers used by Compare) are pure — no Streamlit imports — so
they're unit-testable. Renderers (`_render_stat_card`,
`_render_stat_card_elder`, etc.) are Streamlit-coupled.

---

## Running

```bash
pip install -e .[dashboard]              # one-time
streamlit run scripts/dashboard.py        # runs at http://localhost:8501
```

Override the manifest path for smoke-testing against a copy of the
production DB:

```bash
PROSPECTOR_MANIFEST=/tmp/test_manifest.toml streamlit run scripts/dashboard.py
```

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (early) | Manifest-driven multi-strategy dashboard | Decouples discovery from execution; daemons don't need to know about each other |
| 2026-04-25 | Comparison tab + per-strategy tabs | Insurance book launch; tabs needed for side-by-side without losing per-book detail |
| 2026-04-25 | Empty-DB placeholder card | Insurance book launches with no DB yet; placeholder keeps column layout stable |
| 2026-04-25 | Doc consolidated into platform/ | Was inline in dashboard.py docstring and runbook |
| 2026-04-28 | `crypto_perp` schema added; Elder Triple-Screen tab live | Candidate 16 advanced to paper-portfolio; needed schema-aware dispatch since the elder schema uses `net_pnl` / `exit_time` and lacks categories. Compare tab now overlays all three books. |
