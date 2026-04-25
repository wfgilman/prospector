---
id: 08
name: Dispersion trade on Kalshi series-vs-game markets
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 08: Dispersion Trade

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — high-conviction Tier 1 from fresh-eyes review
- **Next move:** Promote to deep-dive; 1-day historical backtest of the structure on the Kalshi tree is the kill criterion.

## Ideation

**Origin:** TradFi dispersion trading: buy options on index components,
sell options on the index, profit from implied-vs-realized correlation
gap. Index option implied vol tends to be "rich" relative to single-name
component vol — winners and losers offset at the index level.

**Kalshi analogue:** Kalshi lists both "Team X wins championship" *and*
"Team X wins each playoff game." Under independence:

```
P(championship) = ∏ P(game_i wins)
```

Crowd systematically overweights championship dreams (narrative premium
on the aggregate). **Buy the championship market, sell the parlay legs**
→ delta-neutral expression of parlay overpricing. Same edge PM Underwriting
exploits, opposite structure.

**Cross-domain origin:** Cboe S&P 500 Dispersion Index (DSPX); 2000s-era
correlation-trading desks. Earnings season is a common hunting ground —
single-name reactions diverge while indexed options reflect cross-
correlation premium.

**Axiomatic fit:**
- *Combinations* — dispersion trading (mature) + Kalshi sports surface
- *Structurally delta-neutral* — series outcomes don't shift the trade's
  P&L; same-side exposure cancels
- *No new infrastructure* — uses existing calibration + scanner; the
  novel part is the position-pairing logic
- *Small-player* — moderate capacity, fits within current daily caps

## Deep dive

(Empty until promoted.)

## Statistical examination

Pre-registration sketch (lock before any historical run):
- **Universe:** Kalshi sports series with both championship-level and
  game-level markets (NFL, NBA, NHL playoffs)
- **Pairing rule:** for each championship contract, identify its
  game-level constituent contracts via series_ticker prefix
- **Position structure:** long championship, short ∑ game-level legs at
  hand-tuned weights to delta-neutralize the series outcome
- **Pass criterion:** historical backtest produces positive P&L net of
  fees on > 60% of completed series, with mean P&L > 1% of capital
  deployed
- **Kill criterion:** if dispersion is negative or noisy in historical
  data, no rescue path (it's a structural-pricing question)

## Backtest

(Empty until stat-exam complete.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced in fresh-eyes review as T4 (Tier 1) | Pure novelty, no infra changes, clean kill criterion via historical backtest |
| 2026-04-25 | Doc created in rd/candidates/ as ideation | Reorg |

## Open questions

- Which series first? NFL is the most-traded; NBA playoffs are imminent.
- Position-weighting: equal-leg, edge-weighted, σ-weighted?
- Re-pairing cadence — once per series, weekly, or per-game?
- Liquidity considerations: championship markets are typically deeper
  than individual game-leg markets; sizing the short legs may bind
  before the long.

## Pointers

- Calibration component (used to identify mispriced legs): [`components/calibration-curves.md`](../../components/calibration-curves.md)
- Reference: Quantpedia "Dispersion Trading"; Cboe DSPX index
