# R&D Pipeline — Cross-Candidate Status

> The single-screen view of every candidate. Update with every stage transition.

For stage definitions and verdict criteria, see
[`../reference/stages-and-verdicts.md`](../reference/stages-and-verdicts.md).

## Active

| ID | Candidate | Stage | Verdict | Last update | Next move |
|---|---|---|---|---|---|
| 01 | [PM Underwriting · Lottery](candidates/01-pm-underwriting-lottery.md) | paper-portfolio | pending | 2026-04-27 | Continue paper accrual to ~2026-05-20; if `corr(edge_pp, clv_pp)` stays sub-0.1, implement MVT rolling-threshold |
| 04 | [PM Underwriting · Insurance](candidates/04-pm-underwriting-insurance.md) | paper-portfolio | pending | 2026-04-25 | Daemon loaded; first tick ~07:55 PT 2026-04-25; assess after 30 days |
| 16 | [Triple-screen on mid-vol crypto perps](candidates/16-triple-screen-midvol-crypto.md) | paper-portfolio | pending | 2026-04-28 | Funding-aware replay PASSES all paper criteria (mean Sharpe 4.49 holdout, funding 0.6% of P&L). Paper book wired and smoke-tested; 4h-cadence launchd plist ready. Next: launch + accrue 30 days; T+30 eval ~2026-05-28 |

## Terminal — kept for reference

| ID | Candidate | Stage | Verdict | Last update | Reason |
|---|---|---|---|---|---|
| 00 | [Elder templates (LLM optimizer)](candidates/00-elder-templates.md) | rejected | needs-iteration | 2026-04-25 | LLM-as-optimizer falsified (real). "Directional" critique and trade-sparsity were treated as structural; fresh-eyes review revised first two as self-imposed framework errors. Reformulated as [`15`](candidates/15-elder-templates-bayesian.md) with Bayesian optimizer. |
| 02 | [Kalshi × crypto narrative spread](candidates/02-kalshi-crypto-narrative-spread.md) | rejected | needs-iteration | 2026-04-23 | Sign correct on 15-min Coinbase data; magnitude near zero. Operational triage: cadence + throughput fail. Revisit if infra envelope opens or 2+ years more events accumulate. |
| 03 | [Kalshi × Hyperliquid vol surface](candidates/03-kalshi-hyperliquid-vol-surface.md) | absorbed | viable | 2026-04-23 | Convergence thesis dead, D1 longshot wedge replicated. Folded into PM Phase 5 hedging overlay scope. |
| 15 | [Elder templates + Bayesian optimization](candidates/15-elder-templates-bayesian.md) | absorbed | viable | 2026-04-28 | 2-template & 6-template runs on BTC/ETH/SOL failed; expanding to 229-perp universe + σ-quintile cohorts surfaced `triple_screen × vol_q4` as a walk-forward survivor that cross-coin-generalizes to 21/31 cohort coins (median 87% retention). Surviving cell absorbed into [#16](candidates/16-triple-screen-midvol-crypto.md). |

## Ideation — queued

| ID | Candidate | Promoted from | Tier | Notes |
|---|---|---|---|---|
| 05 | [Weather ensemble](candidates/05-weather-ensemble.md) | strategy-families.md #12 | next-track | Daily cadence, many hundreds of events/year; pair with NWS AFD LLM alt-data ([component](../components/llm-altdata-extraction.md)) |
| 06 | [Token unlocks](candidates/06-token-unlocks.md) | strategy-families.md #2 | borderline | Weekly-to-daily cadence, ~120-360 events/yr; throughput borderline |
| 07 | [Three-venue PM divergence](candidates/07-three-venue-pm-divergence.md) | fresh-eyes T5 | tier-2 | Kalshi × Polymarket × HIP-4. HIP-4 mainnet window Jun–Sep 2026 (Polymarket-implied 85%/99%); build Polymarket data layer to be ready ~mid-June |
| 08 | [Dispersion trade](candidates/08-dispersion-trade.md) | fresh-eyes T4 | tier-1 | Buy series-winner / sell parlay legs; delta-neutral parlay-overpricing expression |
| 09 | [Kalshi × CME weather convergence](candidates/09-kalshi-cme-weather-convergence.md) | fresh-eyes T8 | tier-2 | Same NOAA underlying, different audiences; needs employer-policy verification on commodity futures |
| 10 | [Slow book (28d+ rejections)](candidates/10-slow-book-shadow-rejections.md) | fresh-eyes T7 | tier-2 | Replay shadow-ledger rejections at weekly cadence; long-duration markets |
| 11 | [Event-window-only HFT mini-daemon](candidates/11-event-window-hft-daemon.md) | fresh-eyes T9 | tier-3 | Sub-min execution only during ~8 FOMC days/year |
| 12 | [Kalshi maker-side reflexivity](candidates/12-kalshi-maker-reflexivity.md) | fresh-eyes T10 | tier-3 | Maker-side liquidity premium when flow compresses orderbook toward position limits |
| 13 | [HIP-3 first-day-after-auction spread](candidates/13-hip3-first-day-spread.md) | fresh-eyes T11 | tier-3 | Dutch-auction launch spreads on Hyperliquid HIP-3 markets |
| 14 | [LLM-scored attention premium](candidates/14-llm-attention-premium.md) | fresh-eyes T12 | tier-3 | Sentiment-weighted volume vs. DOGE/WLFI perp; narrower #4 reformulation |

## Outside the candidate framework

These are project investments that aren't strategies but which several
candidates depend on:

| Investment | Status | Pointer |
|---|---|---|
| In-house data pipeline | Shipped (M1, M2 done; M3 cron live) | [`../platform/data-pipeline.md`](../platform/data-pipeline.md) |
| Paper-trade daemon (multi-book) | Shipped, two books running | [`../platform/paper-trade-daemon.md`](../platform/paper-trade-daemon.md) |
| Dashboard with comparison tab | Shipped 2026-04-25 | [`../platform/dashboard.md`](../platform/dashboard.md) |
| CLV instrumentation | Shipped 2026-04-24 | [`../components/clv-instrumentation.md`](../components/clv-instrumentation.md) |
| MVT rolling-threshold | Designed; not yet implemented | [`../components/mvt-rolling-threshold.md`](../components/mvt-rolling-threshold.md) |

## How to update this file

When a candidate transitions stage or changes verdict:

1. Move the row between **Active** / **Terminal** / **Ideation** as appropriate
2. Update the candidate's `last-update` cell (current ISO date)
3. Update the **Next move** column with the immediate concrete action
4. Verify the candidate file's frontmatter matches what's here

When a new ideation candidate is added: add a row to **Ideation** with a
short notes string; the full content is in the candidate file.
