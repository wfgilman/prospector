# Axioms

> Beliefs about where edge comes from. The lens through which we evaluate
> ideas. Not theorems — working priors that earn their place by surviving
> contact with empirical evidence.

These axioms aren't proven; they're the operating assumptions that shape
which ideas we pursue and which we don't bother with. New candidates are
scored against them at ideation. Findings that contradict an axiom should
be flagged — repeated contradiction is evidence to revise the axiom.

---

## 1. Novelty comes from new combinations of existing ideas

Brand-new mechanisms are vanishingly rare. The vast majority of edges that
have ever worked are recombinations: an established framework from one
discipline applied to a market where it hasn't been tried, or two known
mechanisms layered into a new structure. Examples:

- Actuarial calibration applied to prediction markets (PM Underwriting)
- ETF-vs-basket convergence applied to Kalshi-vs-perp distributions (vol surface)
- Options dispersion logic applied to Kalshi series-vs-game contracts (T4)
- Foraging theory's MVT applied to scanner admission (T2)
- Pari-mutuel cross-track arb applied to Polymarket-vs-Kalshi (T5)

**How to apply:** When a new candidate is logged, ask: *"What two existing
ideas does this combine, and where has the combination been tried before?"*
If the answer is "nothing — it's totally novel," that's almost always a sign
the candidate is poorly understood, not that it's revolutionary.

---

## 2. There are market advantages to being a small player

Whole categories of arbitrage exist *only* at small scales. They're not
ignored by desks because they're invisible — they're ignored because they're
uneconomic at desk capital, even if they're meaningful at solo-operator
capital.

Examples:
- Persistent multi-hour Kalshi ↔ Polymarket divergences on lower-volume
  events (HFT bots can't size into them; we can)
- Maker-side liquidity premium when flow compresses Kalshi orderbook toward
  position limits (desks blow through limits instantly; we don't)
- 40-event/year strategies with $1K edge per event = $40K/year (uneconomic
  for a desk; meaningful for a family-income operation)

**How to apply:** When evaluating a candidate's competitive posture, ask
*"who is trading the other side, and at what scale?"* If the answer is
"institutional desks," the spread is probably already arbed out. If the
answer is "retail or no one," there's room.

This axiom is the explicit counterweight to the [operational-triage filter](operational-limits.md).
The filter's `≥500 events/year` threshold is desk-style; this axiom says
some strategies in the 40-200 events/year range are real-money meaningful
at our scale. The two views must be reconciled per-candidate, not
algorithmically.

---

## 3. Things that don't work at one scale work at another

A strategy rejected at one scale, cadence, or capital level may be viable
at a different one. The Elder-template parameter search failed when run as
a continuous-optimization problem; the same data substrate supports
calibration-curve work as a categorical problem. PM Underwriting framed as
"insurance" produces lottery-ticket payoffs at the scanner's preferred
bins; the same calibration surface produces insurance-shaped trades when
the bin is constrained (T1).

**How to apply:** When a candidate fails at a stage, the first question is
not "should we kill it?" but *"is there a different scale, cadence, scope,
or formulation where it works?"* The bar for `non-viable` requires
explicitly answering "no" to that question.

This is also why the candidate file structure is append-only with verdicts:
a `needs-iteration` rejection at one scale leaves the candidate alive for a
later reformulation; a `non-viable` rejection requires the explicit case
that no scale change rescues it.

---

## 4. Looking at past work with fresh eyes can reveal possibilities previously unseen

Familiarity is a tax on creativity. The deeper you go on an implementation,
the harder it is to see the alternative framings that were available at the
start. Periodic strategic re-evaluation — the [fresh-eyes playbook](../reference/fresh-eyes-playbook.md) —
is how this project guards against the fog of implementation.

**How to apply:** When the user's spider-sense fires (or when a milestone
suggests it's time), invoke the fresh-eyes playbook. Read the docs cold,
ask what an outsider would notice, look for self-imposed constraints that
have crept in. The 2026-04-24 fresh-eyes review surfaced HIP-4 (which the
project had missed entirely) and the insurance-vs-lottery reframing of PM
Underwriting (which had been hiding inside a sizing-reevaluation document).

---

## 5. The LLM's comparative advantage is categorical reasoning over text

This axiom was learned the hard way — see the
[Elder templates rejection](../rd/candidates/00-elder-templates.md) for the
empirical finding. Random search at N=300 beat the LLM at N=200 on a 6-D
continuous parameter landscape, at ~30× lower wall-clock cost.

**Where the LLM earns its keep:**
- Classifying events into categories (e.g., calibration-bin assignment)
- Assessing pairwise correlation between contracts in natural language
- Reading unstructured text (NWS forecast discussions, SEC filings, FOMC
  minutes) and producing structured features
- Detecting regime-change signals from narrative

**Where the LLM does not earn its keep:**
- Continuous parameter optimization (use Bayesian opt or random search)
- Pricing derivatives (use math)
- Sizing positions (use the σ table)
- Executing orders (use the API)

**How to apply:** A new candidate that asserts "the LLM will optimize X"
where X is continuous gets pushed back to a deep-dive that re-frames the
LLM's role. If no categorical-text role exists, the candidate is fine — it
just shouldn't pretend the LLM is doing something it isn't.

---

## 6. Methodology discipline > discovery enthusiasm

Pre-registration, hard date splits, null-shuffle benchmarks, locked
hyperparameters, pre-committed pass criteria, full-distribution reporting.
These exist because the alternative — running tests until something looks
good and then writing the narrative — produces rejections that should have
been validations, and (worse) validations that should have been rejections.

This axiom is partly the [methodology doc's](../reference/methodology.md)
reason for existing. It's listed here because methodology discipline is a
*belief about what produces real findings*, not just a procedural choice.

**How to apply:** When a strategy is in statistical examination, ask
*"would this conclusion change if we tried 5 different formulations and
picked the best?"* If yes, the test isn't measuring what it claims to. The
discipline of pre-registration is what protects the conclusion.

---

## 7. Structural arb is good; directional with measured edge is also good

The sibling-projects review marked "convergence/delta-neutral" as a
higher-quality strategy class than "directional." That's true at desk
scale where convergence trades crowd out slowly. At solo-operator scale, a
directional bet with a well-measured edge, capped variance, and enough
independent trials is perfectly fine — and the PM Underwriting book has
been such a directional bet from the start.

**How to apply:** Don't penalize a candidate for being directional if its
edge mechanism is sound and its variance is bounded by sizing. Conversely,
don't credit a "structural arb" candidate for the framing alone — the
edge mechanism is what matters, not the framing.

---

## 8. Know what's already been done

Every strategy ideation starts with a literature review. Before logging a
candidate, find how the concept has been applied before — in another
discipline, in TradFi, in academic research, in sibling projects, in
existing open-source implementations. This is the same discipline an
academic paper applies before claiming a contribution: situate the work in
what's known so you can articulate precisely how it's new, incremental,
different, or just borrowed.

The point isn't gatekeeping; it's leverage. People have been thinking
about variants of these problems for decades. Reading their work is the
single highest-ROI use of an hour at the start of a candidate. It:

- Surfaces vocabulary that lets you search more effectively
- Reveals known pitfalls (so we don't rediscover them at 11pm in a paper book)
- Identifies the specific assumption or scale that makes our application different
- Sometimes kills the candidate cheaply when prior art shows it doesn't work
- Sometimes strengthens the candidate by showing the mechanism is well-validated and the only open question is the application

The project's [`literature-survey.md`](../reference/literature-survey.md)
is the running reading list. Every strategy in the active and queued
pipeline should be traceable to one or more entries there (or to a
sibling-project lesson, or to a documented external development).

**How to apply:** When a new candidate is logged, the **Ideation** section
must include a *"Prior art / existing applications"* subsection answering:

1. Where has this concept (or a close analogue) been applied before?
2. What did those applications find — works, doesn't work, conditional?
3. What's specifically different about our application — scale, cadence,
   substrate, combination, formulation?
4. If nothing turns up after a real search, say so explicitly. "I looked
   and found nothing" is a valid answer; "I didn't look" is not.

If the candidate is reformulating or borrowing from a sibling project,
cite [`sibling-projects.md`](../reference/sibling-projects.md). If from
academic literature, add the entry to `literature-survey.md` if it isn't
there, and link the candidate to it.

The bar is not exhaustive — it's *honest engagement with prior work*.
Two hours of focused search beats two days of reinvention.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (pre-project) | Axioms 1-4 in user's mental model | User-stated 20-year investing experience axioms |
| 2026-04-14 | Axiom 5 (LLM categorical-only) added | Falsified by Elder-track parameter search; codified in elder-track-pivot.md |
| 2026-04-22 | Axiom 6 (methodology discipline) explicit | Adopted formally for #10 vol surface pre-registration |
| 2026-04-25 | Axiom 7 (directional is fine at small scale) explicit | Reframed during fresh-eyes review; PM book is directional and that's OK |
| 2026-04-25 | Axioms consolidated into charter | Previously implicit in deep-dives + AGENTS.md; centralized for discoverability |
| 2026-04-25 | Axiom 8 (know what's already been done) added | User-stated after reading the reorganized framework: every ideation should start with literature review against another-discipline / TradFi / sibling-project prior art, the same way an academic paper situates itself in known work. Codifies discipline already in use (the existing `literature-survey.md` exists) but had no ideation-level enforcement. |
