# Dashboard

> Streamlit dashboard for paper-trading strategies. Manifest-driven,
> multi-strategy, with a comparison tab when 2+ books are enabled.

**Status:** In production. Two-book layout (Lottery + Insurance) live as
of 2026-04-25.

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

For each Kalshi-binary book:

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
```

Paths are resolved relative to the manifest. `enabled = false` hides a
strategy without deleting it (useful for archived books).

---

## Adding a new schema

The renderer dispatches by `schema`. Today only `kalshi_binary` exists.
Adding a new schema (e.g., `crypto_perp` for a future Hyperliquid book):

1. Add `crypto_perp` to `SUPPORTED_SCHEMAS` in `src/prospector/manifest.py`
2. Add `_render_crypto_perp(entry)` to `src/prospector/dashboard.py`
3. Add the dispatch in `render_strategy()`
4. Add a manifest entry with `schema = "crypto_perp"`

The Compare tab works across schemas as long as each schema's loaders
return the same `PortfolioSummary` shape (NAV, locked_risk, open_positions,
realized_pnl, etc.).

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
`build_pnl_series`, `load_tick_history`) are pure — no Streamlit imports —
so they're unit-testable. Renderers (`_render_stat_card`, etc.) are
Streamlit-coupled.

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
