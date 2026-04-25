# Philosophy

> How we work. Not what we do (that's [`axioms.md`](axioms.md) and
> [`constraints.md`](constraints.md)) — how the work itself is organized.

These principles change less often than tactics but more often than
constraints. They're stable enough to plan against and explicit enough that
deviations require justification.

---

## 1. R&D mode: deploy then fix

While the project is in R&D — paper-trading, no live capital, solo
operator — work goes **directly to `main`**. No feature branches, no PRs.
Tests + ruff + methodology discipline catch correctness; deploy-then-fix is
acceptable for paper.

**Why:** PR review process is overhead that doesn't earn its weight when
the only reviewer is the person who already reviewed the design. The
methodology discipline (pre-reg, walk-forward, kill criteria) is the real
quality gate; PR ceremony is not.

**Reverts to feature-branch + PR workflow when:** Phase 4 (live capital)
begins, OR the user explicitly asks. At that point the bar shifts because
mistakes cost money, not just engineering minutes.

**Stays the same regardless:**
- Run ruff + the full test suite before pushing
- Conventional-commit subject lines (`feat:`, `fix:`, `chore:`, etc.)
- Never skip hooks, never force-push to `main`, never amend published commits
- Stage files explicitly (no `git add -A`)
- All other Git Safety Rules in `~/AGENTS.md` still apply

This policy is also memorialized in the project root [`AGENTS.md`](../../AGENTS.md)
and as a feedback memory.

---

## 2. Sequential R&D, not parallel

The user is the bottleneck on direction-setting (small kids, sparse
engagement). Adding parallel R&D tracks doesn't help because each track
needs strategic attention to evaluate.

**Default:** one active R&D track at a time. Other candidates queue in
ideation; existing paper books run on autopilot without competing for
strategic attention.

**Exceptions:**
- Components (atomic mechanisms applicable across strategies) can be
  built without consuming R&D-track capacity — they're infrastructure.
- A second paper book that shares calibration + sizing infrastructure with
  an existing book is a low-attention extension (e.g., the insurance
  variant of PM Underwriting).
- 30-minute external checks (HIP-4 status, employer policy verification)
  are coffee-break work, not R&D tracks.

This is the explicit counter-pressure to the natural agent tendency to
"open more tracks because we can." We can; we shouldn't.

---

## 3. Methodology discipline is sacred

Every statistical test pre-registers:

- Hyperparameters (locked in code as module constants before the test runs)
- Date split (hard temporal split; test fold seen exactly once)
- Pass criteria (specific thresholds before any results inspected)
- Null benchmark (typically permutation shuffle)
- Full-distribution reporting (no "best of N" summaries without N)

If a hyperparameter is changed mid-experiment, the change is committed
with a rationale; the prior result is not retroactively rewritten.

The reason: the alternative — running tests until something looks good and
writing the narrative around it — produces persistent type-I errors that
look like real findings. We've seen this in the literature; we won't
reproduce it here.

**Applies to:**
- Statistical-examination stage of every candidate
- Walk-forward backtests
- Live paper-book evaluations (e.g., the kill criterion is pre-committed)

**Does not apply to:**
- Train-fold exploration (researcher intuition is welcome on the train
  fold; the discipline is at the train/test boundary)
- Charter / philosophy decisions (these are judgment calls, not statistics)
- Operational decisions (load this plist now, ship this CLV improvement)

---

## 4. The fresh-eyes harness

The project explicitly schedules strategic re-evaluation as a discipline,
not as a reaction to crisis. The [fresh-eyes playbook](../reference/fresh-eyes-playbook.md)
defines when and how. Triggers include:

- The user's spider-sense
- Major external shifts (e.g., HIP-4 mainnet)
- Quarterly cadence as a default backstop
- After a candidate transitions stage (especially after rejection)

The harness exists because deep implementation work has a fog of war:
the longer you're heads-down on one piece, the harder it is to see the
alternative framings, the underexploited cross-discipline imports, the
self-imposed constraints that have crept in.

The 2026-04-24 fresh-eyes review surfaced HIP-4 (entirely missed by the
project until then), the insurance-vs-lottery reframing of PM Underwriting
(buried inside the sizing-reevaluation doc), and the operational-triage
filter's tendency to be applied too strictly. Each of those would have
remained invisible without an explicit "look up out of the fog" pass.

---

## 5. Append-only history, atomic concepts

The project's collective knowledge — what we've tried, what worked, what
didn't, what we believed at the time — is itself an asset. We don't
overwrite history; we add to it.

Practically:
- **Decision logs** at the bottom of every candidate, component, and
  charter file. Append-only.
- **Stage transitions** preserve the candidate file with the prior stage's
  artifact intact; new stages add new sections rather than replacing old
  ones.
- **Concepts live in one canonical home.** Calibration-curve methodology is
  in [`components/calibration-curves.md`](../components/calibration-curves.md),
  not duplicated across strategy files. Strategies link to it.
- **Archived strategies stay visible** in `rd/candidates/` with verdict
  set to `rejected` or `absorbed`. They're not deleted; they're labeled.

This is what lets a fresh agent (or a returning user) know "what we've done,
what we're doing, and what the next step is" without reading a sprawl of
half-related deep-dives.

---

## 6. Candor over comfort

When a finding is ambiguous, say so. When a result fails its pre-registered
criterion, say so. When you're in agreement with the user, say so concisely;
when you're not, say so explicitly with the specific reason.

The user has 20 years of investing experience. Padding analysis with
hedges to avoid sounding wrong is worse than being wrong cleanly.

---

## 7. The user is the strategist

The agent's role is to:
- Surface what's true (data, findings, external developments)
- Propose options with explicit tradeoffs
- Execute the chosen option rigorously
- Memorialize what was learned

The user's role is to:
- Decide what to pursue
- Decide when to step away
- Apply the spider-sense
- Set the bar for "non-viable"

The agent does not unilaterally pivot strategy direction, override charter
constraints, or open new R&D tracks without explicit approval. When in
doubt, surface the question rather than guess.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-14 | LLM continuous-optimization role abandoned | Elder track empirically falsified |
| 2026-04-22 | Methodology discipline formalized for #10 pre-registration | Prevents retro-fitting narratives |
| 2026-04-23 | Operational-triage framework adopted | Filter candidates by infrastructure feasibility before deep dive |
| 2026-04-25 | Direct-to-main during R&D | Solo-operator paper-trading; PR ceremony doesn't earn its weight |
| 2026-04-25 | Sequential R&D, not parallel | User is the bottleneck on direction; parallel tracks don't help |
| 2026-04-25 | Fresh-eyes harness as recurring discipline | Counters the fog of implementation |
| 2026-04-25 | Documentation reorg into atomic categories | Anti-sprawl; one canonical home per concept |
