# R&D — Strategy Pipeline

> Append-only catalog of every strategy candidate. One file per candidate;
> uniform stages; rigorous verdicts.

This is where every strategy idea lives, from the moment it's logged
through deep-dive, statistical examination, backtest, paper portfolio, live
trading — or rejection. We do not delete candidates. We promote, demote,
reject, or absorb them; the file stays.

## How to navigate

- **[`pipeline.md`](pipeline.md)** — the cross-strategy status table. Start
  here for "where are we?"
- **[`candidates/`](candidates/)** — one file per candidate, numbered by
  ideation order so the catalog reads chronologically.

## The pipeline

Every candidate moves through these stages:

```
ideation → deep-dive → statistical-examination → backtest → paper-portfolio → live-trading
                                                                                ↓
                            absorbed (folded into another strategy) ←────  rejected
```

Stage definitions, entry criteria, exit criteria, and verdict types are in
[`../reference/stages-and-verdicts.md`](../reference/stages-and-verdicts.md).
The bar for **non-viable** is deliberately high — every rejection requires
explicit reasoning that no variant, overlay, or scale change could rescue
the candidate.

## Anatomy of a candidate file

Every candidate file uses the same structure:

```markdown
---
id: NN
name: <short name>
status: ideation | deep-dive | stat-exam | backtest | paper | live | rejected | absorbed
verdict: pending | needs-iteration | viable | non-viable
last-update: YYYY-MM-DD
related-components: [equal-sigma-sizing, calibration-curves, ...]
---

# Candidate NN: <name>

## Status snapshot
- **Stage:** <current stage>
- **Verdict:** <current verdict + why>
- **Next move:** <one-line action>

## Ideation
Origin, axiomatic fit, expected edge mechanism, why-now.

### Prior art / existing applications
Required (per [axiom 8](../charter/axioms.md#8-know-whats-already-been-done)):
- Where has this concept (or a close analogue) been applied before?
  Cross-reference [`../reference/literature-survey.md`](../reference/literature-survey.md)
  and/or [`../reference/sibling-projects.md`](../reference/sibling-projects.md).
- What did those applications find?
- What's specifically different about our application — scale, cadence,
  substrate, combination, formulation?
- If a real search turned up nothing, say so explicitly.

## Deep dive
(Empty until promoted from ideation.)

## Statistical examination
(Empty until promoted from deep-dive. Pre-registered hypothesis,
locked hyperparameters, kill criteria.)

## Backtest
(Empty until promoted from stat-exam. Walk-forward results.)

## Paper portfolio
(Empty until promoted from backtest. Live paper book results.)

## Live trading
(Empty until promoted from paper.)

## Decision log (append-only)
| Date | Decision | Rationale |
|---|---|---|
```

The state of the candidate is encoded in **frontmatter** (machine-parseable)
and the **status snapshot** (human-readable). The stage sections are filled
in as the candidate progresses. Empty sections are kept as placeholders so
the structure is consistent and the gaps are visible.

## Adding a new candidate

1. Pick the next available ID from `pipeline.md`.
2. Copy the template above into `candidates/NN-name.md`.
3. Fill in **Status snapshot** + **Ideation** sections; leave the rest empty.
4. Add a row to `pipeline.md`.
5. Add an entry to the candidate's decision log.

Promoting a candidate to the next stage requires:
- An entry in the candidate's decision log explaining what evidence justified the promotion
- Update of frontmatter `status` + `last-update`
- Update of `pipeline.md`
- Filling in the new stage's section (even if it's "in progress; no results yet")

Rejecting a candidate as **non-viable** requires the additional explicit
finding: *"No variant, overlay, or scale change could rescue this because
[specific reason]."* Without that, the verdict is `needs-iteration`, not
`non-viable`.
