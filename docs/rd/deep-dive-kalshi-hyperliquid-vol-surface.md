# Deep Dive — Kalshi × Hyperliquid Implied-Distribution Arbitrage

> **Status (2026-04-22):** Prospectus. Selected as the second R&D track to run in parallel with the PM-Underwriting paper book. See [`strategy-families.md`](strategy-families.md) §10 for the original one-paragraph summary, and [`deep-dive-prediction-market-underwriting.md`](deep-dive-prediction-market-underwriting.md) for the contrast: PM Underwriting is a directional Kalshi-only calibration book; this is a structural cross-market convergence trade.

## 0. TL;DR

Kalshi's `KXBTC-*` and `KXETH-*` intraday range-contract ladders are a literal discrete implied probability distribution for the terminal price of BTC or ETH at expiry — sampled at ~40 strikes per event, updated continuously, with ~25-hour event lifespans. Hyperliquid's perpetual futures encode a different implied distribution via funding rate, basis-to-spot, and realized-vol trajectory. When the two distributions disagree, someone is wrong. The trade is: buy the underpriced tail of the Kalshi ladder, sell the overpriced tail, and delta-hedge with a BTC_PERP (or ETH_PERP) position on Hyperliquid. The hedge keeps the book market-neutral; the convergence of the two distributions at expiry is the payoff.

The LLM's role is narrow: (a) classify events as "normal" vs. "catalyst-driven" (FOMC day, CPI print, macro headline) so we know whether to trust static-regime priors or pause, (b) monitor for structural shifts in the Kalshi audience that would widen or narrow the gap, and (c) flag individual strikes where its prior disagrees most from the market — the fattest part of the edge.

This is the canonical cross-market strategy: *everything* in the sibling-project portfolio and the current paper book trades within a single venue. Filling the cross-market gap is the single biggest portfolio-level improvement available.

---

## 1. The core bet

**Claim:** The Kalshi crypto-range-contract strike ladder and the Hyperliquid perp-implied distribution for the same underlying, at the same horizon, disagree in a way that (a) is persistent, (b) converges at expiry, and (c) is tradeable after fees and slippage.

**Why it exists:**

- **Audience mismatch.** Kalshi crypto-range contracts are traded by retail-macro participants who are thinking in dollars (*"will BTC be above $90k tomorrow?"*). Hyperliquid BTC_PERP is traded by crypto-native participants thinking in bps and funding (*"what's my liq price and carry?"*). The two populations don't share order books, feeds, or analytical frames.
- **No direct hedging path.** A Kalshi trader who sees BTC tail risk mispriced can only express it with more Kalshi contracts. A perp trader who sees the same thing can only express it with perps or options (and most don't trade options). Neither population arbitrages the other because neither has execution infrastructure on the other venue.
- **Retail tail-bias inherited from longshot studies.** Phase 1 of PM Underwriting found persistent overpricing of crypto longshots (5/20 bins with statistically significant signal). The Kalshi range contracts are a strike-by-strike version of exactly that bias: the extreme buckets (far OTM ranges) get overpriced relative to the sensible distribution. That's the structural feature the vol-surface trade monetizes, but in a delta-neutral way rather than by collecting premium on directional long-shot sells.

**Why now:**

- Kalshi's crypto-range product matured in late 2024; the HF dataset has ~4,781 unique intraday BTC range events × ~40 strikes per event × 25h lifespan in just the *first* of four parquet shards. Total addressable event count is ~20K BTC + ~20K ETH over 2024–2026.
- Hyperliquid funding data is hourly and clean; OHLCV is already local at 1h/4h/1d granularity (`data/ohlcv/BTC_PERP/`, `data/ohlcv/ETH_PERP/`).
- The implied-distribution reconstruction is no longer approximate: the 40-strike ladder *is* the CDF, sampled densely enough that fitting a smooth density is a straightforward numerical exercise.

**Why it doesn't go away immediately:**

- The trade requires simultaneously running code against two venues with fundamentally different execution models (limit-order binary contracts vs. perp taker/maker). The Venn-diagram intersection of traders with infrastructure on both is tiny.
- The edge is per-event modest (we are targeting 20–60bp per event after hedging costs, not single-event alpha). That is plenty for a one-person operation and too small to draw a desk.
- The LLM classifier is only load-bearing at regime boundaries (catalyst days). The rest of the time the strategy is quantitative; there is no narrative-interpretation step to commoditize.

---

## 2. What is genuinely original here

Vol arbitrage between options and spot is a forty-year-old idea (Black-Scholes against realized vol, Merton 1973 forward, entire derivatives-desk PnLs built on it). Cross-venue vol arb in crypto exists on Deribit. Prediction-market-vs-options replication exists on paper (Moontower Meta).

**What's original about this version:**

1. **The "options chain" is a prediction market.** Kalshi range contracts are *already* a binary strike ladder. We don't need to fit a volatility surface from noisy implied vols — we read the prices directly, and they sum to a proper probability measure. That's a cleaner signal than any options-market implied surface because there is no bid-ask-to-mid smoothing, no IV-from-price inversion, no American-vs-European adjustments, no dividend/carry correction. A 40-point sampled CDF with known midpoints and known expiry. That is a research-grade artifact in itself.

2. **The reference distribution is a perp, not an options chain.** In traditional vol arb you compare implied vol to realized vol. Here we compare implied distribution (from Kalshi) to the distribution *implied by the perp's own pricing and funding*. The perp-implied distribution is derivable from funding-rate term structure + recent realized-vol trajectory + basis-to-spot — all public, all already local. No options market required, which is decisive since Deribit has US-person access constraints.

3. **No US-securities constraint hit.** Kalshi is a CFTC-designated contract market, Hyperliquid is a crypto perp DEX. Neither is a security. The entire strategy stays inside the constraint envelope this project was explicitly designed around.

4. **The cross-venue population gap is durable.** S&P-futures-to-cash lead-lag compressed to milliseconds over 40 years because both sides are institutional. Kalshi-crypto audience mismatch has no compression force: the marginal Kalshi trader will not set up a Hyperliquid account, and vice versa. The gap is structural.

**Most useful cross-domain lesson:** the ETF-to-underlying basket arb (circa 2000s) is the tightest analogue. An ETF's NAV was theoretically the basket's NAV; divergences were tradeable. What made it work was a legal redemption mechanism that forced convergence at a known moment. Here the "redemption" is Kalshi expiry — at a known timestamp, the Kalshi ladder prices collapse to 0/100 based on the actual BTC close, and the perp trades at that close. Convergence is mechanical.

---

## 3. How the trade is structured

### 3.1 The two distributions

**Kalshi-implied terminal distribution `F_K(x; t, T)`.** At time `t`, event expiring at `T`, for each strike bucket `[x_i, x_{i+1})`:

```
p_i = yes_mid(ticker_i) / 100
```

Prices must sum to 1.0 (up to the fee-induced wedge that `kalshi-autoagent` already exploits — which we treat as a residual to *avoid* rather than chase). The resulting `p_i` array is a piecewise-constant density; integrate to get the CDF; the midpoint of the density or any pointwise fit (e.g., kernel smoothing) is a full characterization of the Kalshi-implied distribution for BTC at `T`.

**Perp-implied terminal distribution `F_P(x; t, T)`.** Construct from:
- Current spot (taken as the mid of BTC_PERP on Hyperliquid).
- Drift = annualized funding rate over (T - t), summed hour-by-hour from the current funding forward curve. Hyperliquid publishes hourly funding; the forward curve out to 24h is observable as the current premium index trajectory.
- Diffusion = GARCH or EWMA-fit σ from the preceding 24–72h of 1m returns. (Start simple: EWMA with λ=0.94.)
- Assume log-normal terminal distribution at `T`.

The result is a smooth lognormal CDF. Discretize at the same strike midpoints as Kalshi to get `q_i`.

### 3.2 The signal

Per event, per timestamp:

1. Compute `p_i` from Kalshi quotes (mid prices), normalize to sum to 1.0.
2. Compute `q_i` from Hyperliquid spot + funding + realized vol.
3. Compute divergence metric — Kullback-Leibler, Wasserstein, or a simpler "max absolute gap across buckets." Start with max gap for interpretability.
4. If max gap > threshold `τ` (e.g., 300bp at a single bucket, or >50% of the bucket's implied probability, whichever is larger):
   - **Enter position:** buy the buckets where `p_i < q_i` by ≥ threshold; sell the buckets where `p_i > q_i` by ≥ threshold.
   - **Compute hedge delta:** for the resulting Kalshi portfolio, finite-difference the payoff against shifts in the underlying — `Δ = Σ (n_i × ∂payoff_i/∂S)`. Enter an offsetting BTC_PERP position.
5. **Re-hedge cadence:** hourly (aligned with Hyperliquid funding ticks). Re-read Kalshi quotes, re-fit the perp-implied distribution, adjust the perp leg.
6. **Exit on:** (a) event expiry (mechanical convergence), (b) divergence closes (max gap falls below `τ/2`), (c) stop-loss (mark-to-market drawdown exceeds 2× expected event EV), (d) data-quality fail (Kalshi orderbook too thin, perp spread too wide, etc.).

### 3.3 What the LLM does, specifically

Three things, each scoped narrowly:

1. **Regime classifier (real-time, per event).** Three-way decision: *normal* / *macro-catalyst-driven* / *crypto-specific-catalyst*. Inputs: event title, current timestamp, recent headlines (X list or GDELT, last 60 min), Kalshi ΔP over the last hour, BTC return over the last hour. On *macro-catalyst* days, widen `τ`, reduce sizing, or pause — the lognormal model breaks around CPI/FOMC. On *crypto-catalyst* days (exchange hack, regulatory news), both legs move in a coordinated way that the distribution-comparison logic does not capture.

2. **Kalshi-ladder sanity check (offline, weekly).** Read a week of Kalshi ladder snapshots, flag events where the ladder shape is pathological (non-monotonic `p_i`, huge single-bucket spikes, liquidity concentrated in one strike). These are the events where the Kalshi side is noise, not signal.

3. **Priors flagging (offline, monthly).** Given the LLM's own read of the recent macro narrative, which buckets *should* be underpriced vs. overpriced? Compare to the empirical divergence distribution. The events where the LLM's prior agrees most strongly with the statistical signal are the highest-confidence trades; mark them for upsized allocation.

None of these is a continuous optimization task. All are categorical reasoning over structured text. Same shape as PM Underwriting's LLM role.

### 3.4 Sizing and risk

- **Target per-event return:** 20–60bp after fees, hedging cost, and re-hedge slippage.
- **Per-event capital:** size from σ-table analogue (to be built — see §5). Equal-σ as in the PM book.
- **Concurrent events:** start with one active event (one BTC intraday), scale to multi-event once the hedging loop is validated. Correlation across same-underlying same-day events is high; treat as one effective bet.
- **Catastrophic failure mode:** the lognormal perp-implied distribution is the wrong reference during a regime shift (e.g., BTC crashes 10% in an hour because of an exploit). Both distributions become wrong simultaneously, divergence metric does not converge, delta-hedge lags. Mitigated by (a) hard time-stop before event expiry, (b) LLM catalyst classifier pausing entries, (c) stop-loss on mark-to-market.

### 3.5 Transaction cost and feasibility

- **Kalshi:** zero maker fees, 1–3¢ taker fee per contract (worst case ~3% on a $1 contract). The trade is maker-dominant for the Kalshi leg — rest quotes inside the bid-ask on the underpriced buckets.
- **Hyperliquid perp:** 0.035% taker, 0.015% maker. Round-trip ~0.07% taker. Hedge-leg is maker-preferred when the market isn't moving fast.
- **Break-even:** a single round-trip on a $1 Kalshi bucket + a proportional perp hedge needs the gap to close by ~3–5¢ on the Kalshi leg to clear fees + realistic slippage. That is a modest fraction of the gaps we expect at the tails (based on longshot-bias priors — extreme strikes are typically mispriced by 5–15¢).

---

## 4. Data, infrastructure, and the LLM's role

### 4.1 Data we already have

- **Kalshi HF dataset:** `data/kalshi_hf/markets-*.parquet` (markets metadata, 20M rows across 4 shards) and `trades-*.parquet` (154M trades). Event filter `event_ticker LIKE 'KXBTC-%'` or `'KXBTCD-%'` or `'KXETH-%'` isolates the relevant universe.
- **Hyperliquid OHLCV:** `data/ohlcv/{BTC_PERP,ETH_PERP}/{1h,4h,1d}.parquet` — enough for hourly-cadence backtesting.
- **PIT methodology:** `src/prospector/strategies/pm_underwriting/` includes categorize.py (which already has `KXBTC` and `KXETH` under `crypto`), the DuckDB-backed calibration builder, and the σ-table loader. The same PIT-pricing discipline applies — we need the Kalshi bucket prices at known timestamps, not the terminal prices.
- **Categorization:** `KXBTC-*` and `KXETH-*` are already tagged as `crypto` in `categorize.py::CATEGORY_PREFIXES`.

### 4.2 Net-new infrastructure

Small, bounded list:

- **Kalshi ladder reconstructor** — from `trades-*.parquet`, rebuild the `p_i` vector for every (event, timestamp) tuple at a chosen cadence (e.g., every 5 minutes during event life). Output: parquet table keyed by `(event_ticker, ts, strike_midpoint) → mid_price`.
- **Perp-implied distribution fitter** — given spot, funding, EWMA σ, and a strike grid, output the lognormal CDF at each strike. ~50 lines.
- **Divergence computer + signal emitter** — read both, emit trade candidates at each timestamp. ~100 lines.
- **Hedging-cost simulator** — given a Kalshi position and a perp hedge, simulate hourly re-hedging against BTC_PERP 1h OHLCV, apply realistic taker/maker fees and spread. ~150 lines.

Total: 1–2 weeks of coding once the Week-1 data spike validates the thesis.

### 4.3 LLM's role, specifically (repeat of §3.3 for separation of concerns)

Regime classifier + ladder sanity + priors. Nothing else.

### 4.4 What we explicitly do *not* use the LLM for

- Fitting the lognormal — statistical.
- Computing divergences — numerical.
- Sizing — σ-table (equal-σ).
- Execution — deterministic.

This is the same LLM-role discipline that PM Underwriting enforces. The Elder-track pivot's core lesson: don't use the LLM for continuous optimization.

### 4.5 Hardware check

13B Q4 Ollama classifier runs at ~7GB. Per-event inference budget is one 200-token reasoning pass per hour per active event — trivial. M3 16GB is fine.

---

## 5. Validation plan

### 5.0 Methodology discipline (pre-registration)

The Week-1 spike has ~12 continuous or discretionary knobs (σ model, lookback, τ, selection filter, regression horizon, stop-loss multiple, break-even threshold, date window, etc.). A motivated researcher could tune any of them to manufacture an edge. This section locks them down *before any code runs* so the result is a credible yes/no, not a retrodicted narrative. Lessons imported from `sibling-project-insights.md` §2–4 (PIT-pricing, scoring-gaming, execution realism eats the edge).

**Pre-registered hyperparameters — locked, no sweeps:**

| Knob | Locked value | Rationale |
|---|---|---|
| σ model | EWMA(λ=0.94) on 1h log-returns | RiskMetrics default; single choice, no GARCH comparison |
| EWMA lookback | 48h | Midpoint of §3.1's 24–72h range |
| Drift term `r` | 0 | No funding data local to repo; over a 25h event horizon, funding (~5–20% annualized) contributes ≤0.05% drift — second-order to σ·√T of ~1–3% on 25h |
| Snapshot cadence | 15 min | Dense enough for mean-reversion detection, coarse enough to run on a laptop |
| Ladder normalization | Re-normalize B-type yes_prices to sum to 1.0 per snapshot | Trades shape, not sum-to-1 wedge (ceded to kalshi-autoagent's bucket-sum strategy) |
| Contract type | B-type only for Week-1 | Ranges are a proper density; T-type anchors deferred to walk-forward |
| Divergence metric (primary) | max absolute gap across buckets | Interpretable, scale-invariant |
| Divergence metric (secondary) | KL(`p` ‖ `q`) | Reported but not decision-gating |
| Threshold τ (for "passing tuple" stat) | 300bp | Locked at draft time, before data seen |
| Mean-reversion horizon Δt | 1h ahead | Matches planned hourly re-hedge cadence |
| Event-selection filter | ≥500 total trades over event lifetime | Drops dead events; threshold locked here |

**Pre-registered experimental design:**

1. **Hard date split.** OHLCV overlap with Kalshi is 2025-09-17 → 2026-04-22 (~7 months). Train: 2025-09-17 → 2026-01-31. Test: 2026-02-01 → 2026-04-22. All exploration, plot-staring, parameter inspection happens on train only. **The test fold is run exactly once, at the end.** Whatever number comes out is the reported number. If we peek, the test fold is contaminated and must be discarded; at that point we either use a fresh fold or abandon.
2. **Null-shuffle benchmark as primary yardstick.** Within the test fold, randomly permute the event→timestamp alignment (pair each event with a random unrelated timestamp from the fold) and re-run the full pipeline. Report null-shuffle passing rate alongside real-signal passing rate. Real signal must beat null by ≥3× on the "fraction of tuples with max-gap > τ" stat, or the apparent edge is lognormal-fitting noise masquerading as signal.
3. **Pre-committed pass criteria.** To move forward to prototype (§7), all three must hold *on the test fold*:
   - ≥30% of tuples have max-gap > 300bp.
   - Mean-reversion half-life < 30% of remaining event life (i.e., the gap closes inside a tradeable window).
   - Null-shuffle passing rate < 10% (so real signal ≥ 3× noise).
4. **Code-first, data-second.** The three spike scripts are committed with all hyperparameters hardcoded as module-level constants before they first touch the test fold. No CLI flags for the locked knobs. If a value must change after train-fold exploration, it's an explicit follow-up commit with a changelog entry — not a silent re-run.
5. **Full-distribution reporting.** Any intermediate metric that has a natural distribution (gap magnitude across tuples, half-lives across events, realized-Sharpe estimates under different σ realizations) is reported as a distribution, not a summary statistic. No "best of N" reporting without N.
6. **Train-fold exploration is unrestricted.** Plot, inspect, change your mind, chase intuitions on train. The discipline is at the train/test boundary, not inside train. This is the one place researcher intuition earns its keep.

**Knobs explicitly left free (and why that's safe):** event-lifespan (mechanical, determined by Kalshi), strike grid (mechanical, determined by Kalshi), bucket width (mechanical, 500 USD for BTC intraday). These are observable features of the data, not researcher choices.

**What this does *not* defend against:** data-snooping from reading these deep-dive docs, upstream selection bias in the HF dataset's event coverage, Hyperliquid OHLCV gaps or data-quality issues. The first is unavoidable at solo-researcher scale; the second and third are mitigated by the null-shuffle (structural biases affect real and shuffled equally).

---

### 5.1 Week-1 data spike (the kill criterion)

**Goal:** answer *"do the two distributions disagree in a way that persists and converges?"* Binary outcome.

1. Pick a 30-day window with clean data (e.g., Dec 2024 when `KXBTC-25JAN` series is heavily traded).
2. For ~50 high-volume BTC intraday range events in that window, reconstruct `F_K(x; t, T)` at a 15-min cadence across the event's lifespan.
3. For the same timestamps, fit `F_P(x; t, T)` from Hyperliquid spot + funding + EWMA(1h) σ.
4. Compute the per-bucket gap `p_i - q_i` and max-gap statistic at every snapshot.
5. Compute realized convergence: at the next snapshot Δt ahead, how much does the max-gap change? Regress `Δgap` on `gap` to estimate mean-reversion speed.
6. Report: distribution of gaps, convergence half-life, what fraction of (event, timestamp) tuples have gaps > break-even threshold.

**Pass criterion:**
- ≥30% of tuples have max-gap > 300bp.
- Mean-reversion half-life < 30% of remaining event life (so convergence happens inside the window we can trade).
- Gap direction is consistent across tuples (not random noise).

**Kill criterion:** gaps are indistinguishable from Gaussian noise around zero, OR gaps exist but don't mean-revert (structural offset rather than convergence).

One week of work for a repo-local team of one. No live trading, no API integration, just parquet reads + fits + plots.

### 5.2 Walk-forward (month 1)

Same analysis, split the 2024–2026 HF dataset into 6-month non-overlapping windows. Require:
- Mean-reversion speed stable across windows (±50%).
- Gap-direction sign stable (tails consistently overpriced; interior consistently underpriced, or vice versa).
- No regime where the relationship breaks entirely (e.g., bull-run-of-2025).

Drop contract classes that fail. Expected surviving universe: BTC intraday, ETH intraday, maybe BTCD daily. XRP/DOGE/SHIBA likely too thin.

### 5.3 Paper trading (month 2)

Integrate into the existing paper-trading infra (`data/paper/manifest.toml` already supports multi-strategy; extend with a second strategy entry). Simulate Kalshi + perp fills at executable prices (bid/ask, not mid). Target 4–6 weeks of paper data before any live consideration.

**Pass criterion:** Sharpe > 1.0 after all fees, hedging cost, and slippage. Gap-convergence in line with Week-1 spike predictions. LLM regime-classifier accuracy > 70% on hand-labeled catalyst days.

### 5.4 Live, small (month 3+)

0.1% NAV per event, capped at 1% total NAV deployed simultaneously. Running alongside the PM Underwriting paper book so the two compete for research attention, not capital.

---

## 6. Risks and failure modes

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| **Lognormal reference is wrong.** Perp returns have fat tails and skew; lognormal mis-fits the tails systematically. | High | Medium | Compare to empirical-distribution reference (bootstrap from recent BTC_PERP 1h returns) as secondary benchmark; alert when lognormal and empirical diverge. |
| **Kalshi ladder is noisy at the tails.** The very-OTM strikes have thin volume and stale quotes. | High | Medium | Volume/quote-age filter per strike; use only buckets with recent two-sided activity. |
| **Delta-hedge slippage compounds.** Hourly re-hedging accumulates fees; if the event is calm, fees eat the entire edge. | Medium | High | Hedge only when Δ drifts beyond a tolerance band; don't re-hedge on every tick. |
| **Both distributions wrong simultaneously during regime shift.** Exploit, hack, macro print — the perp moves 5%, Kalshi re-prices, divergence widens then re-narrows unpredictably. | Medium | High | LLM catalyst classifier pauses entries on flagged events; hard stop-loss on mark-to-market. |
| **Funding-rate forward curve is not observable cleanly.** Hyperliquid publishes current funding; the forward path is implied by premium index trajectory, which is noisy. | Medium | Low | Treat funding-term-structure as a rough prior; re-fit hourly rather than locking in at entry. |
| **Kalshi maker-fee advantage disappears.** Product change, fee structure update. | Low | High | Monitor; strategy tolerates up to ~0.5¢/contract taker without losing edge at tail strikes. |
| **Correlation across same-day events.** Two overlapping BTC intraday events on the same calendar day are not independent. | High | Low | Treat overlapping events as one effective bet; cap concurrent exposure. |
| **Crypto catalyst moves Kalshi before perp.** Reverse of the usual Kalshi-leads case; our hedge lags the true market. | Low | Medium | Same mitigation as macro-catalyst: LLM flags crypto-specific news; pause. |

The two risks that actually matter: **lognormal reference wrong** and **delta-hedge slippage compounds**. The Week-1 spike directly tests the first (if gaps don't mean-revert, lognormal is not a useful reference). The hedging-cost simulator in the prototype stage directly tests the second.

---

## 7. What a minimal viable prototype looks like

Two weeks of scoped work after the Week-1 spike passes:

1. **`scripts/reconstruct_kalshi_ladder.py`** — from `data/kalshi_hf/`, output parquet keyed by `(event_ticker, snapshot_ts, strike_midpoint) → yes_mid`. Range: BTC intraday (`KXBTC-*`) only; 2024-10 through 2026-01.
2. **`scripts/fit_perp_implied_dist.py`** — given spot + funding + σ at each snapshot_ts, output `(event_ticker, snapshot_ts, strike_midpoint) → q_i`.
3. **`scripts/divergence_study.py`** — join the above two, compute per-snapshot max-gap, bucket gap, realized ΔS and Δgap to next snapshot. Produce the Week-1 spike output: gap distribution plot, convergence regression.
4. **`scripts/hedging_cost_sim.py`** — given a candidate Kalshi position at a snapshot, simulate the full trade lifecycle (fills, hourly re-hedge, exit at expiry), report net PnL per event under realistic fee/slippage assumptions.

Output after two weeks: a Sharpe estimate from historical simulation, stable-or-not verdict from walk-forward, and a go/no-go on building the live pipeline.

---

## 8. What we'd be watching for in the first 90 days

**Green flags:**
- Week-1 spike: ≥30% of (event, ts) tuples have max-gap > 300bp with mean-reversion half-life inside the remaining event life.
- Month 1 walk-forward: gap-direction sign stable across 6-month windows; no "everything flips" regime.
- Hedging-cost sim: net Sharpe > 1.0 before any LLM overlay.
- At least one *non-obvious* divergence pattern (e.g., Kalshi systematically overpricing the downside tail but not the upside) — that's where the audience-mismatch edge would show up structurally.

**Red flags:**
- Gaps exist but are symmetric around zero with no mean-reversion — the two surfaces are noisy estimates of the same true distribution and we're measuring noise, not signal.
- Hedge PnL dominated by perp-leg slippage rather than Kalshi-leg capture — re-hedging cost structure doesn't work at the gap sizes we're seeing.
- Gap direction flips between 6-month windows — the edge is regime-dependent and unstable.
- LLM catalyst classifier either pauses entries on everything (false-positive catalyst detection) or never pauses (misses real regime shifts).

If two or more red flags after Week-1 and walk-forward, pivot to #4 (Kalshi ↔ crypto narrative spread) which is still queued and has its own prospectus at [`deep-dive-kalshi-crypto-narrative-spread.md`](deep-dive-kalshi-crypto-narrative-spread.md).

---

## 9. Why this is the right second track

Three reasons:

1. **It fills the one structural gap in the portfolio.** Every sibling project and the in-progress paper book trades within a single venue. The biggest portfolio-level improvement available is a genuinely cross-market trade — and this is the cleanest one we have infrastructure for. `sibling-project-insights.md` flags this gap as #1 priority.

2. **Its returns are uncorrelated with the PM Underwriting book.** PM Underwriting is sports-parlays + crypto-longshots directional, calibration-driven. This is BTC/ETH structural, convergence-driven, delta-neutral. Drawdowns in the two books are driven by totally different things: one by sports-parlay calibration shift, the other by lognormal-assumption break during regime transitions. A portfolio holding both has genuine diversification, not just "more trades."

3. **It has the cleanest kill criterion of anything in the queue.** One week of parquet reads + lognormal fits + divergence stats gives a binary answer. The only strategy in the shortlist with a comparably cheap kill test is #4, and #4 is still queued as the immediate fallback.

---

## 10. Open questions

1. **Which perp σ model?** Start with EWMA(λ=0.94) on 1m returns. Compare to GARCH(1,1) in walk-forward. Could also try a realized-vol-jump model (recognizes that BTC has regime-dependent vol-of-vol). Parking-lot until Week-1 spike shows whether the model choice is first-order.
2. **How to handle the sum-to-1 constraint on Kalshi.** The ladder prices sum to 1 + fee wedge, which kalshi-autoagent's bucket-sum strategy already trades. Do we (a) re-normalize and trade the shape, (b) require strategies to co-exist without conflict, or (c) let the bucket-sum strategy take the wedge and us take the shape? Probably (c), but worth confirming with the sibling.
3. **ETH as a second underlying: ship simultaneously or sequentially?** Argument for simultaneous: doubles the trade density, same code. Argument for sequential: let BTC walk-forward expose regime issues before adding correlated complexity. Lean sequential.
4. **Hedging on Hyperliquid only, or also spot?** Spot gives cleaner delta but costs more (no leverage). Perp-only hedging is cheaper but introduces funding-path risk. Start perp-only, measure funding drag, decide.
5. **Funding-forward-curve extraction.** Hyperliquid publishes current funding and premium index. The forward curve is implied by premium index trajectory. The literature on extracting term-structure from a perp's premium index is thin; we may need to do the math ourselves. Flag as research sub-task.

---

## 11. The next action

If this prospectus is accepted, the immediate next action is the Week-1 data spike:

1. Write `scripts/reconstruct_kalshi_ladder.py` — parquet reads + ladder reconstruction for `KXBTC-*` events, 2024-10 through 2026-01.
2. Write `scripts/fit_perp_implied_dist.py` — lognormal fitter from spot + funding + EWMA σ.
3. Write `scripts/divergence_study.py` — compute gap distribution and mean-reversion regression.
4. Produce one plot: gap-magnitude CDF overlaid with break-even threshold. Produce one number: expected gross Sharpe before hedging costs.
5. Report findings in a short note appended to this doc. Decide whether to continue to prototype (§7) or pivot to #4.

That is the single experiment that answers the core question. Expected cost: one week.

---

## 12. Week-1 findings (2026-04-22)

**Pre-registered verdict: FAIL on the convergence-trade formulation. Do not proceed to §7 prototype.**

### Scripts run

- `scripts/reconstruct_kalshi_ladder.py` — 323 KXBTC-* B-type events survived the ≥500-trades filter (of 2,196 in window)
- `scripts/fit_perp_implied_dist.py` — 8,597 unique (event, snapshot) perp-implied CDFs; BTC spot range $83.6K–$125K; annualized σ p10/p50/p90 = 0.18 / 0.37 / 0.60
- `scripts/divergence_study.py` — 4,629 snapshots passing completeness ≥ 0.75; time-split train (2,757) / test (1,872) at 2026-01-10

### Dataset-coverage revision committed before test-fold inspection

- Original §5.0 window 2025-09-17 → 2026-04-22 assumed HF data through present. Inspection revealed HF markets end 2026-01-30, trades end 2026-01-28. Split revised to train=2025-09-17 / test=2026-01-10 in the same commit that ran the first divergence pass.
- `MIN_LADDER_COMPLETENESS=0.75` added to the §5.0 locked list *after* train-fold ladder inspection (most snapshots early in an event's life have partial trade coverage across buckets; a completeness filter is required for the renormalized `p_i` to be a meaningful density). Documented as train-fold discovery.

### Pre-registered criteria

| Criterion | Threshold | Test fold | Decision |
|---|---|---|---|
| (a) Fraction of tuples with max-gap > 300bp | ≥ 0.30 | **0.955** | PASS (trivially — threshold was too lax) |
| (b) 1h mean-reversion half-life < 30% of median remaining event life (10h) | < 3.0h | **NaN** (β ≈ +0.013) | **FAIL** |
| (c) Null-shuffle passing fraction | < 0.10 | **0.953** | **FAIL** (threshold useless at this gap magnitude) |

### What the data actually shows

| Fold | n | Median gap | p90 gap | Mean KL | Reversion β | Half-life |
|---|---|---|---|---|---|---|
| Train | 2,757 | 12.8% | 38.3% | 3.45 | −0.054 | 12.5h |
| **Test (real)** | **1,872** | **9.1%** | **32.8%** | **3.54** | **+0.013** | **NaN (no reversion)** |
| Test (null) | 1,872 | 24.9% | 76.1% | 7.92 | −0.86 | 0.35h |

The null-shuffle permutes `(spot, sigma, years_to_close)` across event-snapshot pairs in the test fold and re-derives `q_i`. Real-pair gaps are real — null-pair gaps are not.

### Interpretation

Two facts from the table:

1. **The Kalshi↔perp alignment is real.** Real-pair median gap is 9.1% vs. null-pair 24.9% — **ratio 0.37**. Scrambling which BTC spot/σ/term is paired with which event nearly triples the divergence. The two markets *are* anchored to the same underlying; there is genuine cross-market information.
2. **The gaps don't converge — they're structural shape mismatch.** The pre-registered primary signal required divergences to mean-revert within event life (convergence trade). Test-fold regression shows β ≈ 0, i.e., today's gap has no predictive power for tomorrow's gap change. Gaps are persistent, not oscillatory.

What this likely reflects: the lognormal-at-EWMA(0.94, 48h)-σ reference is a *wider* distribution than Kalshi's implied — heavier tails, less peak near spot. Kalshi's empirical shape appears leptokurtic relative to lognormal. The resulting gap is a persistent per-bucket wedge (Kalshi concentrates mass near spot; lognormal spreads it), not a short-term mispricing that closes.

A convergence trade against such gaps would short the "excess" buckets (where p > q) and long the "deficient" buckets (p < q), expecting them to revert. They don't revert. So the trade doesn't work as specified.

### Why the two failures compound

Criterion (c) — null passing fraction < 10% — was operationalized as a threshold-count, but both real and null sit at 95% above 300bp because the lognormal reference itself produces large gaps. A better discriminator is the *magnitude ratio* (0.37, reported as secondary). But even this stronger signal-vs-noise reading doesn't rescue the thesis: real gaps are real, they just don't convert to tradeable convergence.

### Decision

**Do not proceed to §7 prototype as written.** The convergence-trade framing is falsified. Two narrower next moves exist:

**Option A — Pivot to #4 (Kalshi↔crypto narrative spread).** As pre-committed in §8. Deep-dive already complete at `deep-dive-kalshi-crypto-narrative-spread.md`; one-week FOMC event study is the natural next step. This is the cleanest move and matches the pre-registration.

**Option B — Reformulate #10 before pivoting.** The 0.37 gap ratio is suggestive: real cross-market alignment exists, the convergence form just doesn't monetize it. Candidate reformulations:
- **Empirical-bootstrap reference** instead of lognormal. Draw from historical 25h BTC returns to build `q_i` — removes the shape-mismatch bias that dominates the current gap.
- **Residualized divergence**: fit the average per-bucket-position wedge on train, subtract it at each snapshot, trade only the residual. This is essentially "calibrate the lognormal out."
- **Directional rather than convergence**: instead of betting on `p→q`, bet on next-snapshot `p` being closer to current `q` than to current `p` when the gap is large (i.e., Kalshi catches up to the perp's view, not the other way around).

Each reformulation is itself a new pre-registration exercise — no free parameters left to chase.

**My recommendation:** Option A. The pre-registration process worked: the thesis as specified was tested and failed on the convergence criterion, which is its load-bearing claim. The right move is to honor that and pivot. Option B reformulations are attractive but would be three more weeks of research before any trading, and #4 is ready now with its own deep-dive and a 1-week FOMC event study queued. If #4 also fails, Option B reformulations are the next-next candidate.

### Artifacts

- `data/vol_surface/kalshi_ladder.parquet` (135,938 rows)
- `data/vol_surface/perp_implied.parquet` (131,637 rows)
- `data/vol_surface/divergence_panel.parquet` (4,629 rows, one per snapshot)
- `data/vol_surface/week1_decision.txt` (auditable decision log)

---

## 13. Investigation plan (post-Week-1) — 2026-04-22

**Decision (2026-04-22):** Do not pivot to #4 yet. The 0.37 real/null gap ratio is a blinking light that real cross-market information exists; the convergence form was the wrong instrument to measure it. Priority: exhaust the possibility that a systematic cross-market exploit exists before moving on. Time is the friend here — the PM Underwriting paper book generates return data in parallel and isn't blocked by this work.

### 13.1 Three-phase plan

**Phase 1 — Diagnostic on existing HF data (~3–5 days).** Four pure measurements on the current panel (no new hyperparameters, no optimization). Each is a falsifier for a specific reason the Week-1 test may have mis-measured a real signal:

| # | Diagnostic | What it tests | Falsifies |
|---|---|---|---|
| D1 | Per-bucket-position signed gap | Gap indexed by `(strike_mid − spot) / bucket_width` at each snapshot; look for a consistent sign by relative position | "Gap is a structural wedge" (tradeable post-calibration) vs. "random per-event noise" |
| D2 | Terminal-convergence isolation | Mean |gap| and KL-divergence as a function of fraction-of-event-life-elapsed | "Gaps converge mechanically but only in the last N% of life" — averaged regression masked it |
| D3 | Empirical-bootstrap reference | Replace lognormal `q_i` with `q'_i` drawn from rolling 25h BTC return history; recompute all gaps | "Lognormal reference family is wrong; signal is there with the right shape" |
| D4 | Moderate-volume universe | Re-run the pipeline on events with `n_trades ∈ [100, 500)` — the ones excluded by the current filter | "Edge lives in mid-volume events where Kalshi is thin enough to carry mispricings" |

**Gate at end of Phase 1:** if any diagnostic points to real exploitable structure, proceed to Phase 2 (data pipeline). If all four definitively kill the thesis, pivot to #4 and Phase 2 becomes a separate infrastructure project rather than a #10 blocker.

**Phase 2 — In-house data pipeline (~1–2 weeks, blocking).** Build Kalshi + Hyperliquid native ingest so Phase 3 runs on data we own end-to-end. Scope, design, and rationale in [`docs/implementation/data-pipeline.md`](../implementation/data-pipeline.md). Blocking dependency for Phase 3 re-validation — quantitative conclusions require clean, known-provenance data.

**Phase 3 — Re-validate on fresh + cleaner data (~1 week).** Re-run Phase 1 diagnostics and the original Week-1 spike on in-house data extended through April 2026 (~3 months more than HF). If Phase 1 findings replicate, we have a real signal on clean data and can scope the reformulated prototype. If they don't replicate, we've learned the HF data had a subtle issue and avoided a worse outcome.

### 13.2 Decision gates

- After Phase 1: continue ↔ pivot to #4.
- After Phase 2: in-house data validated against TrevorJS HF on overlap window (≤ random-trade-ordering noise) ↔ investigate data-quality discrepancy.
- After Phase 3: Phase 1 findings replicate ↔ they don't; if they don't, one more round of diagnostic work or pivot.

### 13.3 What's explicitly *not* in Phase 1

- No new hyperparameter sweeps.
- No prototype execution code.
- No new LLM classifier — the LLM's role was specified in §3.3 and isn't relevant until we have a tradeable signal.
- No attempt to tune existing Week-1 hyperparameters to "rescue" the result — if the thesis needs reformulation, that's a new pre-registration exercise, not a retrofit.

### 13.4 Methodology discipline for Phase 1

Same discipline as §5.0 carries: each diagnostic has a pre-registered output format and a pre-committed interpretation rule. The four diagnostics run on the full post-completeness-filter panel (both train and test — we already know the test-fold result under the original measurement, so the added risk from using both folds for descriptive statistics is small). Findings get written up in §14 before any further action. No cherry-picking by slicing the fold or the universe after seeing results.

---

## 14. Phase 1 diagnostic findings (2026-04-22)

**Pre-registered gate: 1 of 4 diagnostics passes → proceed to Phase 2.** But the passing diagnostic reframes the thesis in a way that requires a user decision before continuing.

### 14.1 Results

| # | Diagnostic | Pre-registered rule | Outcome | Pass? |
|---|---|---|---|---|
| D1 | Per-bucket-position signed gap (renorm + raw) | \|mean\| > 3pp AND \|t\|  > 3 in both spaces | Renorm: −10.08pp at rel_pos=0, t=−50 (n=4,601). Raw: +16.78pp at rel_pos=+17, t=+17.5 (n=901) | **PASS** |
| D2 | Terminal convergence (gap vs. life decile) | slope < −0.005/decile | slope = −0.0005/decile (6.1pp gap flat across life) | FAIL |
| D3 | Empirical-bootstrap reference vs. lognormal | emp median < 50% of lognormal median | emp / lognormal ratio = 1.016 (identical) | FAIL |
| D4 | Moderate-volume universe (n_trades 100–500) | gap > 2× high-vol AND β < −0.10 | gap ratio = 1.23, β = −0.087 | FAIL |

### 14.2 What the passing diagnostic actually found

D1's signal is structural and massive, but it is the **favorite-longshot bias**, not a new cross-market phenomenon.

In raw space (prices you'd actually trade at), Kalshi systematically prices far-OTM range buckets at meaningful probabilities (~5–15¢) where the lognormal assigns near-zero probability. The wedge peaks at rel_pos ±17 (~$8,500 OTM at a $500 bucket width) with mean signed gap +16.78pp and t-stat 17.5. This is the classic small-probability-overweighting prospect-theory effect documented across sports betting, horse racing, and prediction markets — and already identified in this project's Phase 1 PM Underwriting calibration work (crypto longshots show favorite-longshot bias in 5/20 bins).

D3 closes an important door: the lognormal reference and an empirical-bootstrap from BTC's own 25h return distribution give median gaps that agree to within 2%. The lognormal is not the wrong reference family. Kalshi's distribution really does deviate from BTC's true terminal-price distribution in the tails — the deviation isn't a lognormal-fitting artifact.

### 14.3 What the failing diagnostics tell us

- **D2 (no terminal convergence):** Gaps don't mechanically shrink across event life. Consistent with the wedge being a persistent structural bias in how Kalshi traders price tails, not a short-term mispricing that resolves as expiry approaches.
- **D3 (empirical ≈ lognormal):** Rules out "we just need a better reference model" — the two distributions agree on BTC's underlying stochastics. The gap is in Kalshi's pricing, not our measurement.
- **D4 (moderate-volume not materially different):** The bias is present in both high- and moderate-volume events, with only modestly larger gaps on thinner events. No hidden gold mine in the low-volume slice.

### 14.4 Thesis reframe

The #10 prospectus proposed: *cross-market arbitrage between a prediction-market-implied terminal distribution and a perp-implied terminal distribution, with delta-neutral hedging*. The phenomenon we actually found is: *Kalshi exhibits favorite-longshot bias in crypto range contracts, which shows up as a persistent wedge vs. any accurate reference for BTC's terminal-price distribution*.

These are related but distinct:

| Feature | Prospectus #10 | Phase 1 finding | PM Underwriting (Phase 1–3) |
|---|---|---|---|
| Source of edge | Cross-market audience mismatch | Prospect-theory tail overpricing | Category-specific calibration gaps |
| Signal per trade | Divergence between two distributions | Mispricing at far-OTM buckets | Mispricing at extreme-price bins (80–95¢ or 5–20¢) |
| Market neutrality | Delta-neutral via perp | **Not inherent — but achievable via perp hedge** | Not hedged; directional per-trade |
| Holding period | Intraday convergence | Hold to event resolution | Hold to event resolution |

The delta-neutrality angle *is* net-new. PM Underwriting takes directional Kalshi positions and accepts the path-dependent loss distribution (9:1 lottery payoff profile — see `sizing-reevaluation.md`). A delta-hedged version of the same longshot-bias edge would:

- Convert the lottery-ticket payoff to a more continuous P&L stream
- Allow larger per-trade sizing under a given σ budget
- Add hedging cost (perp fees + funding drag + tracking error from lognormal mis-specification vs. BTC's actual path)

Whether that trade-off is net positive is an open empirical question.

### 14.5 Decision point

The phase-gate formally passes (1/4 ≥ 1). But before investing 2 weeks in Phase 2 data pipeline work, the investor (not just the analyst) needs to decide:

**Option A — Continue #10 as delta-hedged longshot bias.** Treat the finding as a genuinely new strategy variant: same Kalshi edge PM exploits, but market-neutralized via perp hedging. Phase 2 data pipeline is still warranted. Phase 3 re-validates with clean data and quantifies the hedging-cost drag to decide if the market-neutral version clears a meaningful Sharpe hurdle over the directional PM version.

**Option B — Fold the finding into PM Underwriting as a hedging overlay.** PM is already running; adding a perp-hedge leg is a ~1-week enhancement rather than a standalone track. Abandon the #10 standalone concept. Proceed to #4 (Kalshi ↔ crypto narrative spread) as the next R&D track — it targets a genuinely different information-transmission phenomenon.

**Option C — Declare #10 done, pivot to #4.** The phase gate technically passed, but the signal that passed is one we already trade. Move on; revisit delta-hedging as a potential PM enhancement if/when the paper book shows a tail-risk profile that warrants it.

My recommendation is **B**: the Phase 1 finding is real but too close to what PM already monetizes to justify a separate research/data-pipeline investment just for #10. Folding delta-hedging into PM is a lighter commitment that captures the incremental value; #4 is a structurally different edge and deserves the next track slot. The data-pipeline build (Phase 2) remains load-bearing regardless — it should proceed on its own merit as core infrastructure rather than as a #10 blocker.

### 14.6 Artifacts

- `scripts/vol_surface_diagnostic.py` — locked-hyperparameter diagnostic runner
- `data/vol_surface/diagnostic/d1_signed_gap_by_rel_position.parquet` (renorm + raw space tables)
- `data/vol_surface/diagnostic/d2_gap_by_life_decile.parquet`
- `data/vol_surface/diagnostic/d3_gap_emp_vs_lognormal.parquet`
- `data/vol_surface/diagnostic/d4_moderate_volume_gaps.parquet`
- `data/vol_surface/diagnostic/summary.txt` — plain-text decision record
