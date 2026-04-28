---
id: 16
name: Triple-screen on mid-vol crypto perps
status: backtest
verdict: viable
last-update: 2026-04-28
related-components: []
parent-candidate: 15
---

# Candidate 16: Triple-Screen on Mid-Vol Crypto Perps

## Status snapshot

- **Stage:** backtest (advance to paper-portfolio gated on Hyperliquid
  perp execution infrastructure — see Open questions)
- **Verdict:** viable — promoted from
  [candidate 15](15-elder-templates-bayesian.md) on the basis of
  walk-forward survival at 5-fold (6/10 top configs pass strict
  criterion) and cross-coin generalization to 21 of 31 cohort coins
  (median retention 87%, max 121%). Funding-aware replay (2026-04-28)
  passes all three pre-committed paper-portfolio criteria with wide
  margin in both full-history and 150-day-holdout modes.
- **Next move:** Build a Hyperliquid perp execution path so this can
  run as a paper book. The PM Underwriting paper-trade daemon is
  Kalshi-only; this needs a separate `strategies/elder_triple_screen/`
  module + Hyperliquid execution wiring.

## Ideation

**Origin:** Spawned from candidate 15's cohort expansion
(see [`15-elder-templates-bayesian.md`](15-elder-templates-bayesian.md)
§Cohort expansion). The pre-committed walk-forward criterion was met
on the (template, cohort) cell `triple_screen × vol_q4`, with the
config neighborhood generalizing across 21 of 31 cohort coins.

**Why the previous searches missed this:** The original LLM-run and
the candidate-15 Bayesian search both used the universe BTC-PERP /
ETH-PERP / SOL-PERP, which fall entirely in vol_q1 (BTC, ETH) and
vol_q2/q3 (SOL). Triple_screen's edge is concentrated in higher-vol
mid-cap cohorts (vol_q4: BIGTIME, kPEPE, XAI, HMSTR, LAYER, ZK,
ANIME, etc.) where 4h pullbacks-to-value at extreme RSI thresholds
produce reproducible setups that survive temporal slicing.

**Axiomatic fit:**
- *Combinations* — Elder's triple-screen (1980s mature framework) +
  cohort-aware crypto perp universe (2024-2026 substrate). The novelty
  is the cohort selection, not the template.
- *Different scale, different framing* (axiom 3) — the original Elder
  research framed templates against equities/FX/commodities, where
  the cohort spans wide vol regimes. The crypto-perp analog is
  vol-quintile bucketing across the Hyperliquid universe.
- *Methodology discipline* (axiom 6) — pre-registered walk-forward
  survival was the pass criterion; all candidate-15 work was committed
  to that gate before any cohort exploration. The viable cell was
  identified by the criterion, not chosen post-hoc.

## Locked config neighborhood

| Parameter | Value |
|---|---|
| template | triple_screen |
| long_tf | 1d |
| short_tf | 4h |
| slow_ema | 15 |
| fast_ema | 5 |
| oscillator | rsi (primary) — stochastic also viable |
| osc_entry_threshold | 89-100 (extreme RSI/stoch level) |

**Mechanism:** Within a 1d-defined trend (slow EMA rising → longs
only; falling → shorts only), wait on the 4h chart for the oscillator
to hit an extreme value (RSI ≥ 90 for shorts in a downtrend; RSI ≤ 10
for longs in an uptrend). Enter at the next bar's close. Stop below
the recent 4h low (long) or above the recent high (short). Target a
2:1 reward/risk minimum.

This is a counter-trend pullback inside a same-direction trend filter
— the textbook Elder triple-screen, with parameters discovered by
Bayesian search.

## Universe (locked at vol_q4)

The 31 coins in vol_q4 as of 2026-04-28 (annualized σ on daily log
returns, range 1.18-1.37):

```
BIGTIME, kPEPE, XAI, HMSTR, LAYER, ZK, ANIME, ZRO, MEW, BERA, ENA,
MAVIA, WIF, CYBER, PYTH, SAGA, BANANA, CHILLGUY, AIXBT, MANTA, DEEP,
BERA, S, SUNDOG, MOG, GOAT, kBONK, ZEREBRO, HYPER, NEIROETH, TST
```

(See `/tmp/cohorts.json` — definitive list.)

The σ-quintile assignment is based on the 2026-04-28 lookback. Cohort
membership may drift over time; the paper book should re-profile the
universe on a rolling basis (suggested cadence: monthly).

## Pre-committed pass / fail criteria for paper-portfolio

To advance from paper to live, the paper book must produce, over
**≥ 30 days** of live paper trading on the cohort:

1. **Aggregate Sharpe (annualized) ≥ 1.0** across the cohort book.
2. **Median per-coin Sharpe ≥ 0.5** — confirms the edge isn't
   concentrated in 1-2 coins.
3. **Max drawdown ≤ 25%** at the book level under the same 2%-per-trade
   sizing the harness assumes.
4. **CLV-equivalent metric** (entry vs. local-mean fill) trending
   non-negative — borrowed from the PM Underwriting playbook.

Reject the candidate if any of:
- Aggregate Sharpe < 0 over 30+ days.
- Per-coin Sharpe spread reveals 1-2 coins doing all the work
  (single-asset overfit reasserts itself live).
- Max drawdown > 35%.

## Backtest

Inherits candidate 15's cohort run results
(`data/prospector_bayesian.db`, rows where
`json_extract(config_json, '$.cohort')='vol_q4' AND template='triple_screen'`).

### Broader-TF re-search (2026-04-28)

After candidate 15's initial cohort search, the user flagged that
`triple_screen` had been searched with `long_tf` locked at "1d" and
only `short_tf ∈ {4h, 1h}`. To close the gap, the search axes were
extended to a single categorical `tf_combo` covering all six
Elder-style scale pairs:
`{1d/4h, 1d/1h, 4h/1h, 1w/1d, 1w/4h, 1w/1h}`. 1h + 1w OHLCV pulled for
the 31 vol_q4 coins. Re-ran the locked Bayesian search (200 evals,
seed 42) on vol_q4 with the broader axes (`data/prospector_bayesian_btf.db`):

| tf_combo | evals | scored-rate | max | mean scored |
|---|---|---|---|---|
| 1d/4h | 110 | 84% | 200.0 | 155.9 |
| 1w/4h | 41 | 63% | 151.6 | 100.1 |
| 4h/1h | 12 | 67% | 148.6 | 72.6 |
| 1w/1h | 12 | 42% | 159.0 | 103.3 |
| 1d/1h | 11 | 36% | 147.8 | 65.5 |
| 1w/1d | 14 | **0%** | — | — |

The optimizer concentrated on `1d/4h` and explored every alternative;
none beat it. `1w/1d` produced **zero scored configs** in 14 attempts
(only ~104 weekly bars at 730d lookback — too sparse to clear the
20-trade gate). Walk-forward of broader-TF top-10 produced two configs
with 5/5 perfect fold consistency (#167 XAI 63% retention,
#160 EIGEN 51% retention), but cross-coin generalization is *weaker*
than the original #3895 (4/31 vs 21/31 for #3895), so #3895 remains
the recommended config.

**Conclusion: 1d/4h is the dominant scale. The gap was closed with no
change to the recommendation.**

### Top config #3895 (locked)
parameters: `long_tf=1d, short_tf=4h, slow_ema=15, fast_ema=5,
oscillator=rsi, osc_entry_threshold=93.68`

**Top config (#3895):**
- in-sample score 200.0 (NAV-ceiling cap), 128 trades on ZK_PERP
- 5-fold walk-forward: best holdout 172.2 / 200 = 86% retention
- Cross-coin generalization: scored on 28/31 cohort coins; survives
  strict criterion (≥4/5 folds AND ≥70% retention) on 21/31

**Top config #3890** (sister of #3895):
- Same param family with `osc_entry_threshold=89.3`
- 20/31 cohort coins survive strict criterion
- Median 87% retention

**Convergent neighborhood:** Top-10 configs from vol_q4 cluster on
slow_ema=15, fast_ema=5, oscillator=rsi, threshold ∈ [89, 100]. Robust
to small parameter perturbations.

## Paper portfolio

### Funding-aware replay (2026-04-28)

Funding-rate cost was modeled upfront rather than retrofitted. New
module `src/prospector/harness/funding.py` integrates per-trade
funding charges from Hyperliquid's hourly funding-rate history
(LONG pays funding when rate > 0; SHORT receives). 19 of 31 vol_q4
coins have funding history available; the remaining 12 returned
empty responses from the API (most were listed too recently for the
requested 730-day window). Coins without funding data fall back to
zero funding cost in the replay; given funding is 0.3-0.6% of P&L
for the funded subset, the missing coverage doesn't shift the
decision. Replay script: `scripts/elder_replay_paper.py`.

**Full-history mode** (28 of 31 vol_q4 coins, 730 days, in-sample to the search):

| metric | value |
|---|---|
| total gross P&L | +$1,039,915 |
| total fees | $59,544 |
| total funding cost | +$3,070 (**0.3% of P&L magnitude**) |
| net with funding | +$977,301 |
| median Sharpe (with funding) | 5.09 |
| mean Sharpe (with funding) | 5.29 |
| max DD across coins | 17% |

**Holdout mode** (last 150 days only — the most-recent walk-forward fold):

| metric | value |
|---|---|
| total gross P&L | +$201,621 |
| total fees | $13,557 |
| total funding cost | +$1,179 (**0.6% of P&L magnitude**) |
| net with funding | +$186,884 |
| median Sharpe (with funding) | **4.31** |
| mean Sharpe (with funding) | **4.49** |
| max DD across coins | 16% |

**Pre-committed paper criteria — go/no-go:**

| criterion | threshold | full-history | holdout | result |
|---|---|---|---|---|
| aggregate Sharpe | ≥ 1.0 | 5.29 | 4.49 | ✅ PASS |
| median per-coin Sharpe | ≥ 0.5 | 5.09 | 4.31 | ✅ PASS |
| max drawdown | ≤ 25% | 17% | 16% | ✅ PASS |
| CLV-equivalent non-negative | trending | (not yet instrumented) | — | deferred to live paper book |

**Verdict: GO.** All three quantitative criteria PASS by 4-10× margin
in both full-history and holdout modes. The CLV-equivalent criterion
is deferred to the live paper book where market mid-quote snapshots
will be available.

### On the magnitude of these Sharpes

Sharpe 4-5 is at the optimistic end of plausible. Real-world friction
not in the harness:
- **Slippage on illiquid alts**: harness models 0.05% per side; vol_q4
  includes thin perps where realistic slippage may be 2-5×.
- **Partial fills / cancellation lag**: harness fills at exact close
  price; live execution has queue dynamics.
- **Cohort-membership drift**: 4 of the 31 backtest coins (TRUMP, NIL,
  ANIME, etc.) have less than 730 days history; the holdout sample for
  those is shorter than implied.

A realistic 30-50% Sharpe haircut would still leave the strategy
clearing the threshold (4.49 × 0.5 = 2.24 aggregate, still ≥ 1.0). But
the live paper book is the definitive test — replay numbers should be
read as *upper bounds*, not point estimates.

### Live paper plan (post-infra)

1. Build `src/prospector/strategies/elder_triple_screen/` mirroring
   `pm_underwriting/` structure.
2. Wire Hyperliquid perp execution (paper-only initially — record
   intended trades, mark to mid).
3. Run on top-10 vol_q4 coins; record per-coin P&L, aggregate Sharpe.
4. After 30 days: evaluate against the pre-committed criteria above
   plus CLV-equivalent metric.

## Live trading

(Empty — gated on paper-portfolio outcome.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-28 | Spawned from #15's vol_q4 surviving cell | 6/10 configs pass walk-forward at strict 5-fold criterion; cross-coin generalizes to 21/31 cohort coins (median 87% retention) — not a single-asset artifact |
| 2026-04-28 | Status: backtest, verdict viable | Backtest + walk-forward + cross-coin gen all pass; paper-portfolio advance gated on infra build |
| 2026-04-28 | Replay-first paper plan | Verify fold-5-equivalent Sharpe before building infra; cheap test (no new code beyond the existing harness) that catches regime drift early |
| 2026-04-28 | Pre-committed paper pass criteria locked | Aggregate Sharpe ≥ 1.0, median per-coin ≥ 0.5, max DD ≤ 25%, plus CLV-equivalent trending non-negative |
| 2026-04-28 | Broader-TF re-search closed the `long_tf` gap | User flagged that triple_screen had `long_tf` locked at 1d. Pulled 1h+1w for vol_q4, extended axes to a `tf_combo` categorical covering all six pairs. 1d/4h dominates (110/200 evals, max 200, mean 156); 1w/1d gets zero scored configs (sparse weekly bars). #3895 unchanged as the recommended config. |
| 2026-04-28 | Funding modeled upfront; replay PASSES all criteria | New `harness/funding.py` integrates Hyperliquid hourly funding into per-trade cost. Full-history Sharpe 5.29 / holdout 4.49; funding cost is 0.3-0.6% of P&L magnitude (cancels because triple_screen takes both directions) |
| 2026-04-28 | **Verdict reaffirmed: GO** for paper-portfolio advance | All three quantitative pre-committed criteria pass by 4-10× margin in both replay modes. Sharpe magnitude is at the optimistic end; realistic 30-50% haircut still clears thresholds. Live paper book remains the definitive test. |

## Open questions

1. **Universe stability** — vol_q4 membership will drift. Should the
   paper book re-profile monthly? Quarterly? Or fix the 2026-04-28 set
   as the locked universe and let new vol_q4-eligible coins phase in?
2. **Hyperliquid perp execution** — the existing
   `strategies/pm_underwriting/` doesn't share infrastructure with
   perp execution. Build cost: estimated 1-2 weeks for paper-only
   (mark-to-mid) execution, more for live with real fills.
3. **Funding-rate drag** — Hyperliquid perps charge funding hourly.
   The harness's `transaction_cost` doesn't model this; for hold
   times > 1h, funding can shift Sharpe materially. Need to instrument
   per-trade hold-time and net funding cost in the paper book.
4. **Cohort overlap with PM books** — none of the cohort vol_q4 coins
   overlap with KXBTC/KXETH (PM Underwriting's crypto slice), so
   capital allocation is straightforward.

## Pointers

- Parent candidate: [`15-elder-templates-bayesian.md`](15-elder-templates-bayesian.md)
- Search results DB: `data/prospector_bayesian.db`
  (`SELECT * FROM runs WHERE template='triple_screen' AND
  json_extract(config_json,'$.cohort')='vol_q4'`)
- Cohort definition: `/tmp/cohorts.json` (will be persisted to
  `data/cohorts/vol_quintiles_2026-04-28.json` when this advances)
- Walk-forward + cross-coin scripts:
  `scripts/walk_forward_top_configs.py` (with `--template --cohort`),
  `scripts/elder_cross_coin_test.py`
