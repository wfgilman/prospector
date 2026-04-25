---
id: 11
name: Event-window-only HFT mini-daemon
status: ideation
verdict: pending
last-update: 2026-04-25
related-components: []
---

# Candidate 11: Event-Window-Only HFT Mini-Daemon

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 3 from fresh-eyes review
- **Next move:** Promote only after a candidate demonstrably needs sub-min execution AND throughput-per-event justifies the build.

## Ideation

**Origin:** [`charter/operational-limits.md`](../../charter/operational-limits.md)
disqualifies always-on sub-15m execution because home-internet HFT can't
compete with desks. **But event-window-only sub-min execution** is a
different beast: ~8 FOMC days × 10 min/window × 1 min/year = 80 min/year
of fast-execution requirement. That's bounded.

Build a mini-daemon that activates only during pre-scheduled event
windows (FOMC release times, CPI prints, NFP releases). Rest of the time
it's dormant. The infrastructure investment is bounded and the strategy
universe expands.

**Axiomatic fit:**
- *Different scale at different time* (axiom 3) — same operator, but
  cadence-mode-switches per event
- *Operational triage exception* — surfaces in [`charter/operational-limits.md`](../../charter/operational-limits.md)
  §cadence as the explicit exception
- *Component infrastructure* — the daemon mode itself is a platform
  piece that any future event-driven candidate could reuse

## Deep dive

(Empty until promoted.)

## Statistical examination

(Empty.)

## Backtest

(Empty.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced as T9 in fresh-eyes review (Tier 3) | Bounded HFT requirement; allows specific high-cadence candidates without authorizing always-on rebuild |
| 2026-04-25 | Tier 3 — not urgent, not first | No specific candidate currently demands this; build only when there's downstream demand |

## Open questions

- Trigger source — economic calendar API? Hand-curated event list?
- Latency budget — what's "fast enough" for, e.g., FOMC reaction?
- Which strategy first? #4 narrative-spread reformulation is the most
  obvious downstream consumer — if it's revisited at finer cadence.
- Cost of the daemon itself — colocation? Or just a tighter local loop?

## Pointers

- Operational limits + event-window exception: [`charter/operational-limits.md`](../../charter/operational-limits.md)
- Most-likely first consumer: [`02-kalshi-crypto-narrative-spread.md`](02-kalshi-crypto-narrative-spread.md)
