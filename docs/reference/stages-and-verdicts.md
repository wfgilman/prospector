# Stages and Verdicts — The Strategy Pipeline

> The formal definition of how strategy candidates move from idea to live
> capital. All `rd/candidates/` files speak this language.

Every strategy candidate has two state dimensions:

- **Stage** — *where* the candidate is in the pipeline (procedural)
- **Verdict** — *how* it's doing at that stage (judgment)

Both are recorded in the candidate's YAML frontmatter and updated together.
A stage transition without an updated verdict is a bug.

---

## Stages

```
ideation → deep-dive → statistical-examination → backtest → paper-portfolio → live-trading
                                                                                ↓
                            absorbed (folded into another strategy) ←────  rejected
```

| Stage | Entry criterion | Required artifact | Exit criterion |
|---|---|---|---|
| **ideation** | New idea logged | One-paragraph rationale + axiomatic fit + expected-edge mechanism | Promoted by user/agent if axiom-fit + clean kill criterion exist + no operational disqualifier |
| **deep-dive** | Promoted from ideation | Full prospectus: mechanism, data needs, β maps if applicable, hardware budget, fee structure, who's the marginal trader on the other side | Pre-registered hypothesis + statistical-exam plan with locked hyperparameters and pre-committed pass thresholds |
| **statistical-examination** | Deep-dive complete | Pre-registered hypothesis, locked hyperparameters, null-benchmarks, fully-specified pass criteria | Either thesis falsified (→ rejected/needs-iteration) OR thesis validated on test fold (→ backtest) |
| **backtest** | Stat-exam passes | Walk-forward results across non-overlapping windows; regime-stability check; full-distribution P&L characterization | Sharpe ≥ threshold + stability across windows + no catastrophic drawdown regime |
| **paper-portfolio** | Backtest passes | Live paper book daemon, dashboard panel, CLV instrumentation, drift-vs-prediction monitoring | 30-day paper Sharpe ≥ threshold + calibration holds within ±X pp + beat-line rate ≥ Y% |
| **live-trading** | Paper passes | Live capital deployed (Phase 4 small → scale), weekly review cadence | Continuous; sized up over time |
| **rejected** | Failed at any stage AND no rescue path | Cause-of-death + explicit "no variant, overlay, or scale change could rescue this because [reason]" | (terminal) |
| **absorbed** | Finding folded into another strategy | Pointer to the absorbing candidate | (terminal) |

Stages are strictly forward-progressing for active candidates. A candidate
in `paper-portfolio` that fails its kill criterion goes to `rejected` or
`needs-iteration` — it does not regress to `backtest`. If a regression is
warranted (e.g., the candidate is reformulated as a variant), open a *new*
candidate file pointing at the parent.

---

## Verdicts

| Verdict | Meaning | What it implies |
|---|---|---|
| **pending** | Currently in this stage; no terminal decision yet | Continue working; check kill criterion regularly |
| **needs-iteration** | Failed at this stage but a variant/overlay/scale change might rescue | Decision-log entry must specify *which* iteration is being attempted |
| **viable** | Passed this stage; candidate for promotion | Update stage on next session |
| **non-viable** | Definitively killed | Stage moves to `rejected`; rescue paths explicitly ruled out (see below) |

### The bar for `non-viable`

To verdict a candidate as `non-viable`, the decision-log entry must include
explicit reasoning of the form:

> No variant, overlay, or scale change could rescue this because **[specific reason]**.

Examples of acceptable reasoning:

- "The phenomenon doesn't exist at any cadence we tested (1m, 5m, 15m, 1h, daily); no infra investment closes the gap."
- "The audience-mismatch hypothesis is structurally absent — both sides are institutional with shared analytical infrastructure, so no scale change makes the lag persistent."
- "Throughput is fundamentally capped at N events/year by the underlying calendar; even a 10× edge per event compounds to insufficient annual P&L."

Examples that **don't** clear the bar (and would default to `needs-iteration` instead):

- "Our specific formulation didn't work" — open the question of reformulation
- "Sample size was too small" — the question is whether more sample is reachable
- "The test failed at our cadence" — the question is whether finer cadence is reachable

The point of the high bar is to prevent prematurely killing a real edge
because of a measurement choice or formulation choice. A `needs-iteration`
verdict keeps the candidate alive in the queue with a specified rescue path.
A `non-viable` verdict closes it forever (unless explicitly reopened, which
requires its own decision-log entry).

---

## Status × verdict combinations

Not every combination is sensible. The valid transitions are:

| Stage | Pending | Needs-iteration | Viable | Non-viable |
|---|---|---|---|---|
| ideation | ✓ default | ✓ rare | ✓ promote to deep-dive | ✓ → rejected |
| deep-dive | ✓ default | ✓ if scope unclear | ✓ promote to stat-exam | ✓ → rejected |
| statistical-examination | ✓ default | ✓ retry with new hypothesis | ✓ promote to backtest | ✓ → rejected |
| backtest | ✓ default | ✓ walk-forward variant | ✓ promote to paper | ✓ → rejected |
| paper-portfolio | ✓ default | ✓ sizing/scope tweak | ✓ promote to live | ✓ → rejected |
| live-trading | ✓ default | ✓ rare — scale change | (n/a) | ✓ → rejected |
| rejected | (n/a) | (n/a) | (n/a) | ✓ terminal |
| absorbed | (n/a) | (n/a) | (n/a) | (n/a, terminal) |

A `paper-portfolio` candidate marked `needs-iteration` typically gets a new
sibling candidate file (e.g., "PM Underwriting · Insurance variant"), with
a decision-log entry on the parent pointing at the variant.

---

## Required artifacts per stage

A stage transition is incomplete until the artifact for that stage exists.
This is what prevents "we promoted it but haven't actually written down what
the deep-dive concluded" drift.

| Stage | Required artifact in candidate file |
|---|---|
| ideation | Filled-in `## Ideation` section: 1-paragraph rationale, axiomatic fit, expected edge mechanism, why-now |
| deep-dive | Filled-in `## Deep dive` section: full prospectus (target ~500-2000 words; structure varies by strategy type) |
| statistical-examination | Filled-in `## Statistical examination` section: hypothesis, locked hyperparameters table, kill criteria, null benchmark spec |
| backtest | Filled-in `## Backtest` section: walk-forward results, per-fold breakdown, full distribution stats |
| paper-portfolio | Filled-in `## Paper portfolio` section: daemon config, kill criterion, current state, links to dashboard tab |
| live-trading | Filled-in `## Live trading` section: deployment config, sizing, review cadence |

If you find yourself promoting a candidate without the artifact, write the
artifact first. If the artifact requires data you don't have yet, the
candidate stays in its current stage until the data arrives.

---

## Reading the verdict bar

Some questions to ask before assigning a verdict:

| Question | If answer is "no" → |
|---|---|
| Does the empirical finding clearly contradict the pre-registered hypothesis? | `pending` (need more data) |
| Did we lock all hyperparameters before running the test? | `pending` (re-pre-register, re-run) |
| Was the null-shuffle distinguishable from the real signal? | `non-viable` for *this formulation* — but consider reformulation before declaring `non-viable` overall |
| Is the failure mode specific to our formulation, our cadence, our scale, or our universe? | `needs-iteration` with the specific rescue path documented |
| Have we explicitly ruled out variants, overlays, and scale changes? | `needs-iteration` until that case is made |
| Does promoting this require an artifact we haven't built? | `pending` until artifact exists |

---

## Decision-log discipline

Every stage transition or verdict change generates an entry in the
candidate's decision log. The entry has three fields:

- **Date** (ISO YYYY-MM-DD)
- **Decision** (what changed)
- **Rationale** (why — including the specific empirical evidence or reasoning that justified the change)

Decision logs are append-only. We never edit prior entries; if a prior
decision is being reversed, that's a new entry that explicitly references
the prior one.
