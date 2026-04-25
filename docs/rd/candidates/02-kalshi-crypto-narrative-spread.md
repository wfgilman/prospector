---
id: 02
name: Kalshi × crypto narrative spread
status: rejected
verdict: needs-iteration
last-update: 2026-04-23
related-components: []
---

# Candidate 02: Kalshi × Crypto Narrative Spread

## Status snapshot

- **Stage:** rejected
- **Verdict:** needs-iteration — directional sign correct on 15-min Coinbase data; magnitude near zero. Operational triage flags failure on cadence (sub-15m needed) and throughput (~40 FOMC events/yr). Not pivoted-and-killed; deprioritized.
- **Reason:** Two specific failure modes identified, each with clear rescue criteria. Not non-viable.
- **Next move:** Revisit if (a) infra envelope expands to sub-5m execution, OR (b) 2+ years of additional FOMC cycles accumulate, OR (c) a different macro contract class (CPI, NFP) shows stronger transmission than FOMC at the cadences we can run.

## Ideation

**Origin:** Macro Kalshi contracts (Fed, CPI, NFP, elections, ETF
approvals) have causally-linked downstream effects on crypto. Hypothesis:
the two markets have structurally different participant pools (Kalshi:
macro/political retail; crypto: trading-first, distracted). When Kalshi
moves on news, crypto's response lags by 1-60 minutes. That lag is
exploitable.

**Single-leg trade:** watch Kalshi → infer expected crypto response via
LLM-maintained β map → take a directional position on Hyperliquid perp.
LLM's role: maintain the β map, classify each Kalshi move as news-driven
vs. noise, reject reverse-causation (crypto leads Kalshi).

**Axiomatic fit:**
- *Combinations* — equity-futures-leads-cash arbitrage (40-year-old) +
  prediction markets as the leading indicator + LLM as semantic-content
  extractor
- *Small-player* — modest per-event edge (10-30bp) is too small for
  desks; plenty for one operator
- *LLM categorical role* — every Kalshi contract is literally a question;
  the β map is reasoning over text

## Deep dive

### Event taxonomy

Useful Kalshi contract classes:

| Class | Density | Crypto coupling |
|---|---|---|
| Fed rate decisions | 8/yr + intraday | Strong on BTC/ETH |
| Inflation prints | 12/yr + intraday | Strong on BTC/ETH |
| Employment reports | 12/yr | Moderate on BTC |
| Election outcomes | Continuous in cycle | Token-specific (DOGE, WLFI, $TRUMP) |
| SEC/regulatory | Sporadic but high-impact | Asset-specific |
| Crypto price contracts | Continuous | Direct (synthetic options) |

### β map artifact

YAML/SQLite store mapping each contract class to expected crypto exposures.
Maintained by the LLM (proposing additions backed by historical event
studies); reviewed by Claude monthly.

### Signal pipeline

1. Kalshi price update for a mapped contract
2. Compute ΔP since last evaluation (1/5/15 min windows)
3. LLM classifies: news-driven vs. noise vs. reverse-caused
4. If news-driven, compute expected crypto response via β map
5. Check actual crypto move; if lagged, enter position
6. Exit on catch-up, time decay, reverse signal, or stop-loss

## Statistical examination

### Phase 1 (2026-04-22) — Hourly granularity

Pre-registered hyperparameters locked in `scripts/fomc_event_study.py`
before any results inspection. Train/test split: 3 train events
(FED-25SEP/OCT/DEC) / 1 test event (KXFED-26JAN).

**Pre-committed pass criteria (test fold):**
- |t-stat β| > 3.0
- R² > 0.002
- sign(β) = negative (dovish ΔP → BTC up)
- Null-shuffle |t-stat| < ⅓ real |t-stat|

**Result:** All four FAIL. β positive in both train and test (wrong sign);
t-stats 0.18-1.05; null t-stats comparable to real.

**Interpretation:** Hourly granularity averages over both the lag and the
reversion within one return window — the sign is determined by whichever
moves more, not by the underlying transmission. Couldn't distinguish "no
signal" from "wrong measurement."

### Phase 3 (2026-04-23) — 15-min Coinbase data

Same pre-reg carried forward; only granularity change pre-locked.

**Result:**

| Criterion | BTC | ETH |
|---|---|---|
| (a) \|t-stat β\| > 3.0 | FAIL (1.06) | FAIL (0.28) |
| (b) R² > 0.002 | FAIL (0.00039) | FAIL (0.00003) |
| (c) sign(β) = negative | **PASS** (was FAIL in Phase 1) | **PASS** (was FAIL) |
| (d) null t-stat ratio | FAIL | FAIL |

**Interpretation:**

1. Granularity alone fixed the sign prior. Phase 1's positive β was a
   measurement artifact of hourly pooling. Sign is correctly negative in
   both coins on test fold and 2 of 3 train events.
2. **5× the sample size did not rescue significance.** Train n went from
   1,442 → 7,806; test from 720 → 2,880. T-stats stayed 0.3-1.1. The
   effect is genuinely close to zero at the 15-min horizon.

The most interesting train per-event:
- **FED-25OCT:** BTC β=−0.016, ETH β=−0.059 (|t|=1.49). Sign correct,
  largest magnitude.
- FED-25SEP / FED-25DEC: noise.

Oct 2025 was a FOMC with active rate-cut repricing; Sep and Dec settled.
Suggests **regime-dependent transmission** — macro news drives BTC only
when the Fed is actively surprising. Can't pre-register cleanly with 4 events.

## Backtest

Not reached as a portfolio sim; the statistical examination already
falsified the simplest formulation.

## Paper portfolio

Not reached.

## Live trading

Not reached.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-15 | Logged in [strategy-families.md](../../../docs/rd/strategy-families.md) (now archived) as #4 | Cross-domain fit; LLM categorical natural |
| 2026-04-22 | Phase 1 fail (wrong sign at hourly) | Granularity / measurement issue suspected |
| 2026-04-22 | Defer pending data-pipeline M2 (1m candles) | Can't measure the phenomenon at the cadence the thesis requires |
| 2026-04-23 | Phase 3 re-run on 15-min Coinbase data | Sign correct, but 5× more data didn't rescue significance |
| 2026-04-23 | Operational triage applied; cadence + throughput fail | At 5m, infra not credible; at 40 events/yr, throughput insufficient for structural arb. See [`charter/operational-limits.md`](../../charter/operational-limits.md). |
| 2026-04-23 | Verdict: needs-iteration (deprioritize, don't kill) | Two specific rescue paths: more events accumulating naturally, OR finer cadence via infra investment. |
| 2026-04-25 | Doc consolidated into rd/candidates/; the open `needs-iteration` status preserved | Reorg; verdict unchanged |

## What survives

- **Pre-registration discipline.** The Phase 1 → Phase 3 sequence is a
  textbook example: pre-locked criteria caught the granularity artifact
  cleanly without retro-fit.
- **Infrastructure.** Coinbase 1m backfill ([component](../../platform/coinbase-client.md))
  was built for this candidate; serves any future cross-asset work.
- **The thesis is alive but underpowered.** Sign is correct; the
  formulation fails operational triage, not measurement.

## Rescue paths (specific, falsifiable)

For this candidate to revisit:

1. **More FOMC cycles accumulate.** Each cycle adds ~3K observations to
   the FOMC windows. Revisit after 2-3 more Fed meetings (~4-6 months).
2. **A different macro contract class shows stronger transmission.** CPI,
   NFP have higher density (12/yr each). If one of those shows |t-stat|
   > 2 on the existing data, the thesis is alive in that channel.
3. **Sub-5m execution infra is built.** Allows pre-registering at 5-min
   or 1-min granularity where the audience-mismatch lag should be largest.

Without one of these, the candidate stays in `rejected / needs-iteration`.

## Pointers

- Coinbase data source: [`platform/coinbase-client.md`](../../platform/coinbase-client.md)
- Operational triage: [`charter/operational-limits.md`](../../charter/operational-limits.md)
- Methodology pre-registration discipline: [`reference/methodology.md`](../../reference/methodology.md)
