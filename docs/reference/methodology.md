# Methodology

> Validation rigor that applies across every candidate's statistical
> examination, backtest, and paper-portfolio stages. Pre-registration,
> hard date splits, null-shuffle benchmarks, locked hyperparameters,
> pre-committed pass criteria, full-distribution reporting.

This is the project-wide testing discipline, lifted out of
`implementation/methodology.md` (which was scoped to PM Underwriting) so
it applies to every candidate.

---

## The non-negotiables

These six rules apply to every statistical examination, backtest, and
paper-portfolio kill-criterion check. Skipping any of them invalidates
the conclusion regardless of how clean the result looks.

### 1. Pre-register hyperparameters

Every continuous or discretionary knob (model choice, lookback, threshold,
date split, regression horizon, etc.) is **locked in code as module-level
constants before any test fold is touched**. No CLI flags for the locked
knobs. If a value must change after train-fold exploration, it's a new
commit with a changelog entry — not a silent re-run.

The minimum table that lives at the top of the test script:

```python
# Pre-registered hyperparameters — locked, no sweeps
KNOB_1 = value_1   # rationale
KNOB_2 = value_2   # rationale
...
```

### 2. Hard date split

Train and test folds are split by a fixed timestamp known before any data
is inspected. The test fold is **run exactly once at the end**. If you
peek, the test fold is contaminated and must be discarded; at that point
either use a fresh fold or abandon the test.

Train-fold exploration is unrestricted — researcher intuition earns its
keep on the train fold. The discipline lives at the train/test boundary,
not inside train.

### 3. Null-shuffle benchmark

Within the test fold, randomly permute the relevant pairing (event ↔
timestamp, candidate ↔ outcome) and re-run the full pipeline. Real
signal must beat the null benchmark by a pre-registered ratio
(typically 3×) on the primary metric.

If the null benchmark produces results comparable to the real signal,
the apparent edge is reference-model noise or selection bias, not
exploitable signal.

### 4. Pre-commit pass criteria

Before the test fold runs, write down the specific thresholds that
constitute "pass":

- Specific values, not "good Sharpe"
- Multiple criteria when appropriate (each must hold)
- Distinguish "pass" from "needs-iteration" (per
  [`stages-and-verdicts.md`](stages-and-verdicts.md))

If the pre-commit list is missing or vague, the result has no falsifiable
interpretation.

### 5. Full-distribution reporting

Any intermediate metric that has a natural distribution (gap magnitudes
across tuples, Sharpe across folds, P&L per trade) is reported as a
distribution, not a summary statistic. No "best of N" reporting without
N. No "we picked the best run" without the full list.

This is the rule that prevents post-hoc cherry-picking from sneaking back
in after pre-registration.

### 6. Document hyperparameter changes inline

If a hyperparameter is changed mid-experiment (e.g., a discovered data-
quality issue forces a filter), that change is committed with a rationale
*before* re-running. The prior result is not retroactively rewritten;
it's a known-superseded pre-registration with a documented reason.

---

## Recurring validation tools

### Wilson confidence intervals

For binomial proportions (resolution rates, win rates, beat-line rates):
use Wilson score intervals, not the naive normal approximation. Wilson
intervals are bounded to [0,1] and well-behaved at small samples and
extreme proportions:

```
center = (p̂ + z²/2n) / (1 + z²/n)
spread = z × √((p̂(1-p̂) + z²/4n) / n) / (1 + z²/n)
CI = [center − spread, center + spread]
```

with `p̂ = success/n` and `z = 1.96` (95%). See
[`components/calibration-curves.md`](../components/calibration-curves.md) §Wilson
for the canonical implementation.

### Walk-forward across non-overlapping windows

For backtest: split history into N non-overlapping windows. Run train →
test in each. Require sign-stability and within-±50% magnitude stability
across folds. A single-fold result is not a backtest; it's a spot check.

### Regime characterization

When a candidate fails or shows ambiguous results, ask: *was the test
period a homogeneous regime, or did it span multiple regimes that should
be analyzed separately?* The #4 narrative-spread Phase 3 finding ("Oct
2025 was an active rate-cut repricing cycle; Sep and Dec settled")
exemplifies regime conditioning.

Regime conditioning is **explicitly post-hoc** and must be flagged as
such — it's a hypothesis for re-pre-registration on more data, not a
rescued conclusion on the original data.

---

## What this discipline catches

Three categories of false-positive findings that pre-registration prevents:

1. **Hyperparameter overfit.** Try 5 σ models, pick the best, report
   without disclosing the search. Pre-registration locks the σ model
   before results are seen.
2. **Fold contamination.** Look at test results, tweak the model, re-run
   on the same test fold, declare success. The "test fold seen exactly
   once" rule prevents this.
3. **Reference-model noise.** Apparent edge is just the reference
   distribution being mis-specified. The null-shuffle benchmark forces
   the real signal to beat structurally-similar noise.

The PM Underwriting Phase 1 validation, the #4 Phase 1/3 narrative-spread
work, and the #10 Phase 1 vol-surface work all hit some of these traps —
the discipline caught them cleanly each time. Several candidates that
*looked* tradeable on first inspection turned out to be measurement
artifacts or formulation-specific failures rescuable as variants. Those
are the ones the discipline is designed to surface.

---

## Methodology by stage

| Stage | Discipline applies |
|---|---|
| ideation | Light — just need axiomatic fit + clear kill criterion. Methodology kicks in at the next stage. |
| deep-dive | Medium — the deep-dive specifies *what* will be tested. The test plan must be falsifiable. |
| statistical-examination | **Full** — all six rules above. This is the gate. |
| backtest | Full — walk-forward across non-overlapping windows; regime check |
| paper-portfolio | Full — pre-committed kill criteria; live monitoring; CLV instrumentation |
| live-trading | Full + risk overlays — pre-committed circuit breakers; weekly review |

---

## When discipline conflicts with progress

Sometimes the discipline says "you can't conclude X from this data." The
right response is **not** to relax the discipline — it's to either get
more data or formally accept "needs-iteration" status with a documented
rescue path.

Examples we've actually faced:

- **#4 Phase 3 (15-min Coinbase data, 5× train/test sample size).** Sign
  correct, magnitude near zero, t-stats 0.3-1.1. The discipline said
  "thesis is alive but underpowered." We classified as
  `rejected/needs-iteration` with explicit rescue paths (more events,
  finer cadence). Did NOT call it `non-viable` and did NOT retro-fit a
  finer hypothesis.
- **#10 Phase 1 D1 finding.** Convergence thesis dead, but D1 wedge
  passed. Discipline said the D1 finding was real but was the same edge
  PM already exploits. Reframed candidate to `absorbed`, folded the new
  info (delta-hedgeability) into a [component](../components/hedging-overlay-perp.md)
  rather than retro-fitting a new convergence formulation.

In both cases the discipline produced a *more useful* outcome than
relaxation would have.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Methodology discipline formalized for #10 vol-surface pre-registration | Twelve continuous knobs in the spike scope; without lockdown, motivated researcher could manufacture an edge |
| 2026-04-22 | Six non-negotiables codified | Generalizes the #10 pre-registration discipline as project-wide rule |
| 2026-04-25 | Doc moved from `implementation/methodology.md` to `reference/methodology.md` | Reorg: this is project-wide, not PM Underwriting-specific |
| 2026-04-25 | PM-specific empirical content moved to [`01-pm-underwriting-lottery.md`](../rd/candidates/01-pm-underwriting-lottery.md) | This doc is the discipline; the candidate doc is the data |
