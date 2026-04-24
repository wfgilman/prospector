# Operational triage framework for R&D candidates

Established 2026-04-23, after the #4 narrative-spread work made both constraints visible.

Every candidate strategy has to pass two operational filters BEFORE we invest engineering time. They're independent of whether the signal is real or the edge is calibratable — they're about whether the strategy fits what we can operate.

## Filter 1 — Operational cadence

Can we execute at the cadence the thesis requires?

| Cadence | What it takes | Our envelope |
|---|---|---|
| Days to weeks | Polling every few hours, no latency constraints | ✓ |
| Hours | 15-min polling, normal API discipline | ✓ |
| 15 min | Current paper-trade cadence. Two-leg execution fits comfortably | ✓ (outer bound) |
| 5 min | Sub-minute polling, ~1s two-leg execution, daemon-quality uptime, rate-limit headroom | ✗ (~1–2 months of infra to build credibly) |
| 1 min | Low-latency network, sub-100ms order placement | ✗ (not credible from MacBook + home internet) |
| Sub-1 min | Co-lo, kernel-bypass, HFT discipline | ✗ (competing with desks that productize this) |

**Rule:** if a strategy's thesis asserts its edge lives at cadences below 15 min, we can't capture it regardless of whether the signal is real. Deprioritize unless someone funds a low-latency rebuild.

## Filter 2 — Throughput × edge

Can the strategy produce structural-arb-scale P&L, or is it a side bet?

Structural arb works on **law of large numbers**: small edge × many trades → book converges to expected value under bounded variance. If event count is low, even a big per-event edge can't drive the P&L — and variance dominates.

| Events per year | Viability |
|---|---|
| < 50 | Side bet at best. Even 5% edge on $1K position × 40 events = $2K/yr. Not a strategy. |
| 50–500 | Borderline. Needs meaningful edge per event or long-lived positions that accrue time decay. |
| 500–5,000 | Healthy. Enough for per-event Sharpe > 0.05 to aggregate to book Sharpe > 1.5 with N independent trades. |
| > 5,000 | Excellent. PM Underwriting sports parlays sit here. Throughput-bound, not capital-bound. |

**Rule:** a candidate needs ≥ 500 tradeable events/year OR an edge mechanism that persists for weeks (long event-life) to justify build-out as a standalone strategy.

## Applying both filters to the current queue

| Strategy | Cadence fit | Events/year | Decision |
|---|---|---|---|
| **PM Underwriting** (active) | ✓ 15-min | 5,000+ (sports), ~500 (crypto) | **Keep running** |
| **PM Phase 5 hedging** (scoped) | ✓ hourly re-hedge | Inherited from PM crypto slice (~500/yr) | **Build when triggered** (per §Phase 5 criteria) |
| **#10 vol surface** (closed) | Was borderline | — | Closed; finding folded into PM Phase 5 |
| **#4 narrative spread** | Borderline at 15m, ✗ at 5m | ~40 Fed events/yr | **Deprioritize.** Let cron accumulate; revisit only if a 15m-tested version produces signal over 2+ years. Even then, throughput constraint remains. |
| **#2 token unlocks** (queued) | ✓ daily-to-weekly | ~120–360/yr | **Candidate for next active R&D track.** Borderline throughput; edge needs to be meaningful per event. |
| **#12 weather ensemble** (queued) | ✓ daily | Many hundreds/yr | **Strong candidate for next track.** Good cadence fit + good throughput. |
| **#11 cross-exchange funding** (baseline-only) | ✓ hourly | Continuous | Proven mechanic; limited novelty. Hold unless sizing needs a no-correlation complement. |
| **#13 flow classification** | ✓ continuous | Continuous | Novel but infrastructure-heavy. Later. |

## Implications for how we choose next

Two factors make a strategy a good next-track candidate:

1. **Fits our cadence envelope** — 15-min or slower
2. **Has throughput OR long-lived positions** — enough to matter structurally

The two clearest fits from the shortlist are **#12 (weather ensemble)** and **#2 (token unlocks)**. #12 is stronger on cadence + throughput; #2 has more cross-asset flavor and closer mechanical kinship with PM Underwriting (both are event-driven with measurable mispricing).

## Not a static filter

The envelope expands as infrastructure does. If we build:
- A sub-minute execution daemon → cadence filter opens up to 5m strategies
- A real-time orderbook capture → execution-quality strategies become viable
- A co-lo setup → proper HFT strategies become testable

Each of those is its own investment decision. They should be driven by a specific strategy demand, not built speculatively. The current cadence + throughput filter is the right one for our current infra.

## Prior decisions this framework would have made differently

- **#4 narrative spread** — should have been flagged earlier as a cadence-filter candidate failure. The thesis text said "1–60 minute horizon" explicitly. Would have saved ~2 days of Phase 1 + Phase 3 work. Not wasted — the pre-registration discipline and data-pipeline learnings carried forward — but a faster filter-out.
- **#10 vol surface** — cadence fit was fine; the issue was model-family mismatch (lognormal vs. empirical). Wouldn't have been filtered out by this framework.
