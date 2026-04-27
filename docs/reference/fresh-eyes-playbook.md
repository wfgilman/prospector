# Fresh-Eyes Playbook

> When and how to do strategic re-evaluation. The harness for staying out
> of the fog of implementation.

The user explicitly identified periodic strategic re-evaluation as a
discipline the project needs — not a one-off, not a rigid schedule, but
an invocable playbook the user runs when their spider-sense fires or
when a milestone suggests it's time. This doc is what gets executed when
"let's do a fresh-eyes review" is invoked.

---

## When to invoke

**Invoke proactively when:**
- The user's spider-sense fires ("we're getting off track")
- A candidate transitions stage (especially after a rejection or
  promotion to paper)
- A material external development is observed (e.g., HIP-4 mainnet,
  Kalshi product launch, regulatory shift)
- After ~1 month of pure implementation without strategic re-look
- The user has been deep on one piece for too long and is losing
  perspective

**Don't invoke when:**
- A specific tactical question is at hand (just answer the question)
- A candidate's pre-registered test fired (just report the result)
- The user is asking for a specific thing (just do that thing)

Strategic re-evaluation is a different mode from implementation. Treat
the invocation as a context switch.

---

## The axiom lens

Every fresh-eyes review re-examines the project through the
[charter axioms](../charter/axioms.md). The four originating axioms
shape the strategic questions; axiom 8 (literature review) shapes the
discipline applied to any new candidate the review surfaces:

1. **Novelty from new combinations of existing ideas.** What recent
   external developments suggest new combinations? Are we currently
   pursuing combinations that *seemed* novel but on reflection are
   crowded?
2. **Small-player advantages at small scale.** What are we filtering out
   because it looks too small? Where are desks structurally absent?
3. **Things that don't work at one scale work at another.** Are any
   recently-rejected candidates rescuable at a different scale, cadence,
   capital level, or formulation?
4. **Fresh eyes reveal what familiarity hides.** What self-imposed
   constraints have crept in? What outsider-obvious questions have we
   stopped asking because we've internalized the assumptions?
5. **Know what's already been done** (axiom 8). For any new candidate the
   review proposes, name the prior art — TradFi analogue, academic
   paper, sibling-project work — before logging it. A review that
   surfaces 5 candidates without prior-art anchoring is generating
   speculation, not insight.

---

## The seven-step procedure

### Step 1 — Read the most recent fresh-eyes review

Use it as the baseline. The first question is always: *did the prior
review's recommendations actually happen, and what did they show?*

If the prior review's "recommended next moves" were ignored, that's
information — either the user found a better path, or the review's
recommendations were wrong. Either way it's worth a beat to ask.

### Step 2 — Snapshot the live state

Concrete numbers, not narrative:

- Each paper book's NAV trajectory (3 days / 1 week / 30 days)
- Open-position count and category mix
- Realized win-loss record so far
- CLV reading on each book (run `python scripts/compute_clv.py`)
- Recent settlements (anything notable?)
- Daemon health (any tick failures? launchd showing exits ≠ 0?)

This is the empirical anchor. Conclusions should reference these numbers.

### Step 3 — Read the candidate pipeline

[`rd/pipeline.md`](../rd/pipeline.md) — the cross-strategy status table.
Note which candidates have moved since last review, which are stalled,
which are queued.

For any candidate that's been in `pending` for > 30 days without progress,
ask: *is this stalled because of bandwidth, or because the candidate has
quietly become uninteresting?* If the latter, consider re-classifying or
de-prioritizing.

### Step 4 — External-landscape scan

Read [`external-landscape.md`](external-landscape.md) and update with any
observed material developments since last review:

- Kalshi product launches / fee changes / position limit changes
- Polymarket / HIP-4 / Hyperliquid product or partnership news
- Regulatory developments (CFTC, SEC posture on prediction markets)
- Sibling-project shipments that change what we should/shouldn't build
- Notable new academic or industry findings on relevant strategy classes

For new external developments: which candidates are activated, which
deactivated, which need re-framing?

### Step 5 — Drift check

Compare time spent on implementation vs. strategic reading since last
review:

- Has the user been heads-down on one piece for too long?
- Have any pre-registered kill criteria fired without being honored?
- Are there decisions made under deadline pressure that deserve revisit?
- Is the project's effort distribution matching its stated priorities?

Drift is normal; the playbook is what catches it.

### Step 6 — Apply the axioms

For each axiom, ask the specific question:

| Axiom | Question to ask |
|---|---|
| Combinations | What two existing ideas could combine into a candidate we haven't logged? |
| Small-player | What 40-200 events/year strategy are we filtering out because it fails the desk-style throughput filter? |
| Different scale | What recently-rejected candidate could be rescued by a cadence/scale/scope change? |
| Fresh eyes | What self-imposed constraint has crept in that an outsider would question? |
| Prior art (axiom 8) | For any new candidate this review proposes — has it been done before, where, and what was the finding? |

These questions are not rhetorical — write down the answers.

### Step 7 — Output: 3-5 concrete next moves

Not exhaustive. **Concrete enough to execute next week.** Prioritized by
effort × leverage. Include:

- 1-2 immediate small actions (≤ 1 day each)
- 1-2 medium actions (1-2 weeks each)
- A "step away" option if appropriate
- Any recommended re-classification of pipeline candidates

Write the output as a new dated doc:
`docs/rd/fresh-eyes-review-YYYY-MM-DD.md` (NOT overwriting prior).

Brief verbal summary back to the user at the end of the session.

---

## What the output should look like

A fresh-eyes review doc has roughly this shape (~1,500-3,000 words):

```markdown
# Fresh-Eyes Review — YYYY-MM-DD

## Track-so-far evaluation
- What's working
- What to reconsider

## External landscape: <key change>
[Anything material from external-landscape scan]

## Self-imposed assumptions worth challenging
[3-5 specific items]

## New strategy candidates surfaced
[Tier 1 / Tier 2 / Tier 3 with one-line rationale each]

## Cross-discipline imports — fast list
[Brief; what's worth digging into later]

## Recommended next moves
[3-5 concrete, prioritized actions]
```

The 2026-04-24 review is the canonical example: surfaced HIP-4 (entirely
missed by the project), reframed PM Underwriting as lottery-vs-insurance,
generated 12 strategy candidates (T1-T12 → candidates 04-14).

---

## What the playbook is NOT

- **Not a status report.** Status is in [`rd/pipeline.md`](../rd/pipeline.md).
  The playbook generates *recommendations*, not summaries.
- **Not a backtest.** Empirical rigor lives in `methodology.md`.
- **Not a deep-dive on any one candidate.** It can recommend deep-dives
  but doesn't perform them.
- **Not a permission to expand the active R&D track count.** Per
  [`charter/philosophy.md`](../charter/philosophy.md), default is
  sequential R&D. The playbook may *propose* a new active track but
  promotion still requires user direction.

---

## Anti-patterns to avoid

- **"Looking deep at everything" mode.** Pick the top 3-5 things, not
  the top 30. The user's bandwidth is the bottleneck.
- **Repeating the same critique session-after-session.** If the same
  recommendation appears in two consecutive reviews, either the user
  needs to act on it or it should be retired.
- **Generating new candidates for the sake of generating them.** A
  review that adds 10 ideation candidates is doing more harm than good.
  The best fresh-eyes reviews surface 1-3 genuinely new ideas (or none,
  if the existing queue is sound).
- **Ignoring the prior review.** Always start by reading the last one
  and noting which recommendations did/didn't happen.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Playbook codified | User explicit ask: "create a short doc that encapsulates the objective of a fresh eyes check-in, so there's playbook to run when I invoke it" |
| 2026-04-25 | Procedural rather than scheduled | User explicitly redirected away from cron-style fresh-eyes; ad-hoc invocation is the discipline |
