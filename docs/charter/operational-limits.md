# Operational Limits

> What infrastructure can credibly do today. The cadence + throughput
> envelope inside which strategies must fit.

These limits are real, observable boundaries — not preferences. A strategy
that requires execution faster than the cadence floor or more events than
the throughput floor is operationally disqualified at ideation, regardless
of how attractive its edge mechanism looks on paper.

This doc is the formal version of what was originally in the
operational-triage R&D doc; it now lives here in the charter because it's
a project-level boundary, not a strategy-specific finding.

---

## Filter 1 — Operational cadence

Can we execute at the cadence the strategy's thesis requires?

| Cadence | What it takes | Our envelope |
|---|---|---|
| Days to weeks | Polling every few hours, no latency constraints | ✓ |
| Hours | 15-min polling, normal API discipline | ✓ |
| 15 min | Current paper-trade cadence; two-leg execution fits comfortably | ✓ (outer bound) |
| 5 min | Sub-minute polling, ~1s two-leg execution, daemon-quality uptime, rate-limit headroom | ✗ (~1-2 months of infra to build credibly) |
| 1 min | Low-latency network, sub-100ms order placement | ✗ (not credible from MacBook + home internet) |
| Sub-1 min | Co-lo, kernel-bypass, HFT discipline | ✗ (competing with desks that productize this) |

**Rule:** if a strategy's thesis asserts its edge lives at cadences below
15 min, we can't capture it regardless of whether the signal is real.
Deprioritize unless someone funds a low-latency rebuild.

**Exception worth noting:** event-window-only cadence is different from
continuous cadence. ~10 minutes of fast execution × ~10 events/year is
~100 minutes/year of HFT-quality work. That's bounded enough to consider
building (see candidate 11 — event-window-only HFT mini-daemon) without
authorizing a continuous low-latency rebuild.

---

## Filter 2 — Throughput × edge

Can the strategy produce structural-arb-scale P&L, or is it a side bet?

Structural arb works on the **law of large numbers**: small edge × many
trades → book converges to expected value under bounded variance. If
event count is low, even a big per-event edge can't drive the P&L —
variance dominates.

| Events per year | Viability for a structural-arb book |
|---|---|
| < 50 | Side bet at best. 5% edge × $1K position × 40 events = $2K/yr. Not a strategy by itself. |
| 50-500 | Borderline. Needs meaningful edge per event or long-lived positions that accrue time decay. |
| 500-5,000 | Healthy. Enough for per-event Sharpe > 0.05 to aggregate to book Sharpe > 1.5 with N independent trades. |
| > 5,000 | Excellent. PM Underwriting sports parlays sit here. Throughput-bound, not capital-bound. |

**Rule:** a candidate needs ≥ 500 tradeable events/year OR an edge
mechanism that persists for weeks (long event-life) to justify build-out
as a standalone strategy.

**Important counterweight from the axioms:** [`axioms.md`](axioms.md) §2
states that small-player advantages exist at scales that fail desk-style
filters. A 40-event/year × $1K-edge/event = $40K/year strategy is real money
for a family-income operation but fails this filter. The filter is *useful*
as a default but should not be applied without considering the
small-player counterweight on a per-candidate basis.

In practice: throughput failure is a **prompt to think harder**, not an
automatic disqualifier. Disqualify only after considering whether
long-lived positions, capital efficiency, or asymmetric payoff change the
arithmetic.

---

## Hardware footprint

| Resource | Available |
|---|---|
| CPU | MacBook Pro M3, 8-core |
| RAM | 16 GB unified |
| Disk | Several hundred GB free; current data tree ~10 GB |
| Network | Home internet (residential ISP) |
| Always-on | Yes — machine runs continuously through this project's R&D phase |
| Cloud / co-lo | None authorized |

The machine being always-on is what makes local launchd-driven daemons
viable. If the machine gets retired or moves to a part-time-on schedule,
the always-on assumption breaks and we'd need to migrate to cloud (which
is a deliberate Phase 4-or-later investment).

---

## API quotas (rough)

| Source | Limit | Headroom |
|---|---|---|
| Kalshi REST | Self-imposed 0.3-0.5s sleep per call (~120-200/min) | Comfortable for ~100 concurrent open positions × 15-min monitor cycle |
| Hyperliquid info | Generous public limits | Not currently a binding constraint |
| Coinbase public | Generous; we use it for backfill only | Not binding |
| Local LLM (Ollama qwen2.5-coder:7b) | M3 16GB hosts the 7B comfortably | Not currently a binding constraint |

If a strategy proposes a 1-minute monitor cadence on hundreds of open
positions, we'll hit Kalshi rate limits. The 15-min cadence at ~20 open
positions per book is well within headroom.

---

## What expanding the envelope would take

The envelope is not fixed. Each of these is a deliberate investment:

| Capability | Investment | Triggers |
|---|---|---|
| Sub-minute execution daemon | 1-2 months | A specific strategy demand whose edge is unambiguously sub-minute and whose throughput justifies the build |
| Real-time L2 orderbook capture | 2-4 weeks | Execution-quality strategy where slippage is the binding edge constraint |
| Co-located server | 4-6 weeks + ongoing cost | Genuine HFT strategy with measured profit > infrastructure cost |
| Cloud migration of paper books | 1-2 weeks | Local machine retirement or part-time-on schedule |

Each of these is its own decision. They should be driven by a specific
strategy demand, not built speculatively.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-23 | Operational-triage framework formalized | After #4 narrative-spread work made both filters' costs visible. Would have saved ~2 days of Phase 1 + Phase 3 work if applied earlier. |
| 2026-04-25 | Moved from `rd/operational-triage.md` to `charter/operational-limits.md` | These are project-level boundaries, not a strategy-specific finding. |
| 2026-04-25 | Counterweight from axioms §2 explicitly noted | Avoid mechanical application of the throughput filter; small-scale arb is a real category. |
