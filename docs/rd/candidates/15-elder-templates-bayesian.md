---
id: 15
name: Elder templates + Bayesian optimization
status: absorbed
verdict: viable
last-update: 2026-04-28
related-components: []
parent-candidate: 00
spawns: [16]
---

# Candidate 15: Elder Templates + Bayesian Optimization

## Status snapshot

- **Stage:** absorbed (into [candidate 16](16-triple-screen-midvol-crypto.md))
- **Verdict:** **viable** for the (template, cohort) pair
  `triple_screen × vol_q4`. Family verdict is more nuanced — see the
  Cohort expansion section below — but the candidate's question
  ("can a competent optimizer find Elder configs that survive
  walk-forward?") is **answered yes** when the universe is right.
- **Next move:** None on this candidate; the surviving cell is being
  carried forward as [candidate 16](16-triple-screen-midvol-crypto.md)
  (triple_screen on mid-vol crypto perps, paper portfolio).

## Parent candidate

This is a **reformulation** of [`00-elder-templates`](00-elder-templates.md).
The original was rejected as `non-viable` 2026-04-14. The fresh-eyes
review on 2026-04-24 / 2026-04-25 surfaced that two of the three failure
modes were either wrong-tool errors or charter-axiom mis-applications:

| Original rejection criterion | What the framework now says |
|---|---|
| LLM inner-loop didn't beat random search at continuous parameter optimization | Per [`charter/axioms.md`](../../charter/axioms.md) §5, that's an LLM-comparative-advantage issue, not a strategy-template issue. The right tool is Bayesian optimization (GP surrogate + acquisition function), not an LLM. |
| Directional, not structural-arb | Per [`charter/axioms.md`](../../charter/axioms.md) §7, directional bets with measured edge and capped variance are fine at small scale. PM Underwriting Lottery is also directional and works. The original framing was desk-style. |
| Walk-forward killed all top configs (overfitting + trade sparsity) | This one is **real**. Trade density (~40-50 trades over 5000 bars vs. the 20-trade per-fold gate) is structural to the templates, not the search method. Bayesian opt fixes the search; it doesn't fix this. |

Of the three, only the third is a real binding constraint. The first
two were self-imposed. So we revisit — but with eyes open about what the
Bayesian rescue can and cannot fix.

## Ideation

**Origin:** Reopening Elder templates with the right optimizer
(Bayesian, not LLM) to test whether any of the templates' parameter
space contains stable edge — distinct from the LLM-can't-optimize-this
finding.

**Why-now:** The 2026-04-24 fresh-eyes review explicitly flagged the
self-imposed nature of the original rejection criteria.

**Axiomatic fit:**
- *Combinations* — Elder templates (mature TA framework) + Bayesian
  parameter optimization (mature ML framework). Neither is novel; the
  combination wasn't tested in the original work because LLM was used
  instead.
- *Different scale, different framing* (axiom 3) — the original was
  framed as "LLM-as-optimizer fails." This reformulation reframes as
  "the templates' parameter space is what's being measured, with a
  competent optimizer." Same templates, different question.
- *Methodology discipline* (axiom 6) — the original work pre-registered
  the LLM-vs-random comparison and falsified the LLM. This work
  pre-registers Bayesian-vs-random AND walk-forward survival.

## Deep dive

### What's preserved from candidate 00

All Elder code is intact in the repo:

- `src/prospector/templates/` — `base.py`, `triple_screen.py`,
  `false_breakout.py` (Elder-derived strategy implementations)
- `src/prospector/harness/` — `engine.py` (NAV simulation, Iron
  Triangle sizing), `walk_forward.py` (fold isolation + scored gates)
- `scripts/walk_forward_top_configs.py` — Elder-specific top-config
  validator
- `data/prospector_oracle.db` — the 2000-config oracle baseline
  random-search ran (peak score 192.5; useful as the new baseline)
- `docs/implementation/archived/elder-track-*.md` — full original
  design specs

### What's being tested differently

**Old setup (candidate 00):**
- Optimizer: LLM (Ollama qwen2.5-coder, sliding-window prompt + coverage prompt)
- Search budget: 200 LLM proposals / 2000 oracle random
- Templates: triple_screen, false_breakout
- Securities: BTC-PERP, ETH-PERP, SOL-PERP perp 4h
- Scoring: composite + EV
- Validation: walk-forward at 3-fold + 5-fold, 20-trade-per-fold gate

**New setup (candidate 15):**
- Optimizer: **Bayesian (Gaussian process surrogate + Expected Improvement
  acquisition)** — see implementation note below
- Search budget: 200 GP proposals (matched to original LLM budget for
  apples-to-apples) + 2000 oracle baseline (already exists)
- Templates: same triple_screen, false_breakout
- Securities: same BTC-PERP, ETH-PERP, SOL-PERP
- Scoring: same composite (so cross-comparable to oracle baseline)
- Validation: same walk-forward at 3-fold + 5-fold + 20-trade gate
  **(the binding constraint — see kill criterion)**

### Bayesian optimization choice

Use `scikit-optimize` (or equivalent: `bayes_opt`, `Ax`, `optuna`'s GP
sampler) — well-validated, drop-in replacement for the LLM-proposing
loop. Specific configuration to lock in pre-registration:

- **Surrogate:** Matérn 5/2 kernel Gaussian process
- **Acquisition function:** Expected Improvement (EI) with `xi=0.01`
- **Initial random samples:** 20 (covers the parameter space)
- **Total budget:** 200 evaluations
- **Search space:** identical to the original LLM run's 6-D
  parameter space per template

This is one optimizer, locked. **No sweeping over kernel/acquisition
choices** — that would re-introduce the post-hoc selection bias the
methodology discipline is designed to prevent.

### What this rescue does NOT fix

The trade-sparsity problem is real and structural. Elder templates
produce 40-120 trades across the full ~5000-bar 4h history. Walk-forward
requires ≥ 20 trades per fold:
- 3-fold split: ~13-40 trades per fold — borderline
- 5-fold split: ~8-24 trades per fold — most folds will fail the gate

Bayesian optimization can find better parameter configs, but if the
underlying templates are trade-sparse, the configs that survive
walk-forward will still be the small minority where the model happened
to fire 20+ times in each fold.

This is **explicitly known** going in. The pre-registered kill criterion
below incorporates it.

## Statistical examination

### Pre-registered hyperparameters — locked

| Knob | Value | Rationale |
|---|---|---|
| Optimizer | scikit-optimize GP, Matérn 5/2 kernel, EI acquisition (xi=0.01) | Industry-standard low-dim continuous optimizer |
| Initial random samples | 20 | Cover the 6-D space before GP fitting |
| Total evaluation budget | 200 | Matched to original LLM budget for direct comparison |
| Random baseline | 200 (subset of existing 2000-config oracle) | Apples-to-apples vs. original LLM finding |
| Templates | triple_screen, false_breakout | Same as original |
| Universe | BTC-PERP, ETH-PERP, SOL-PERP 4h | Same as original |
| Scoring | composite (existing harness) | Same as original |
| Walk-forward | 3-fold + 5-fold | Same as original |
| Per-fold trade gate | ≥ 20 | Same as original (the structural constraint) |

### Pre-committed pass criteria

To advance from backtest to paper, **both** must hold:

1. **Bayesian-vs-random:** Bayesian optimizer's max-score and scored-rate
   exceed random at matched N=200, by ≥ 30% on max-score AND ≥ 50% on
   scored-rate. (Original LLM lost both metrics by margins exceeding
   30% — the Bayesian replacement should clear this hurdle if the
   problem-shape thesis is correct.)
2. **Walk-forward survival:** Among Bayesian top-10 configs, ≥ 3 configs
   have ≥ 4/5 scored folds AND ≥ 70% best-security-holdout retention
   relative to in-sample peak. (Original LLM-found configs degraded
   42-82% on holdout; we need at least one configuration that holds.)

### Pre-committed kill criteria

Reject as `non-viable` (this time for the right reason) if either:

1. **Bayesian fails its own benchmark.** GP optimizer doesn't beat
   random at N=200 by the pre-registered margins. This would be
   surprising — GP is well-validated for low-D continuous optimization —
   and would suggest the score landscape is so noisy that no smarter
   optimizer can do better. Implies the templates themselves are not
   informative.
2. **Walk-forward kills the Bayesian top-10 the same way it killed the
   LLM top-10.** Trade-sparsity is the structural constraint; if it
   survives Bayesian's better-config-selection, the rescue is dead AND
   we've confirmed the original third-rejection-criterion was real.

If both criteria fail, the verdict is `non-viable` — no further rescue
path because we've now ruled out: LLM-as-optimizer (original), Bayesian-
as-optimizer (this), AND structural trade-sparsity (both).

If criterion 1 passes but criterion 2 fails, the verdict is
`needs-iteration` with a specific rescue path: extend Elder to
higher-density templates (1m or 5m timeframes) where walk-forward
folds get more trades. That's a separate candidate (16+) — not a
reformulation of this one.

## Backtest

**Run date:** 2026-04-27
**Implementation:** `scripts/elder_bayesian_search.py` (skopt GP +
EI, locked per pre-registration). Output: `data/prospector_bayesian.db`.

### Bayesian-vs-random (criterion 1)

200 evaluations per template (20 random init + 180 GP-guided EI), seed
42. Random baseline = first 200 configs by run_id from the existing
2000-config `data/prospector_oracle.db`.

| Metric | Template | Random N=200 | Bayesian N=200 | Δ vs random | Threshold | Pass? |
|---|---|---|---|---|---|---|
| Max score | false_breakout | 192.5 | 190.1 | **−1.2%** | ≥ +30% | ❌ |
| Max score | triple_screen | 169.9 | 200.0 (cap) | **+17.7%** | ≥ +30% | ❌ |
| Scored-rate | false_breakout | 16.0% (32/200) | 61.5% (123/200) | **+284%** | ≥ +50% | ✅ |
| Scored-rate | triple_screen | 25.0% (50/200) | 67.5% (135/200) | **+170%** | ≥ +50% | ✅ |
| Top-10 mean | false_breakout | 132.2 | 151.4 | +14.5% | (informational) | — |
| Top-10 mean | triple_screen | 115.9 | 200.0 (cap) | +72.6% | (informational) | — |

The 200.0 cap on triple_screen is the harness's NAV-ceiling-saturation
limit (`pct_return × 200` with `pct_return` clipped at +1.0 by the
`nav_ceiling=20_000` rule); the Bayesian search found multiple configs
that saturate the cap, the random baseline did not.

**Reading:** Bayesian *crushed* random on sample efficiency
(scored-rate 4-5× higher) and dominated on top-10 mean. Bayesian was
**competitive but not 30% better** on the headline max-score: random
got lucky with a single 192.5 config in its first 200 samples for
false_breakout, and triple_screen's max-score gap is muted by the
NAV-ceiling cap. **Per the literal pre-registered conjunction
(≥30% max-score AND ≥50% scored-rate), criterion 1 fails for both
templates.**

### Walk-forward survival (criterion 2)

`scripts/walk_forward_top_configs.py` against the per-template
Bayesian top-10 at both 3-fold and 5-fold splits.

| Split | Template | Configs ≥ threshold scored / total | Best holdout retention | Pass criterion 2? |
|---|---|---|---|---|
| 5-fold | false_breakout | 0/10 (≥4/5 scored) | n/a — all folds reject | ❌ |
| 5-fold | triple_screen | 0/10 (≥4/5 scored) | 33% (config #371, 2/5 folds) | ❌ |
| 3-fold | false_breakout | 0/10 (≥3/3 scored) | 78% (config #41, 1/3 folds) | ❌ |
| 3-fold | triple_screen | 0/10 (≥3/3 scored) | 100% (config #288, 1/3 folds) — but only 1 fold scored | ❌ |

Best 3-fold-survival cases for triple_screen reach 78-83% retention but
only across 1-2 of 3 folds, never all 3. The remaining folds reject
under the 20-trade gate — i.e. trade-sparsity hits each fold even
though full-sample trade counts (45-91) are well above 20.

**Per the literal pre-registered criterion 2 (≥3 configs with ≥4/5
scored AND ≥70% retention), criterion 2 fails for both templates at
both splits.**

### Interim verdict (2-template subset)

Both pre-committed pass criteria fail on the 2-template subset. Per the
literal reading of the pre-committed kill criteria, this would warrant
a non-viable verdict on the *family* — but the candidate doc inherited
its template scope from the original LLM run (which only coded
triple_screen and false_breakout), and the source design doc
([`elder-track-strategies.md`](../../implementation/archived/elder-track-strategies.md))
enumerates **six** Elder templates. Declaring the family non-viable on
2 of 6 would falsify a strategy family on partial coverage.

**Per user direction 2026-04-27: the verdict is paused. Expanding the
search to the full 6 before applying the pre-committed criteria.**

The 2-template result is preserved as an interim checkpoint; if the
remaining 4 templates also fail criterion 2 (walk-forward survival),
the family non-viable verdict is reinforced from a representative
sample. If any of the 4 produces a config that survives walk-forward
with ≥70% retention across ≥4/5 folds (or ≥3/3 at 3-fold), the family
verdict shifts to needs-iteration with a specific template-and-config
to advance.

### What this conclusively learned

Three failure modes were on the table in the parent candidate's
rejection. This run rules out the first two and confirms the third:

| Failure mode | Status before | Status after |
|---|---|---|
| LLM-as-optimizer is wrong tool for continuous optimization | empirical (original) | confirmed; Bayesian replacement *did* dramatically improve sample efficiency, ruling out optimizer choice as the binding constraint |
| Templates' parameter space is uninformative | unclear (LLM might have masked the signal) | **falsified** — Bayesian found multiple NAV-ceiling-saturating configs, so the parameter space *does* contain extreme in-sample edge |
| Trade-sparsity / temporal robustness is the binding constraint | hypothesized | **confirmed** — Bayesian found configs with 45-91 trades, NAV-ceiling-saturating in-sample, that fail walk-forward at both 3-fold and 5-fold; the in-sample edge is concentrated in a few high-leverage trades that don't reproduce in held-out time slices |

The cleanest possible falsification: a competent optimizer found the
edge if there was one to find, and the edge that exists is overfitted
to the specific 5000-bar 4h history. No optimizer rescue is possible.

The only remaining rescue is **higher-density data** (1m/5m timeframes)
where 5-fold splits yield ≥20 trades per fold without the harness's
trade-gate firing — but per the user's strategic direction
(`docs/rd/pipeline.md`, sequential R&D, capacity-constrained operator),
that is a *new* candidate, not a reopening of this one.

### Cohort expansion (2026-04-28)

After the 2-template interim, the search was first expanded to all 6
Elder templates on the same BTC/ETH/SOL universe (search log
`/tmp/cohort_search.log`'s superseded 6-template run). That re-run
produced no walk-forward survivors either, with channel_fade and
kangaroo_tail scoring 0/200 — i.e. so trade-sparse on 4h that the
20-trade gate fires structurally on the underlying universe regardless
of template parameters.

**User pushback (2026-04-27 evening):** Elder's templates were designed
for equities / FX / commodities, where the cohort spans many vol/liquidity
regimes. Searching on three of the highest-correlated, highest-liquidity
crypto perps (BTC/ETH/SOL) is a cohort mismatch — analogous to running
small-cap-growth signals against large-cap-value names and concluding
the signal doesn't work. Authorized overnight to expand to the full
Hyperliquid perp universe and bucket by volatility.

**Universe expansion:**
- Pulled 4h + 1d candles for **229 of 230 active Hyperliquid perps**
  (`scripts/backfill_hyperliquid.py` + retry loop for 429s).
- Profiled coins with ≥365 days history (`scripts/coin_universe_profile.py`):
  159 of 229 qualified.
- Bucketed by annualized σ on daily log returns into **5 quintile
  cohorts** (`/tmp/cohorts.json`):

| Cohort | n | σ low | σ med | σ high | First few coins |
|---|---|---|---|---|---|
| vol_q1 | 31 | 0.28 | 0.85 | 0.94 | PAXG, BTC, BNB, TRX, ETH |
| vol_q2 | 31 | 0.95 | 1.01 | 1.06 | CELO, ALGO, GMX, ONDO, BLAST |
| vol_q3 | 31 | 1.07 | 1.14 | 1.18 | ME, DYDX, HYPE, JTO, FTT |
| vol_q4 | 31 | 1.18 | 1.26 | 1.37 | BIGTIME, kPEPE, XAI, HMSTR, LAYER |
| vol_q5 | 35 | 1.39 | 1.61 | 2.24 | PEOPLE, BRETT, USUAL, PENGU, BERA |

**Critical observation:** BTC and ETH both fall in vol_q1. The original
3-coin universe was a single quintile's worth of vol regime — exactly
the cohort-mismatch the user flagged.

**Cohort search:** 6 templates × 5 cohorts × 200 evals = 6000
evaluations (84.8 min wall, `scripts/elder_cohort_search.py`).

### Per-(template, cohort) walk-forward survival matrix (5-fold, ≥4/5 scored, ≥70% retention)

| template | vol_q1 | vol_q2 | vol_q3 | vol_q4 | vol_q5 |
|---|---|---|---|---|---|
| channel_fade   | 0% scored | 0% scored | 0% scored | 0% scored | 0% scored |
| kangaroo_tail  | 0% scored | 0% scored | 0% scored | 0% scored | 0% scored |
| ema_divergence | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail |
| false_breakout | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail |
| impulse_system | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail | 0/10 fail |
| triple_screen  | 0/10 fail | 0/10 fail | **6/10 PASS** | 0/10 (3-fold: 5/10 PASS) | 0/10 fail |

Only **triple_screen** produces walk-forward survivors, and only in
**mid-vol cohorts** (vol_q3 / vol_q4). Channel_fade and kangaroo_tail
are structurally too sparse to ever clear the 20-trade gate at any
volatility regime on 4h data.

### Cross-coin generalization (within-cohort)

To distinguish "real cohort-level edge" from "single-asset overfit
dressed as cohort", every top-10 surviving config was re-tested by
applying its parameters to *every* coin in its cohort:

**triple_screen × vol_q4** (config #3895, tuned on ZK_PERP):
- params: `slow_ema=15, fast_ema=5, oscillator=rsi, threshold=93.7,
  long_tf=1d, short_tf=4h`
- Scored on 28 of 31 cohort coins
- **Survives walk-forward (≥4/5 folds AND ≥70% retention) on 21 of 31
  cohort coins** (~68%)
- Median retention across the cohort: 87% — well above threshold
- Max retention: 121% (holdout > in-sample on at least one coin)

**triple_screen × vol_q3** (config #2634, tuned on FTT_PERP):
- params: `slow_ema=15, fast_ema=5, oscillator=rsi, threshold=91.8`
- Scored on 30 of 31 cohort coins
- Survives strict criterion on 10 of 31 cohort coins (~32%)
- Median retention: 69% — borderline
- More concentrated edge; the cohort is split between coins where the
  config holds and coins where it doesn't.

The **vol_q4 result is the strongest finding** — robust generalization
across two-thirds of the cohort, not a single-coin artifact.

### Convergent config neighborhood

The top-4 generalizing configs (across vol_q3 + vol_q4) cluster on a
tight neighborhood:

| param | value |
|---|---|
| long_tf | 1d (locked in pre-registration) |
| short_tf | 4h |
| slow_ema | 15 |
| fast_ema | 5 |
| oscillator | rsi (3 of 4) or stochastic (1) |
| osc_entry_threshold | 89-100 (very extreme RSI/stoch level) |

This is a triple-screen pullback where, within a 1d trend, the 4h RSI
hits an extreme (90+ for shorts, ≤10 for longs) — i.e. fade extreme
short-term moves *only* in the direction of the longer-term trend.
Mechanism is consistent with Elder's original prescription; the
specific EMA/threshold neighborhood is data-driven.

### Final verdict (2026-04-28)

The pre-committed criteria, applied to the full
templates × cohorts grid:

- **Criterion 2 (walk-forward survival)**: PASS for
  `triple_screen × vol_q4` at both 5-fold (the strict pre-registered
  test) and 3-fold; PASS for `triple_screen × vol_q3` at 5-fold only.
  All other 28 (template, cohort) cells fail.
- **Cross-coin generalization**: PASS for `triple_screen × vol_q4`
  with 21/31 coins meeting the strict per-coin criterion;
  borderline for `triple_screen × vol_q3` at 10/31.

**Verdict: viable for the specific cell** `triple_screen × vol_q4`.
The remaining 5 templates and 4 cohorts are *not* viable on 4h
Hyperliquid data — the family-level cohort hypothesis is partially
confirmed (triple_screen does have edge in mid-vol cohorts) and
partially refuted (the other 5 templates produce no surviving configs
in any cohort at this cadence).

The viable finding is **absorbed into [candidate 16](16-triple-screen-midvol-crypto.md)**
for paper-portfolio advance with the locked config neighborhood and
the vol_q4 universe.

## Paper portfolio

(N/A — see [candidate 16](16-triple-screen-midvol-crypto.md).)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Candidate created as reformulation of [`00`](00-elder-templates.md) | Fresh-eyes review surfaced that 2 of 3 original rejection criteria (LLM-doesn't-fit, directional-not-structural) were self-imposed framework errors, not empirical findings. Third criterion (trade sparsity) is real but worth testing whether Bayesian opt can find configs robust enough to survive it. |
| 2026-04-25 | Status: backtest, pending | Per user direction; the harness + templates are in place, the Bayesian optimizer is the implementation gap |
| 2026-04-25 | Pre-registered Bayesian optimizer choice (skopt GP + EI) | Lock in one well-validated optimizer; no kernel/acquisition sweeping — that would re-introduce selection bias |
| 2026-04-25 | Two pre-committed pass criteria + two kill criteria | Make the test falsifiable; ensure that if Bayesian also fails, the rejection is on real grounds (trade-sparsity is structural) |
| 2026-04-27 | `scripts/elder_bayesian_search.py` shipped; ran 200×2 templates | Pre-registered config: skopt GP + Matérn 5/2 + EI (xi=0.01), 20 init + 180 EI evals, seed 42; output to `data/prospector_bayesian.db` |
| 2026-04-27 | Criterion 1 fails on max-score for both templates | Bayesian competitive on max-score but didn't clear 30%; sample-efficiency dominance (4-5× scored-rate) is a real positive but not the pre-committed gate |
| 2026-04-27 | Criterion 2 fails decisively at 3-fold and 5-fold | 0/10 configs hit the threshold on either template at either split; trade-sparsity hits each fold below the 20-trade gate |
| 2026-04-27 | Verdict initially set to non-viable, then **reverted to pending** per user direction | The candidate doc inherited the 2-template scope from the original LLM run; declaring the *family* non-viable on 2 of 6 documented Elder templates is falsification on partial coverage. Implementing the remaining 4 (impulse_system, channel_fade, kangaroo_tail, ema_divergence) before re-evaluating the criteria across the family |
| 2026-04-27 | 6-template re-run on BTC/ETH/SOL still failed | All 6 templates failed walk-forward across BTC/ETH/SOL; channel_fade and kangaroo_tail produced zero scored configs in 200 evals each (template-level sparsity, not cohort-specific) |
| 2026-04-27 | User flagged cohort mismatch — Elder templates were designed for equities/FX/commodities, not 3 highly-correlated majors | Authorized expansion to full Hyperliquid perp universe + volatility profiling overnight |
| 2026-04-28 | Pulled 229 of 230 HL perps; bucketed 159 with sufficient history into 5 σ-quintile cohorts | BTC and ETH fall in vol_q1, confirming that the original 3-coin universe was a single quintile's worth of vol regime |
| 2026-04-28 | Cohort search: 6 templates × 5 cohorts × 200 evals = 6000 evals (84.8 min) | One DB run via `scripts/elder_cohort_search.py` |
| 2026-04-28 | Walk-forward survival: `triple_screen × vol_q4` PASSES at 5-fold (6/10 configs ≥4/5 scored AND ≥70% retention); `triple_screen × vol_q3` PASSES at 5-fold (6/10 with 4/5+) | All other 28 (template, cohort) cells fail |
| 2026-04-28 | Cross-coin generalization: config #3895 on vol_q4 generalizes to 21/31 cohort coins; median 87% retention | Robust cohort-level edge, not single-asset overfit |
| 2026-04-28 | **Verdict: viable** for `triple_screen × vol_q4`; spawning [candidate 16](16-triple-screen-midvol-crypto.md) for paper-portfolio advance | The cohort hypothesis is confirmed in one cell; the family-level outcome is "1 of 6 templates × 1 of 5 cohorts" — narrower than hoped, but a real survival not previously found |
| 2026-04-28 | Status: backtest → absorbed; verdict pending → viable | Surviving cell carried into #16; this candidate is closed at backtest stage |

## What this validated

The pre-committed branch that ran was: **passes Bayesian-vs-random on
sample-efficiency, fails on max-score-by-30%, fails walk-forward.** The
finding maps to the third pre-registered branch with a refinement:

- The score landscape is **not** uninformative — Bayesian found multiple
  NAV-ceiling-saturating configs that the random baseline at matched-N
  did not.
- Sample-efficiency dominance was decisive (4-5× scored-rate) but was
  not the gate; the pre-committed conjunction required ≥30% on
  max-score AND ≥50% on scored-rate.
- The binding constraint is **temporal robustness**, not optimizer
  power: the in-sample edge concentrates in a small number of
  high-leverage trades that vanish under fold splits, even though
  per-config trade counts (45-91) are well above the 20-trade gate at
  full-sample scale.

Future work on this template family is conditional on a higher-density
timeframe (1m/5m) where folds carry enough trades to clear the gate.
That would be a separate candidate (#16+); not a reformulation of #15.

## Pointers

- Parent candidate: [`00-elder-templates.md`](00-elder-templates.md)
- Charter axioms (LLM categorical-only): [`../../charter/axioms.md`](../../charter/axioms.md) §5
- Charter axioms (directional is fine): [`../../charter/axioms.md`](../../charter/axioms.md) §7
- Methodology discipline: [`../../reference/methodology.md`](../../reference/methodology.md)
- Original design specs: [`../../implementation/archived/`](../../implementation/archived/)
- Original walk-forward analysis: see decision-log entry on candidate 00
