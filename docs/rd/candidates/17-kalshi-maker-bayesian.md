---
id: 17
name: Kalshi sports MM with Bayesian optimizer (sibling-strategy replication)
status: ideation
verdict: pending
last-update: 2026-04-29
related-components: []
parent-candidate: null
---

# Candidate 17: Kalshi Sports MM with Bayesian Optimizer

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — user-directed 2026-04-29 R&D track
- **Next move:** Deep-dive into infrastructure gaps (maker-side simulator,
  paper-MM book schema). Pre-register Bayesian-vs-random and walk-forward
  pass criteria before any test fold runs. Replicate the friend's sports
  MM result on our `data/kalshi/trades/` tree as the first checkpoint.

## Ideation

**Origin:** User direction 2026-04-29 after a verbal exchange with the
friend who owns `~/workspace/other-trading-projects/kalshi-autoagent`.
Friend stated that the only currently-promising sibling strategy is
sports-prop market making in high-spread, thin-liquidity Kalshi markets
(KXMLBHRR / KXNHLGOAL / KXNBAPTS / KXMLBHIT / KXNHLFIRSTGOAL). His best
config achieves +71.8% bankroll on a 134-event retrain (`mm_sports_meta_results_134ev.tsv`,
score 143.69, 11,949 fills) — but the optimization procedure that found
it is an LLM inner-loop, the same pattern we falsified for continuous
parameter search in [candidate 00](00-elder-templates.md).

**Why-now:** Two compounding signals:
1. The friend's published trajectory has decreasing KEPT rate as the
   sample widens (8/48 KEPTs on 25-event run → 3/50 KEPTs on 134-event
   retrain). This is consistent with the LLM-as-optimizer plateau
   documented in [axiom 5](../../charter/axioms.md#5-the-llms-comparative-advantage-is-categorical-reasoning-over-text)
   — the LLM is not generating fresh exploration directions, it's
   accidentally landing on incremental improvements within a concave
   bowl.
2. We have a working Bayesian harness from
   [candidate 15](15-elder-templates-bayesian.md) (`scripts/elder_bayesian_search.py`,
   skopt GP + Matérn 5/2 + EI). The same harness pattern drops in
   directly on the MM problem.

The act of porting his strategy through our pipeline is itself the
deliverable: it forces us to (a) understand the simulator's edge
mechanics in detail rather than treating it as a black box, (b) verify
that our `data/kalshi/trades/` tree can reproduce his training data
(byte-for-byte agreement was previously confirmed on the overlap window —
see [data-pipeline.md](../../platform/data-pipeline.md) §canonical Kalshi
tree), and (c) settle the open question of whether his 71.8% number
survives a competent optimizer's search or was an LLM-luck artifact.

**Axiomatic fit:**
- *Combinations* (axiom 1) — friend's MM simulator × our Bayesian harness ×
  our paper-trade daemon pattern. None of the three is novel; the
  combination wasn't tried because the friend's project doesn't use BO and
  we don't have a maker-side simulator.
- *Small-player axiom* (axiom 2) — pro MMs cannot quote sports props at
  Kalshi position limits; the spread persists *because* of small-scale
  capital. This is exactly the regime axiom 2 names.
- *Different scale, different framing* (axiom 3) — the friend trains
  per-category and accepts whatever the LLM finds. We will train
  per-category but with a falsifiable optimizer comparison and
  walk-forward gating.
- *Methodology discipline* (axiom 6) — pre-registered Bayesian-vs-random
  comparison, walk-forward survival across event-disjoint folds, locked
  search space.
- *LLM categorical-only* (axiom 5) — explicitly NOT using the LLM for
  parameter search. The LLM's role, if any, is at the outer loop:
  reading pattern from search traces and proposing new knobs to expose,
  same as in candidate 15.
- *Directional with measured edge* (axiom 7) — MM is technically
  non-directional (matched fills net to zero net direction) but
  inventory P&L at settlement is directional. Per axiom 7, that's fine
  if variance is bounded by sizing.
- *Know what's already been done* (axiom 8) — see *Prior art* below.

**Prior art / existing applications:** see
[`literature-survey.md`](../../reference/literature-survey.md) §2.3 +
the new optimal-MM-theory subsection.

| Reference | What it gives us | What we adapt vs. apply directly |
|---|---|---|
| Avellaneda–Stoikov 2008 | Reservation-price + symmetric-spread closed-form for inventory-aversion MM | The friend's `inv_skew` is a linearization of A–S's γσ²(T−t) skew. We use the linearization (cheaper to fit) but A–S is the theoretical anchor. |
| Glosten–Milgrom 1985 | Bid-ask spread emerges from informational asymmetry | The friend's `toxicity_widen_threshold` is a binary G–M heuristic (widen on adverse-flow signal). We carry this knob into the Bayesian search. |
| Cartea–Jaimungal–Penalva 2015 | Practitioner translation, model-uncertainty extensions | Reading-list reference; not used in implementation. |
| Spooner et al RL MMs (1911.05892, etc.) | Upper bound on what optimal quoting can achieve | Out of scope for this candidate; would be candidate 17+ if BO succeeds and RL becomes worth the compute. |
| Sibling `kalshi-autoagent/strategies/market_maker.py` | Working maker-side simulator with hardening (vol gate, pair-eventually detection, toxicity defense, MM_MIN_HALF_SPREAD_VOL_RATIO floor) | Port wholesale; this is the fastest path to a tested simulator. Friend's `mm_meta_results.tsv` and `config_market_maker_sports_best_134ev.json` are the replication target. |
| Sibling `market_maker_sports_handoff.md` | Replication recipe (5 series, 60-day window, 134 events, MIN_TRADES_PER_EVENT=20 filter) | Use as the spec for our task generator. |
| Our own [#15 Bayesian harness](15-elder-templates-bayesian.md) | skopt GP + Matérn 5/2 + EI(xi=0.01), 20 init + 180 EI proposals, locked seed | Drop-in for the optimizer side. |

**What is specifically different about our application:** we are running
the same simulator and same task universe through a different optimizer
and a stricter validation harness. The strategy isn't novel; the
*honest measurement of whether the strategy is real and whether the
free-parameter optimizer is the bottleneck* is.

## Deep dive

### What we are testing, in three nested questions

1. **Is the MM strategy itself real on our data tree?** Replicate the
   friend's sports baseline (+2% bankroll, 76% WR pre-tuning) on our
   `data/kalshi/trades/` using the ported simulator. Pass = match within
   ±5%. This isolates "does our data tree reproduce his data" from "does
   the strategy work."
2. **Can a Bayesian optimizer beat the LLM at finding the same kind of
   config?** Same search space, matched 200-evaluation budget, locked
   seed, locked acquisition function. Pass = Bayesian beats random
   baseline at matched N by ≥30% max-score AND ≥50% scored-rate (same
   bar as candidate 15).
3. **Do BO-found configs survive walk-forward across event-disjoint
   folds?** This is the validation gate the friend's pipeline does not
   apply. Pass = ≥3 of top-10 BO configs hit ≥4/5 scored AND ≥70%
   retention on holdout-event folds.

If all three pass, we have an MM strategy with a competently-tuned
config that survived event-disjoint walk-forward. That earns paper-book
deployment behind a maker-side daemon — analogous to
`paper_trade_elder.py` but with maker-side execution semantics and
inventory state.

### What we will port from the sibling project

| Sibling artifact | Our destination | Notes |
|---|---|---|
| `strategies/market_maker.py` | `src/prospector/strategies/kalshi_mm/simulator.py` | Port verbatim; rename module. Preserve `OPERATOR_OVERRIDES`, `MM_MIN_HALF_SPREAD_VOL_RATIO`, `MM_ADVERSE_HAIRCUT_FRAC`, `MM_PAIR_LOOKAHEAD_TRADES`, `MM_MAKER_FEE_PER_CONTRACT` constants verbatim. |
| `build_mm_sports_tasks.py` | `scripts/build_mm_sports_tasks.py` | Rewrite to read from our parquet tree (`data/kalshi/trades/`, `data/kalshi/markets/`) instead of his `orderbook.db`. Keep the 134-event filter (MIN_TRADES_PER_EVENT=20). |
| `mm_strategy_loop.py` | replaced by `scripts/kalshi_mm_bayesian_search.py` | The whole point — drop the LLM-loop wrapper, use skopt GP + EI. |
| `config_market_maker_sports_best_134ev.json` | `data/kalshi_mm/sibling_baseline.json` | Frozen reference — what we are trying to match-or-beat. |

### What we will NOT port

- The LLM inner loop (`mm_strategy_loop.py`'s Ollama integration)
- The two-loop categorical scoring TSV format
- The `MM_EXPANSION_PLAN.md`-described external-FV adapters (politics
  polling, sportsbook odds). Friend's sports MM works with internal
  static FV only; we follow that.

### Infrastructure gaps to fill

| Gap | Effort | Risk if skipped |
|---|---|---|
| Maker-side simulator port | Small (~200 LOC, copy + adapt I/O) | Cannot run anything |
| Sports-task generator from parquet tree | Small (~150 LOC) | Cannot generate training set |
| Bayesian search wrapper | Trivial — fork `scripts/elder_bayesian_search.py`; only the search-space dict and the eval function change | None |
| Walk-forward fold splitter (event-disjoint) | Small | Cannot pre-register criterion 3 |
| Paper-MM daemon | Medium (~400 LOC: position state schema, settlement-handling, separate launchd plist) | Only blocks paper-portfolio stage; not blocking statistical exam |

The paper-MM daemon is genuinely a separate piece of work from the
sibling-replication; it's listed here as a known downstream
dependency, not something to build before the optimization-side work
finishes. Decision point: build it only if criteria 1–3 all pass.

### Trade-density check (versus the #15 sparsity wall)

The Elder candidate hit a structural trade-sparsity wall — 40-120
trades over the full 5000-bar 4h history meant 5-fold splits gave
~8-24 trades per fold, often below the 20-trade gate.

Sports MM is on the opposite side of this wall by orders of magnitude:
the friend's 134-event retrain produced **11,949 fills**. Per-event
fills ≈ 89; per-fill walk-forward fold (134 events × 5-fold = ~27
events/fold × 89 fills/event) ≈ 2,400 fills per fold. The sparsity
constraint that killed Elder is irrelevant here. **The walk-forward
test is a real test of generalization, not a degenerate gate.**

## Statistical examination

(Pre-registered before any test fold is touched. To be filled in
after the deep-dive completes infrastructure work.)

### Pre-registered hyperparameters — locked

| Knob | Value | Rationale |
|---|---|---|
| Optimizer | scikit-optimize GP, Matérn 5/2 kernel, EI acquisition (xi=0.01) | Direct copy of candidate 15's locked optimizer; no kernel/acquisition sweep |
| Initial random samples | 20 | Cover the search space before GP fitting |
| Total evaluation budget | 200 | Matched to friend's LLM run for direct comparison |
| Random baseline | 200 evals (Latin hypercube over the same search space) | Apples-to-apples vs. LLM and Bayesian |
| Universe | KXMLBHRR + KXNHLGOAL + KXNBAPTS + KXMLBHIT + KXNHLFIRSTGOAL | Same as friend's sports-MM scope |
| Sample window | Last 60 days from our `data/kalshi/trades/` watermark | Replicates the friend's `--days 60` predexon filter |
| Event filter | MIN_TRADES_PER_EVENT=20 | Same as friend's filter; expected to yield ~134 events |
| Operator overrides | `quote_size=2`, `max_inventory=10`, `fv_rolling_window_trades=0` | Pinned per friend's `OPERATOR_OVERRIDES` (from his live-pilot calibration) |
| Search space | the 13 unpinned knobs in `KNOB_SCHEMA` from `market_maker.py` | Identical to friend's space (continuous ∪ small int) |
| Scoring | `pct_return × 200` capped at 200 | Direct copy from `mm_strategy_loop.py` |
| Walk-forward | 5-fold event-disjoint (events sorted by `expiration_time`, hashed into 5 buckets) | Time-disjointness is the relevant generalization axis |
| Per-fold trade gate | ≥ 100 fills | MM-specific; far above the structural floor — events with no fills indicate task-generation bug |
| Random seed | 42 | Reproducibility |

### Pre-committed pass criteria

To advance from **statistical-examination → backtest**:

1. **Replication.** Running the ported simulator at the friend's
   `config_market_maker_sports_best_134ev.json` against our task tree
   reproduces his +71.8% bankroll within ±10%. (Sample noise is
   acceptable; large discrepancy is a data-tree bug to investigate.)

To advance from **backtest → paper-portfolio**, **all three** must hold:

2. **Bayesian-vs-random.** BO max-score and scored-rate exceed random
   at matched N=200, by ≥30% on max-score AND ≥50% on scored-rate.
   (Same threshold as candidate 15.)
3. **BO replication.** BO's best config matches-or-beats the friend's
   LLM-found config on the full 134-event task set.
4. **Walk-forward survival.** Among BO top-10 configs, ≥3 have ≥4/5
   scored folds AND ≥70% retention vs. in-sample peak. (Same shape as
   candidate 15.)

### Pre-committed kill criteria

Reject as `non-viable` if **either**:

1. **Replication fails by >25% gap.** Investigation diverts into a
   data-tree audit, not a strategy verdict. Status returns to ideation
   pending audit; not a non-viable verdict on the strategy itself.
2. **BO walk-forward kill.** BO's top-10 configs all fail
   the walk-forward gate. Combined with #15's finding, this would
   suggest that "tune the free parameters by historical replay" is
   *itself* the wrong frame on Kalshi MM regardless of optimizer
   choice — and would push toward an A–S-style closed-form
   formulation as a separate candidate.

If criterion 1 passes but 2/3 fails, the verdict is
`needs-iteration`: BO didn't beat random by the pre-registered
margins, but the strategy replicates and the walk-forward survives.
That would be a slightly weaker version of axiom 5 — BO is not
strictly required when the landscape is concave-and-easy — and the
candidate would advance to paper at the friend's converged config
without claiming optimizer credit.

If criterion 4 fails alone, the verdict is `needs-iteration` with
diagnostic: investigate whether walk-forward fails because of regime
shift (specific weeks/series have flow profiles that don't generalize)
or because of true overfit (no robust cell exists in the search space).

## Backtest

(Empty until pre-registration locks and runs.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-29 | Candidate created from user direction | Friend's verbal "only thing showing live promise" combined with the structural mismatch of his LLM-as-optimizer choice and our axiom 5. Replication-through-our-pipeline is itself the deliverable. |
| 2026-04-29 | Locked optimizer copy from candidate 15 (skopt GP + Matérn 5/2 + EI, xi=0.01, 20+180 budget, seed 42) | Re-used pre-registration; no sweeping. Apples-to-apples with the prior Bayesian-vs-LLM comparison on Elder. |
| 2026-04-29 | Pre-committed three-tier pass criteria (replication, BO-vs-random, walk-forward) | Each tier isolates a different question; failure at one yields different remediation paths, not a single non-viable verdict. |

## Open questions

- Should we keep the friend's `OPERATOR_OVERRIDES` (`quote_size=2`,
  `max_inventory=10`) or re-derive them from scratch? Friend's pins are
  calibrated to his live pilot's actual sizing. We don't have a live
  pilot. **Default: keep his pins for the replication phase; revisit
  for our own paper deployment if criteria 1-4 pass.**
- The friend's simulator includes a `MM_PAIR_LOOKAHEAD_TRADES=50`
  detector that skips adverse haircut on fills that pair within 50
  trades. Calibrated against his live data. Our walk-forward fold may
  produce different pair-time distributions; if so, this constant is a
  hidden free parameter masquerading as a constant. Flag for
  audit during the deep-dive.
- Walk-forward fold construction: hash-by-event (random) vs. time-disjoint
  (events sorted by start time, sequential folds). **Default: time-disjoint
  by `expiration_time`, since the relevant generalization axis is
  forward-in-time.**
- Does the friend's strategy still work if the search were also given
  budget to deviate from `OPERATOR_OVERRIDES`? Out of scope for this
  candidate (would expand the search space and break apples-to-apples).
  Could be a future variant.

## Pointers

- Sibling implementation: `~/workspace/other-trading-projects/kalshi-autoagent/strategies/market_maker.py`
- Sibling sports handoff: `~/workspace/other-trading-projects/kalshi-autoagent/strategies/market_maker_sports_handoff.md`
- Sibling MM expansion plan: `~/workspace/other-trading-projects/kalshi-autoagent/MM_EXPANSION_PLAN.md`
- Bayesian harness template: [`scripts/elder_bayesian_search.py`](../../../scripts/elder_bayesian_search.py)
- Walk-forward template: [`scripts/walk_forward_backtest.py`](../../../scripts/walk_forward_backtest.py)
- Data tree: [`platform/data-pipeline.md`](../../platform/data-pipeline.md)
- Friend's strategy summary in our framework: [`reference/sibling-projects.md`](../../reference/sibling-projects.md) §what's already covered
- Charter axioms: [`charter/axioms.md`](../../charter/axioms.md) §5 (LLM categorical-only), §7 (directional is fine), §8 (know what's been done)
- Methodology: [`reference/methodology.md`](../../reference/methodology.md) (the six non-negotiables)
- Optimal-MM literature: [`reference/literature-survey.md`](../../reference/literature-survey.md) §2.3 (Avellaneda–Stoikov, Glosten–Milgrom, Cartea–Jaimungal–Penalva, RL MMs)
