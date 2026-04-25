---
id: 05
name: Weather ensemble model arbitrage
status: ideation
verdict: pending
last-update: 2026-04-25
related-components:
  - llm-altdata-extraction  # NWS AFD layer (T6)
---

# Candidate 05: Weather Ensemble

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — strong fit, queued as next active R&D track per [pipeline.md](../pipeline.md)
- **Next move:** Promote to deep-dive when bandwidth allows. Pair with [`llm-altdata-extraction`](../../components/llm-altdata-extraction.md) for NWS Area Forecast Discussion features as a differentiator.

## Ideation

**Origin:** GFS 31-member ensemble models produce probability distributions
for temperature, precipitation, snowfall. Compare to Kalshi weather
contract prices. When models diverge from market, trade. Update 4× daily
(00Z, 06Z, 12Z, 18Z model runs).

**Cross-domain origin:** Numerical weather prediction. Ensemble forecasting
exists because no single model run is reliable — averaging across
perturbations produces a calibrated probability distribution. Same
principle as Bayesian model averaging in statistics. Apply to Kalshi.

**Why-now:** Open-source weather bots exist (~$1.8K profits documented).
Kalshi weather markets are well-structured. GFS data is free (NOAA).

**LLM angle (the differentiator):** Layer LLM-extracted features from NWS
Area Forecast Discussions (free-text expert narrative published 2× daily
per station) on top of model outputs. AFDs contain hedges like "models
probably underforecast max temps due to wildfire haze reducing
radiational cooling" — information not in any structured product. See
[`llm-altdata-extraction`](../../components/llm-altdata-extraction.md)
for the pattern.

**Axiomatic fit:**
- *Combinations* — ensemble forecasting + LLM-extracted forecaster
  narratives + Kalshi binary contracts
- *Small-player* — open-source bots have done it; the LLM-AFD overlay
  hasn't been done at this layer
- *Categorical LLM role* — perfect fit (text → structured features)
- *Operational* — daily cadence, hundreds of events/year (multi-city ×
  multi-contract-type), uncorrelated with crypto book

**Operational triage:** Passes both filters. Cadence is daily (well
within envelope); throughput is many hundreds/year (excellent).

## Deep dive

(Empty until promoted.)

## Statistical examination

(Empty.)

## Backtest

(Empty.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-15 | Logged in original `strategy-families.md` (now archived) as #12 | Family scoring; high LLM-fit, daily cadence, uncorrelated with crypto |
| 2026-04-23 | Operational triage applied; passes both filters | Best-fit candidate for next active R&D track |
| 2026-04-25 | T6 (NWS AFD LLM alt-data) surfaced in fresh-eyes review and recommended as a layered enhancement | Distinguishes from existing weather bots |
| 2026-04-25 | Doc consolidated into rd/candidates/; status remains ideation | Reorg |

## Open questions

- Which cities first? Kalshi has expanded coverage; pick by liquidity.
- Which forecast horizon? GFS goes 16 days; Kalshi contracts vary.
- AFD scope — all stations, or only the cities Kalshi trades?
- LLM prompt design for AFD extraction — needs prompt-versioning discipline (see component doc).

## Pointers

- LLM altdata pattern: [`components/llm-altdata-extraction.md`](../../components/llm-altdata-extraction.md)
- Open-source reference: GitHub `suislanchez/polymarket-kalshi-weather-bot`
