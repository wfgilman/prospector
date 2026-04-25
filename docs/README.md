# Prospector — Documentation

> **Canonical entry point.** Start here.

This documentation is structured to keep the project's collective knowledge
discoverable, atomic, and resistant to sprawl. Each top-level directory has
one responsibility; cross-cutting concepts live in the directory they belong
to, never duplicated across strategies.

## Where things live

| Directory | What lives here | When to update |
|---|---|---|
| **[`charter/`](charter/)** | The brief: constraints, axioms, philosophy, operational limits, risk tolerance. Rarely changes. | When the project's fundamental boundaries shift. Decision-log entry required. |
| **[`platform/`](platform/)** | Infrastructure that enables everything: data pipeline, paper-trade daemon, dashboard, accounting. One file per platform piece. | When the corresponding code changes. |
| **[`components/`](components/)** | Reusable mechanisms that strategies apply as variants or overlays: calibration curves, equal-σ sizing, MVT, CLV, hedging, etc. One file per component. | When a new mechanism is invented or an existing one materially changes. |
| **[`rd/`](rd/)** | Strategy candidates moving through the [stages-and-verdicts pipeline](reference/stages-and-verdicts.md). Append-only — candidates that fail are kept with a verdict, not deleted. | New ideas → new candidate file. Stage transitions → update frontmatter + decision log. |
| **[`reference/`](reference/)** | Methodology, glossary, runbook, fresh-eyes playbook, sibling-projects, external landscape. The "how we work" docs. | When discipline, terminology, or operational state changes. |

## Where to start, by question

| You're asking… | Read… |
|---|---|
| What is this project, and what may it not do? | [`charter/`](charter/) — start with `README`, then constraints + axioms |
| What's running right now, and what's coming next? | [`rd/pipeline.md`](rd/pipeline.md) |
| How does the paper-trade daemon work? | [`platform/paper-trade-daemon.md`](platform/paper-trade-daemon.md) |
| What does "calibration curve" mean? | [`components/calibration-curves.md`](components/calibration-curves.md) |
| What's our testing rigor? | [`reference/methodology.md`](reference/methodology.md) |
| When/how do we do strategic re-evaluation? | [`reference/fresh-eyes-playbook.md`](reference/fresh-eyes-playbook.md) |
| What does "ideation → live" mean precisely? | [`reference/stages-and-verdicts.md`](reference/stages-and-verdicts.md) |
| What's HIP-4, what's Polymarket doing? | [`reference/external-landscape.md`](reference/external-landscape.md) |
| How do I run X? | [`reference/runbook.md`](reference/runbook.md) |

## The pipeline at a glance

Every strategy moves through these stages:

```
ideation → deep-dive → statistical-examination → backtest → paper-portfolio → live-trading
                                                                                ↓
                            absorbed (folded into another strategy) ←────  rejected
```

The bar for **non-viable** is high — explicit reasoning required for "no
variant, overlay, or scale change could rescue this." See
[`reference/stages-and-verdicts.md`](reference/stages-and-verdicts.md) for
the formal stage definitions and verdict criteria.

## Acceptance contract

This documentation system is built to satisfy three rules:

1. **Zero data loss.** Every fact, finding, decision, and rationale from
   prior sprawl-era docs has a home in the new structure. Nothing important
   gets buried in an unrelated file.
2. **Cold-start legibility.** A fresh agent (human or otherwise) reading
   `docs/README.md` and `rd/pipeline.md` knows what we've done, what we're
   doing, and what the next step is — within 15 minutes.
3. **One-source-of-truth per concept.** Each component, mechanism, or
   constraint lives in exactly one canonical doc. Strategies link to it.

If you find duplication or buried lore while working, treat it as a bug.
Either consolidate to the canonical home or open a TODO in a decision log.
