---
id: 15
name: Elder templates + Bayesian optimization
status: backtest
verdict: pending
last-update: 2026-04-25
related-components: []
parent-candidate: 00
---

# Candidate 15: Elder Templates + Bayesian Optimization

## Status snapshot

- **Stage:** backtest
- **Verdict:** pending — reopening at the backtest stage with Bayesian
  optimization in place of the LLM, after the fresh-eyes review surfaced
  that two of the original rejection criteria were self-imposed
  constraints (axiom mis-application), not empirical findings.
- **Next move:** Run pre-registered Bayesian-vs-random comparison on the
  same 6-D parameter space the original LLM lost on; if Bayesian beats
  random by a meaningful margin AND walk-forward survives, escalate to
  paper. Otherwise: reject for the *right* reason this time.

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

(In progress — this is the active stage.)

Implementation work to do:

1. Add `scripts/elder_bayesian_search.py` mirroring the original LLM
   harness but swapping the proposal loop for `skopt.Optimizer`.
2. Persist results to a new SQLite table in `data/prospector_oracle.db`
   (parallel to the existing oracle random results) so they're
   cross-comparable.
3. Run the locked-hyperparameter search.
4. Walk-forward top-10 Bayesian configs via existing
   `scripts/walk_forward_top_configs.py`.
5. Compare against the existing 2000-config random baseline + the
   archived LLM run.
6. Decide pass/fail per the pre-committed criteria.

Estimated effort: ~3-5 days of focused work (most of the harness
already exists; the net-new is the Bayesian optimizer wrapper + the
result-persistence pattern).

## Paper portfolio

(Empty until backtest passes.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Candidate created as reformulation of [`00`](00-elder-templates.md) | Fresh-eyes review surfaced that 2 of 3 original rejection criteria (LLM-doesn't-fit, directional-not-structural) were self-imposed framework errors, not empirical findings. Third criterion (trade sparsity) is real but worth testing whether Bayesian opt can find configs robust enough to survive it. |
| 2026-04-25 | Status: backtest, pending | Per user direction; the harness + templates are in place, the Bayesian optimizer is the implementation gap |
| 2026-04-25 | Pre-registered Bayesian optimizer choice (skopt GP + EI) | Lock in one well-validated optimizer; no kernel/acquisition sweeping — that would re-introduce selection bias |
| 2026-04-25 | Two pre-committed pass criteria + two kill criteria | Make the test falsifiable; ensure that if Bayesian also fails, the rejection is on real grounds (trade-sparsity is structural) |

## What this validates

- **If candidate 15 passes:** Elder templates have real edge after
  competent optimization, AND we've conclusively learned that the
  original LLM-vs-random finding was an LLM-as-optimizer issue (not an
  Elder-templates issue). Two distinct learnings.
- **If candidate 15 fails on Bayesian-vs-random:** the score landscape
  is too noisy for *any* optimizer to find structure. Templates
  themselves are not informative. Confirms candidate 00's original
  rejection but for a deeper reason.
- **If candidate 15 fails on walk-forward but passes Bayesian-vs-random:**
  trade-sparsity is the binding constraint. Future work: higher-density
  template variants (sub-4h timeframes) — open as a new candidate.

## Pointers

- Parent candidate: [`00-elder-templates.md`](00-elder-templates.md)
- Charter axioms (LLM categorical-only): [`../../charter/axioms.md`](../../charter/axioms.md) §5
- Charter axioms (directional is fine): [`../../charter/axioms.md`](../../charter/axioms.md) §7
- Methodology discipline: [`../../reference/methodology.md`](../../reference/methodology.md)
- Original design specs: [`../../implementation/archived/`](../../implementation/archived/)
- Original walk-forward analysis: see decision-log entry on candidate 00
