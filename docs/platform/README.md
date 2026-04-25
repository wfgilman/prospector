# Platform

> Infrastructure that enables everything else. One file per platform piece.

The platform is the substrate strategies run on: data ingestion, paper-trade
execution, accounting, monitoring. Strategies and components depend on the
platform; the platform depends on nothing project-specific.

## Documents

| File | What it covers |
|---|---|
| [`data-pipeline.md`](data-pipeline.md) | The unified Kalshi + Hyperliquid + Coinbase data tree, daily incremental cron, retention model, validation discipline. |
| [`paper-trade-daemon.md`](paper-trade-daemon.md) | `paper_trade.py` runner architecture, scan/sweep/enter loop, launchd integration, multi-book pattern. |
| [`kalshi-client.md`](kalshi-client.md) | REST client, RSA-PSS auth, retention-window gotchas, historical-vs-live endpoint split. |
| [`hyperliquid-client.md`](hyperliquid-client.md) | Info API client, funding history, OHLCV download. |
| [`coinbase-client.md`](coinbase-client.md) | 1m candle backfill — the only US-accessible deep-history source for sub-hour BTC/ETH. |
| [`dashboard.md`](dashboard.md) | Streamlit dashboard, manifest-driven multi-strategy rendering, comparison tab. |
| [`portfolio-accounting.md`](portfolio-accounting.md) | NAV / locked risk / fees / sizing math; what the SQLite portfolio stores and why. |
| [`calibration-store.md`](calibration-store.md) | The on-disk calibration snapshot store and the `current.json` pointer model. |

## Operating principle

Platform docs describe **what is**, not **what should be**. They reflect the
shipped, working state of the code. Aspirational changes belong in
[`rd/`](../rd/) until they're built and merged.

When platform code changes, update the corresponding doc in the same commit.
The doc and the code are part of the same artifact.
