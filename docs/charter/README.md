# Charter

> The brief. Why we're doing this, what we may not do, and what we believe.

The charter is the project's constitution. It sets the boundaries inside
which all R&D operates and the principles that guide what counts as a
strategy worth pursuing. It changes rarely, and every change carries a
decision-log entry stating why.

## Documents

| File | What it covers |
|---|---|
| [`constraints.md`](constraints.md) | Hard external constraints (regulatory, employer, market access) that strategies must respect by construction. |
| [`axioms.md`](axioms.md) | Beliefs about where edge comes from. Used as the lens for evaluating new ideas. |
| [`philosophy.md`](philosophy.md) | How we work: methodology discipline, deploy-then-fix, sequential R&D, the LLM's role. |
| [`operational-limits.md`](operational-limits.md) | What infrastructure can credibly do today: cadence + throughput envelope. |
| [`risk-tolerance.md`](risk-tolerance.md) | NAV, drawdown, scale targets, concentration limits at the book level. |

## Reading order on first contact

1. `constraints.md` — what's allowed
2. `axioms.md` — what we believe pays
3. `philosophy.md` — how we develop
4. `operational-limits.md` — what we can execute
5. `risk-tolerance.md` — what we can absorb

## When this changes

Updates to charter docs require:

1. A pull-up with the user explicitly framing the change as a charter shift.
2. A decision-log entry at the bottom of the affected file.
3. A check across `rd/candidates/` for strategies the change might
   activate, deactivate, or re-frame.

Charter changes are rare by design. If you find yourself editing a charter
file mid-implementation, stop and surface the proposed change first.
