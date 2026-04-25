# Fresh-Eyes Review — 2026-04-24

> **Purpose:** axiom-driven re-examination of the project's current track and queue, surfacing self-imposed constraints worth relaxing and novel strategy candidates that supplement (not replace) `strategy-families.md`. Triggered by a user request to look at the work with fresh eyes against four axioms: (1) novelty from new combinations of existing ideas, (2) market advantages at small scale, (3) things that don't work at one scale work at another, (4) fresh eyes reveal what familiarity hides.

> **Companion artifacts:**
> - `strategy-families.md` — the formally-triaged strategy queue. Unchanged.
> - `operational-triage.md` — the cadence/throughput filter. This doc challenges some of its applications.
> - `sizing-reevaluation.md` — sizing decisions that interact with §3.H below.
> - `deep-dive-prediction-market-underwriting.md` — the live track's prospectus.
> - Memory: `reference_hip4.md`, `project_strategy_candidates.md` for cross-session continuity.

---

## 1. Track-so-far evaluation

### 1.1 What's working

- **Methodology discipline.** Pre-registration, hard date splits, null-shuffle benchmarks, pre-committed pass thresholds, full-distribution reporting. This is the project's most defensible asset — it's why #4 and #10 died *cleanly* instead of surviving as partial-success illusions.
- **The Elder-track pivot (2026-04-14)** was correctly executed. LLM-as-bayesian-optimizer was the wrong shape; the falsification was rigorous and didn't leak into adjacent decisions.
- **D1 wedge replication** (vol-surface §15) is real, durable, and now confirmed across two non-overlapping windows at t-stats of ±17 to ±52. The thesis-as-convergence-trade failed but the underlying *phenomenon* is independent.
- **Data infrastructure is now a moat.** 5 years of Kalshi trades (7.2 GB) + Coinbase 1m BTC/ETH/SOL + Hyperliquid funding, incremented daily. Most solo operators do not have this.

### 1.2 What to reconsider

- **The live paper book is effectively single-category.** All 19 open positions on 2026-04-24 are NBA props; crypto produces zero candidates at `min_edge_pp=5`. NAV trajectory $10,000 → $9,883 in 4 days, ~−$117 realized on ~80 trades. Within 9:1-lottery variance, but the *validation signal* is weak: single-category and N=80 vs. N_target=150.
- **Operational triage filter** (`docs/rd/operational-triage.md`: ≥500 events/yr, ≥15-min cadence) imports desk-style "structural-arb-or-skip" thinking. For a small operator a 40-event/yr trade with $1K edge/event is real money. Filter is structurally right but applied too strictly — it currently kills candidates before research, not after.
- **Insurance-vs-lottery framing mismatch.** Phase 3.5 patched the *sizing* layer but the scanner still selects 85-95¢ extreme bins. The project name "underwriting" describes the aspirational portfolio shape, not the realized one. This is fine, but it should be explicit and there should be a *second* book that genuinely is insurance-shaped (see T1 below).
- **LLM-role constraint** ("categorical reasoning only") is over-fit to the Elder-track failure. It correctly excludes continuous optimization but also excludes the LLM's strongest applied use: feature generation from unstructured text. The project has never tried this.
- **Single-active-track cadence.** The R&D queue is serialized. Some candidates are operationally light enough to run as parallel auxiliary tracks without competing for primary attention or capital.

---

## 2. External landscape: HIP-4

The biggest gap between the project docs and current external reality: **HIP-4 — "Event Perpetuals" on Hyperliquid** — is not mentioned anywhere in the docs.

- Co-authored by Kalshi's John Wang. Submitted Sep 2025. Testnet live **2026-02-02**.
- Kalshi "Timeless" product launches **2026-04-27** (~3 days from now).
- Partnership formally announced March 2026.
- Clear Street projects 2026 prediction-market volume: Kalshi $96B, Polymarket $84B.
- Microstructure: 1× isolated margin, price bands 0.001-0.999, oracle resolution with challenge windows, 50-min tick-limited settlement (creates documented arb windows).

**Why this matters for the project:**

1. The two platforms most central to prospector are **converging** their PM capabilities. The #10-as-standalone close decision was based on 2-venue thinking; 3-venue is a different problem.
2. **3-axis audience mismatch** (US retail, global crypto, Hyperliquid-natives) is structurally larger than the current 2-axis story. The arguments in `strategy-families.md` §4 are stronger.
3. Cross-platform Kalshi ↔ Polymarket arb is a known phenomenon (15-20% of events diverge >5pp; $40M+ extracted from Polymarket alone per IMDEA arxiv:2508.03474). Reported implementations are HFT bots on sub-second windows. **The persistent multi-hour divergences on lower-volume events are within our 15-min envelope and inaccessible to scalping HFT** — textbook small-player axiom.

Verify the exact mainnet timeline and current product state via Hyperliquid docs before planning against it. See `~/.claude/projects/.../memory/reference_hip4.md`.

---

## 3. Self-imposed assumptions worth challenging

### A. "Cadence floor is 15 minutes"
True for the always-on paper book. Not true for: (i) weekly/monthly horizon strategies, which don't even touch this floor; (ii) event-window-only modules that activate around scheduled catalysts (≤10 minutes / event × ≤10 events / year — bounded total fast-execution requirement).

### B. "≥500 events/year throughput"
Imported from desk-style LLN-at-strategy-level. At book level, three strategies × 100 events/year each = 300 events with the same statistical footing as one strategy at 300 events. Long-lived positions (months) deploy capital efficiently without competing for scanner time.

### C. "LLM role is categorical-reasoning only"
Correct: continuous optimization is the wrong shape. **Excluded from this constraint that it shouldn't be:**
- Feature generation from unstructured text (NWS Area Forecast Discussions, SEC 8-K filings, FOMC minutes tone)
- Counterfactual simulation ("what if this were a non-catalyst day")
- Synthetic data augmentation for category-classifier robustness testing

These are categorical reasoning tasks — they just produce *inputs* to a quantitative model rather than picking parameters.

### D. "Structural arb > directional"
`sibling-project-insights.md` ranks convergence/delta-neutral as higher quality. That's desk thinking; convergence trades crowd out at scale. At small scale, a directional bet with measured edge, capped variance, and enough independent trials is fine. The PM book is already directional; own it explicitly.

### E. "One active R&D track at a time"
Several candidates in §4 are data-pipeline-free and operationally lightweight. Run them as parallel auxiliary tracks.

### F. "Kalshi is *the* prediction market"
Obsolete in 2026 (HIP-4; Polymarket; Limitless; Manifold). Project has deep Kalshi expertise; extending the data layer is ~2 weeks, not a strategy pivot.

### G. "Securities are off-limits" → maybe broader than necessary
Worth a 30-min conversation with the employer's policy. CME HDD/CDD weather futures and CME ag/energy futures are CFTC-regulated commodity futures, *categorically not securities*. If the prohibition is specifically on SEC-regulated securities, weather/ag/energy/metals/FX open up. If broader, nothing changes.

### H. "Insurance framing — accept the lottery payoff"
Phase 3.5 resolved this at the sizing layer but left the scanner selecting lottery tickets. The actuarial premium (small edge × many favorites) lives in **60-80% implied** bins, not 85-95%. The current ranker `edge/σ` pulls to extremes because σ rises at extremes but so does path risk. A second book with `edge × σ⁻²` or `edge × WR` ranker would select genuine insurance positions: low variance, ~70% WR, small wins, compounding. Same data, same calibration store, same sizing infrastructure.

---

## 4. New strategy candidates

Filtered for: axiom fit (novel combinations, small-player advantage, scale-dependent possibility) × current-infrastructure compatibility (≤2 weeks to MVP) × clean kill criterion. Candidate IDs (T1-T12) are stable and used in memory references.

### Tier 1 — ship-ready, high-conviction

**T1. Insurance-slice second PM book** (~1 week)
The actual insurance-underwriting strategy the prospectus described. New scanner, new ranker (`edge × σ⁻²` or `edge × WR`), targets 55-75¢ implied where σ is low and WR is high. Runs alongside the lottery-ticket book; shares σ-table, calibration store, schema. Payoff profile: high WR, small wins, low variance — the opposite of today's book. Kill criterion: 30-day paper Sharpe < 0.5 after fees. *Addresses axiom 3 directly — same calibration edge, different scale/framing.*

**T2. MVT-style dynamic trade selector** (~50 LOC)
Charnov's Marginal Value Theorem: a forager leaves a patch when marginal capture rate drops to the habitat average. The scanner currently picks highest-edge above a static floor — this is "stay in the patch forever." Instead: dynamic leave-threshold = rolling-window average per-tick edge. Pass on candidates below average even if above the hard floor; take more than usual when the scanner is rich. **Not** the same as raising `min_edge_pp`. Zero prior art in trading literature that I can find.

**T3. CLV (closing-line value) instrumentation** ✅ **SHIPPED 2026-04-24**
Sports sharps' closing-line-value metric ported to Kalshi. Computes signed gap between entry price and last bid/ask before resolution. Gives a faster edge signal than realized P&L (price-based statistic stabilizes at N~hundreds vs. N~thousands for outcome-based at 9:1 payoff). See §6 for first-run results.

**T4. Dispersion trade on Kalshi series-vs-game markets** (~1 week)
TradFi dispersion: buy options on index components, sell options on the index, profit from implied-vs-realized correlation gap. Kalshi analogue: Kalshi lists both "Team X wins championship" *and* "Team X wins each playoff game." Under independence, P(championship) = ∏ P(game_i wins). Crowd overweights championship dreams. **Buy the championship, sell the parlay legs** → delta-neutral on series outcomes. Same edge as parlay overpricing, different expression. No directional exposure, moderate capacity, kill criterion is a 1-day historical backtest of the structure.

### Tier 2 — bigger but tractable

**T5. Three-venue PM divergence** (~2 weeks once HIP-4 mainnet)
Kalshi ↔ Polymarket cross-venue arb is publicly documented; HIP-4 adds a third venue with the smallest initial liquidity. HFT-accessible gaps close in seconds; persistent multi-hour gaps on lower-volume events are *invisible to desks* (too thin to size into) but *perfect at small scale*. Start with Polymarket data layer now; HIP-4 joins automatically when mainnet ships.

**T6. NWS Area Forecast Discussion alt-data via LLM** (~2 weeks, pairs with #12)
NOAA forecasters publish AFDs 2× daily per station — paragraphs of expert narrative explicitly NOT in ensemble model output. Contains hedges like "models are probably underforecasting max temps due to wildfire haze reducing radiational cooling." The queued #12 weather-ensemble track uses only model outputs; layering LLM-extracted AFD modifiers on ensemble probabilities differentiates from anyone else trading Kalshi weather. **LLM as feature generator, not classifier.** Zero prior art in Kalshi weather trading.

**T7. "Slow book" from shadow-ledger 28d+ rejections** (~150 LOC)
Shadow ledger (added 2026-04-23) logs every candidate rejected for `close_time - now > 28 days`. Many are politics / season-long sports / commodity / award markets — long-duration, thinner, more inefficient. The main book skips them (correct for paper validation, wasteful long-term). A second book runs weekly-cadence rebalance on 30d-365d markets with different sizing (higher per-position because rebalance cadence is weekly, not event-driven). Universe is already being recorded; just need a second portfolio + rebalancer.

**T8. Kalshi ↔ CME weather futures convergence** (~2-3 weeks; needs employer-policy verification)
CME HDD/CDD are CFTC-regulated commodity futures. Kalshi has weather contracts on the same NOAA stations. CME = utilities/airlines/energy traders (institutional, sharp). Kalshi weather = retail. Same underlying, totally different audience. Cleanest cross-market convergence setup in the queue, *contingent* on employer policy permitting CFTC commodity futures.

### Tier 3 — interesting / lower priority

- **T9. Event-window-only HFT mini-daemon.** ~8 FOMC × 10 min/yr = 80 min/yr of sub-min execution. Activates only during pre-scheduled windows; rest of the time the paper book runs as today. Bounded infra cost.
- **T10. Kalshi maker-side reflexivity trade.** Maker-side liquidity premium when flow compresses orderbook toward position limits. Desks can't exploit (blow through limits instantly). Small-player-specific.
- **T11. HIP-3 first-day-after-auction spread.** Dutch-auction-launched markets have a narrow first-day spread between auction floor and early market. Pre-competitive, lumpy throughput.
- **T12. LLM-scored attention premium on crypto Twitter ↔ DOGE/WLFI perp.** Sentiment-weighted volume vs. price. Narrower re-expression of #4 with attention as signal, not information.

---

## 5. Cross-discipline imports — fast list

- **Hausch-Ziemba parimutuel cross-track arb (1980s)** — home track (sharp, liquid) infers correct odds; away tracks (illiquid, soft) get systematic mispricings. Direct port: Kalshi = home, Polymarket = away, HIP-4 = newest away.
- **Reinsurance layer cake** — write "normal outcome" layer separately from "extreme tail" layer. Improves portfolio attribution on weather / sports.
- **Charnov MVT** — see T2.
- **Artificial immune system / dendritic-cell anomaly detection** (Aickelin et al.) — 2-signal framework (PAMP=danger, safe). Fits Kalshi: orderbook depth compression (danger) + volume spike (safe) → entry signal. More principled than ad-hoc thresholds.
- **Variance risk premium in weather** (Bae/Jacobs/Jeon AEA 2025) — weather implied variance exceeds realized; systematic sellers earn premium. Strengthens T8.
- **Stoikov market-making** — reference model for Kalshi maker orders; standard in crypto MM, not yet standard in Kalshi.
- **Calendar/circadian effects in retail flow** — Kalshi sports lines drift more after 6 PM ET; one-day exploratory scan on the historical trade tree should reveal whether entry-time-of-day is a sizable axis.
- **Insurance float (Buffett)** — Kalshi positions lock capital from entry to resolution. A slow book (T7) with 90-day resolution × 20 positions has ~$20K float for 90 days. Sizing the slow book is about float-opportunity-cost, not just per-trade variance.

---

## 6. Recommended next moves

Priority by effort × impact × axiom fit. Updated 2026-04-24 (T3 shipped).

| # | Action | Effort | Status |
|---|---|---|---|
| 1 | **T3 — CLV instrumentation** | 1 day | ✅ shipped 2026-04-24 |
| 2 | **T1 — insurance-slice second PM book** | ~1 week | next up |
| 3 | **T4 — dispersion trade backtest** | 1-2 weeks | parallel R&D candidate |
| 4 | Verify HIP-4 mainnet timeline | 30 min | external check |
| 5 | Verify employer-policy scope (securities vs commodities) | 30 min | external check |
| 6 | **#12 weather ensemble** with **T6 (NWS AFD LLM alt-data)** layered in | per existing queue | promote T6 inside #12 |
| 7 | Keep paper book running | n/a | don't change course on 4-day data |

**What NOT to do:** expand the scanner universe right now (already at 20/day cap, monitor churn eats API quota). Rebuild the LLM inner loop. Re-open #4 or #10 as currently formulated. Chase HFT cross-platform arb.

---

## 7. T3 — first-run findings (snapshot of what CLV is already telling us)

Initial run on the 4-day-old paper book (2026-04-24, 100 positions: 19 open + 60 closed + 21 voided/other):

```
Aggregate (n=28 scoreable)   mean=+2.93pp  median=−0.75pp  σ=14.12pp  beat_line=32.1%
Open positions (n=25)        mean=+0.20pp  median=−2.50pp  σ= 7.76pp  beat_line=24.0%
Closed positions (n=3)       mean=+25.67pp median= +7.00pp σ=33.20pp  beat_line=100%
By price bin: 85-90¢         mean=−1.06pp  median=−3.50pp  beat_line=18.8%  (worst)
              95-100¢        mean=+5.93pp  median=+6.00pp  beat_line=57.1%  (best)
corr(edge_pp, clv_pp) = +0.144
```

Read with care: only 28/100 positions had any closing-line reference at first run because the daily Kalshi-tree cron is scoped to KXBTC + FED tickers, not sports. The new `clv_snapshots` table populated via the live monitor will have full coverage on every ticker the paper book holds, growing by ~19/tick from now on. Re-read in 48 hours for a cleaner picture.

What it is *already* hinting at:
- **Open-book CLV is mildly negative** (median −2.5pp). The market is moving against most of our entries within the holding window. Either the entry timing is suboptimal, or the calibration-driven edge is being eroded by post-entry information.
- **edge_pp ↔ CLV correlation is weak** (+0.144). The scanner's `edge_pp` is at best a noisy CLV proxy. Once N grows, this correlation is the right metric to optimize the scanner against.
- **85-90¢ bin is underperforming, 95-100¢ is leading.** Worth re-checking the σ-table assumptions for those bins given Phase-3 live data.

---

## 8. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-24 | Created this doc | User-requested fresh-eyes review against four axioms |
| 2026-04-24 | Shipped T3 (CLV instrumentation) | Lowest-effort, highest-leverage first move; faster signal than realized P&L at 4-day horizon |
| 2026-04-24 | Added `clv_snapshots` table on paper portfolio | Daily Kalshi-tree cron is scoped to KXBTC+FED only; CLV needs broader per-ticker coverage; piggybacks on the existing monitor's per-position market fetch |
| 2026-04-24 | Memorialized HIP-4 to memory + this doc | Not in any project doc; co-authored by Kalshi exec; testnet live Feb 2026 — material to multiple R&D decisions |
| 2026-04-24 | Listed T1, T4 as next priorities | Both ≤2 weeks effort, no infrastructure changes, complement (not replace) PM Phase 3 |
| 2026-04-24 | Did NOT touch the operational-triage doc | Filter is structurally right; only the application strictness is too aggressive — flagged here as a §3.B observation rather than a doc rewrite |
| 2026-04-24 | Did NOT modify `strategy-families.md` | The triaged queue is fine; this doc is a supplement, not a replacement |
