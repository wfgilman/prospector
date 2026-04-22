# Strategy Families — Candidate Shortlist

This document inventories strategy families that fit the constraint set (crypto exchanges + non-securitized markets like Kalshi, no securities/equities/ETFs, LLM-suitable, local 16GB hardware). Each family is scored on four axes:

- **LLM fit** — does the reasoning role match what a 13B model is good at (categorical, narrative, text-based)?
- **Trade density** — enough events to validate statistically (≥100/quarter)?
- **Novelty** — can we plausibly discover an edge that is not already crowded?
- **Tractability** — can we build it with the data and infrastructure we have?

Eight families are listed. One is selected for the deep-dive prospectus (see `deep-dive-kalshi-crypto-narrative-spread.md`).

---

## 1. Funding-rate carry + regime classification

**Shape:** Long spot (or basis) vs short perp when funding is positive; collect funding. LLM classifies whether a funding regime is likely to persist (based on news, narrative, protocol events) versus mean-revert.

**Cross-domain parallels:** FX carry trade (borrow low-yield, lend high-yield) + Soros-style reflexivity (carry regimes persist until they don't, and the "until" is usually narrative-driven).

**LLM fit:** Medium. Classifying regime persistence from news is a reasoning task; executing the carry is not.

**Trade density:** High. Hyperliquid funding pays hourly; multiple venues × multiple coins gives hundreds of decision points/month.

**Novelty:** Low. Delta-neutral funding arb is the most crowded trade in crypto. Classification overlay might add alpha but competes with well-resourced desks.

**Tractability:** High. Funding data is clean and public; execution is straightforward on Hyperliquid + any CEX.

**Verdict:** Viable baseline. Not the prospectus pick — too crowded, LLM value limited to a second-order classifier.

---

## 2. Token unlock / vesting cliff calendar

**Shape:** Token supply schedules are public. Unlocks of 1–10% of circulating supply typically depress price in a predictable window (−30 to +14 days). LLM reads project communications, investor commitments (lockup extensions, OTC deals) to classify whether a given unlock will mark-to-market or be absorbed.

**Cross-domain parallels:** Equity insider-lockup expiry (post-IPO). Established finance literature documents significant underperformance in the 30 days after lockup expiry. Crypto should share this shape but has more surface area (hundreds of tokens, weekly events).

**LLM fit:** High. Reading project Discord, Medium posts, team tweets to classify unlock posture is a natural language task.

**Trade density:** Moderate. ~10–30 significant unlocks/month across top-200 tokens.

**Novelty:** Medium. Known effect; edge is in the LLM's ability to separate "routine dump" from "team has OTC'd" events. Some funds do this manually.

**Tractability:** Moderate. Unlock data is aggregated by Token Unlocks, CryptoRank. Hyperliquid lists ~130 perps, which covers most large-cap unlocks but not all mid/small-caps.

**Verdict:** Strong alternative. Worth revisiting if the prospectus pick doesn't pan out.

---

## 3. Event-driven reaction to on-chain signals

**Shape:** Monitor chain state for catalysts — large wallet movements, governance proposal submission, liquidity migrations, exploit indicators. LLM assesses severity and reads protocol response to classify actionable vs. noise. Trade the perp on the affected token.

**Cross-domain parallels:** Event studies in equity markets (Fama/MacBeth/Eckbo) — systematically measure return around defined events. Same framework, new event set.

**LLM fit:** High. Interpreting governance proposal text, protocol incident reports, exploit post-mortems is where LLMs shine.

**Trade density:** High if cast wide across 100+ tokens. Moderate per-token.

**Novelty:** Medium-high. On-chain specialists exist (Nansen, Arkham subscribers) but few combine systematic chain state with automated LLM classification and algorithmic execution.

**Tractability:** Low-medium. Requires chain indexing infrastructure (Dune/Flipside/private node) that we don't have yet.

**Verdict:** High ceiling but heavy infrastructure lift. Hold.

---

## 4. Prediction market ↔ crypto cross-market (Kalshi-crypto narrative spread)

**Shape:** Kalshi contracts on macro outcomes (Fed rate decisions, CPI prints, elections, SEC enforcement, ETF approvals) have causally-linked downstream effects on crypto. When Kalshi implied probabilities move, crypto *should* move by a predictable β — but often doesn't immediately. Trade the lagging market in the direction implied by the leading one. LLM's job is mapping contracts to exposures and classifying each Kalshi move as news-driven vs. noise.

**Cross-domain parallels:** Information-transmission trades between related markets (bond futures → FX, S&P futures → individual equities, weather → gas prices). Each starts with the observation that two markets trading the same underlying risk have measurable lag between them.

**LLM fit:** **Very high.** Every Kalshi contract is literally a question; every move is an updated answer. The mapping "how would this answer move crypto?" is explicit narrative reasoning. No other strategy here is so directly shaped like an LLM task.

**Trade density:** High. Kalshi has hundreds of active contracts; Hyperliquid has ~130 perps. The cartesian product × intraday moves yields thousands of candidate events per month.

**Novelty:** **High.** The two markets have non-overlapping participant populations (Kalshi: macro/political retail; crypto: trading-first, distracted by 1000 alts). Cross-market mispricings from audience-mismatch are structurally different from within-market arb and less picked-over.

**Tractability:** High. Kalshi has a REST API and historical CSV exports. Hyperliquid data we already have. Execution is single-leg (Hyperliquid perp) — no cross-venue settlement risk if we trade the crypto leg only.

**Verdict:** **Prospectus pick.** See deep-dive doc.

---

## 5. Stablecoin depeg classification

**Shape:** USDC, USDT, DAI, FRAX micro-depeg (~0.1–1%) on stress events. LLM reads Fed/banking news, reserve-attestation releases, governance proposals to classify depeg cause (transient liquidity vs. solvency). Trade the basis back to peg when classified benign.

**Cross-domain parallels:** Sovereign bond CDS during crises (Greek bond 2011, Russia 2022) — markets overshoot on fear and recover on clarity.

**LLM fit:** High. Distinguishing liquidity from solvency is a text-interpretation task.

**Trade density:** Low. Significant depeg events are rare (~10/year), catastrophic ones rarer still. Insufficient for systematic validation.

**Tractability:** Medium. Execution requires CEX spot + stablecoin — straightforward but fragmented.

**Verdict:** Too rare. Interesting as a tail-risk overlay, not a standalone strategy.

---

## 6. Cross-venue perp funding divergence

**Shape:** Funding rates diverge between Hyperliquid, Binance, Bybit, OKX. Take opposing positions across venues and collect the spread. Pure mechanical arb; LLM adds minimal value.

**LLM fit:** Low. This is a pure-latency mechanical trade.

**Trade density:** High.

**Novelty:** Low. Crowded; requires low-latency infrastructure we don't have.

**Verdict:** Infrastructure mismatch. Skip.

---

## 7. Liquidation cascade prediction

**Shape:** Monitor open interest and liquidation price clusters on Hyperliquid + GMX + dYdX. When clusters form near current price, gap risk is elevated. LLM combines chain state with news/sentiment to predict cascade likelihood. Short the affected asset ahead of the gap, or buy the bounce after.

**Cross-domain parallels:** Margin-call cascades in 1987 portfolio-insurance crash, LTCM 1998, 2008 deleveraging. Well-studied in equities and fixed income.

**LLM fit:** Medium. The cascade prediction is more quantitative than textual; LLM's role is secondary.

**Trade density:** Moderate (one or two major cascades per month; many micro-cascades).

**Tractability:** Moderate-low. Requires liquidation-price indexing per venue; Hyperliquid publishes it, others don't uniformly.

**Verdict:** Promising but data-heavy. Not this round.

---

## 8. Kalshi-native inefficiencies (no crypto leg)

**Shape:** Trade Kalshi standalone — weather forecasts vs. NOAA models; sports lines vs. Vegas odds; election implied probabilities vs. 538/polling aggregators. LLM reads forecast discussions, poll methodology, narrative context to classify when the Kalshi price is meaningfully off.

**Cross-domain parallels:** Sports-betting model arb (Pinnacle vs. retail books), weather-derivative trading (which was a thing before securitization).

**LLM fit:** High for some sub-markets (weather, sports narrative), low for others (implied-probability arb is pure math).

**Trade density:** High. Kalshi has hundreds of contracts, most with liquid two-sided markets.

**Novelty:** Medium. Sharp Kalshi-native traders exist and are hard to compete with on pure math. Novelty would require a genuinely original signal source.

**Tractability:** High. Kalshi API is clean.

**Verdict:** Strong standalone alternative. Could be pursued in parallel with the prospectus pick if they share infrastructure (they do — Kalshi data layer).

---

## Summary table

| # | Family | LLM fit | Density | Novelty | Tractable | Pick? |
|---|---|---|---|---|---|---|
| 1 | Funding carry + regime | Med | High | Low | High | Baseline only |
| 2 | Token unlocks | High | Med | Med | Med | **Backup** |
| 3 | On-chain events | High | High | Med-High | Low | Hold |
| 4 | **Kalshi ↔ crypto narrative spread** | **V.High** | **High** | **High** | **High** | **→ deep-dive** |
| 5 | Stablecoin depeg | High | Low | Med | Med | Skip |
| 6 | Cross-venue funding | Low | High | Low | Low | Skip |
| 7 | Liquidation cascade | Med | Med | Med | Low | Hold |
| 8 | Kalshi-native | Mixed | High | Med | High | Parallel track |

## Why #4

Three reasons to go deep on Kalshi-crypto:

1. **LLM shape-fit is direct, not retrofitted.** Every Kalshi contract is a natural-language question, every price is a numerical answer; mapping answers to crypto exposures is the most natural reasoning task in the entire shortlist.
2. **The participant mismatch is structural and hard to arb out.** Kalshi traders are macro/politics retail; crypto traders are crypto-native. The two audiences don't share feeds, priorities, or analytical frames. Audience-mismatch arbitrage is documented in equity markets (local-bias, home-bias, foreign-retail premia) and the same shape is visible here.
3. **Data and execution are already within reach.** Kalshi has a REST API and historical data; Hyperliquid we already use. Single-leg execution on the crypto side means no cross-venue settlement risk. A credible prototype is ~100 lines of glue code on top of what we already have.

The deep-dive is in `deep-dive-kalshi-crypto-narrative-spread.md`.

---

# Expanded Families — Post-Literature Review (2026-04-15)

After a literature survey (see `literature-review.md`), review of sibling projects (see `sibling-project-insights.md`), and cross-domain brainstorming, additional families emerged. These are scored on the same four axes plus a fifth: **structural** (is this a convergence/arbitrage trade, not a directional bet?).

The key portfolio insight: all four sibling projects trade **within** a single venue. Nobody trades **across** venues. The biggest gap is cross-market strategies.

The key creative insight: the most novel strategies come from applying frameworks from unrelated disciplines (insurance, meteorology, market microstructure theory) to prediction markets and crypto — where those frameworks have never been used.

---

## 9. Prediction market underwriting (actuarial science → Kalshi)

**Shape:** Treat Kalshi as an insurance book. Build a master calibration curve from historical resolutions: at each implied probability level (e.g., 20%), measure the actual hit rate across thousands of resolved contracts. Where the curve deviates from 45° (e.g., contracts priced at 20% actually resolve 25% of the time), systematically trade the gap. Size using Kelly. Diversify across independent events. Manage the portfolio like an underwriter manages a policy book.

**Cross-domain origin:** Actuarial science. Insurance companies don't predict individual fires — they price portfolios of risks by calibrating their frequency models against historical claims data. The math is identical: revenue = Σ premiums, expected loss = Σ (actual probability × payout), profit = the gap between market price and true probability, compounded by diversification. The Favorite-Longshot Bias (documented in JPE, Management Science) is the actuarial analogue of adverse selection in insurance — retail participants overpay for tail protection.

**LLM fit:** Very high. (a) Classify events by category for segmented calibration (weather, politics, economics, crypto, sports — each may have a different bias curve). (b) Assess pairwise correlation between contracts ("are these two weather contracts for nearby cities on the same day independent?" → categorical reasoning). (c) Detect regime changes that might shift the calibration curve. (d) Flag contracts where the LLM's probability estimate diverges most from market — the fattest part of the edge.

**Trade density:** Very high. Kalshi has 420K+ historical markets for calibration. Hundreds of active contracts at any time. Every contract is a potential position.

**Novelty:** Very high. Nobody frames Kalshi as an insurance book. Individual traders exploit specific biases in specific categories; nobody has built a universal calibration surface across all Kalshi contract types and traded the portfolio-level expected value.

**Structural:** Approximately. Individual positions are directional (each is a binary bet), but the portfolio is diversified across independent events. The law of large numbers makes the aggregate converge to expected value. This is market-neutral in the actuarial sense.

**Tractability:** Very high. Historical data available via kalshi-data-collector (420K markets, 16M trades). Calibration curve is a straightforward empirical exercise. No new exchange integration needed.

**Portfolio complement:** kalshi-autoagent exploits **mathematical** constraint violations (prices must sum to 1.0). This exploits **statistical** violations (prices should be calibrated but aren't). Different signal, same execution infrastructure.

---

## 10. Cross-market implied probability surface (Kalshi ↔ Hyperliquid)

**Shape:** Kalshi crypto-price contracts ("BTC > 50k by June," "BTC > 60k by June," etc.) at multiple strikes define a discrete implied probability distribution — a volatility surface. Reconstruct it. Compare to the distribution implied by Hyperliquid BTC perp funding rate and basis. When the Kalshi-implied and perp-implied distributions disagree, take offsetting positions across venues. Delta-neutral via perp hedging.

**Cross-domain origin:** Volatility arbitrage in equity options. The canonical vol arb: compare implied vol (from options prices) to realized vol (from stock returns). Here, the "options" are Kalshi binary contracts, and the "realized vol" is encoded in perp funding and basis. The Moontower Meta blog documents the option-chain-to-prediction-market mapping. What's new is using a perp market (not options) as the reference surface.

**LLM fit:** High. The LLM maps between Kalshi contract specifications and crypto exposures, classifies divergences as structural (trade) vs. transient (skip), and adjusts the delta hedge as regime shifts.

**Trade density:** Moderate. Depends on how many Kalshi crypto-price contracts are active simultaneously.

**Novelty:** Very high. Nobody is constructing a volatility surface from Kalshi binary prices and cross-referencing it against crypto perp market-implied distributions. The two markets have completely non-overlapping participant populations.

**Structural:** Yes. Delta-hedged binary option position is market-neutral by construction.

**Tractability:** Moderate. Requires computing implied distributions from discrete binary prices (straightforward but requires care around the tails) and a live delta-hedging loop.

---

## 11. Cross-exchange perpetual funding spread

**Shape:** Different exchanges compute funding rates differently (premium index, impact pricing, caps, intervals). Hyperliquid: hourly, 4% cap. Binance: 8-hourly, variable cap. Short the high-funding perp, long the low-funding perp on a different venue. Delta-neutral. Collect the spread.

**Cross-domain origin:** FX carry trade (borrow low-yield currency, lend high-yield). Same structure, crypto substrate. Also: commodity contango arb (buy near-month, sell far-month when term structure is steep).

**LLM fit:** Low-moderate. Mostly mechanical. LLM could classify whether a funding rate spike is sustainable (news-driven positioning) vs. transient (liquidation cascade aftermath).

**Trade density:** Continuous. Multiple coins × multiple venues.

**Novelty:** Low. Well-documented (Bocconi, MDPI). But crypto-copy-bot only does Kraken spot-futures; cross-exchange perp-perp is a different, higher-density trade.

**Structural:** Yes. Delta-neutral by construction.

**Tractability:** High. Funding data is public. Requires accounts on two exchanges.

---

## 12. Weather ensemble model arbitrage (meteorology → Kalshi)

**Shape:** GFS 31-member ensemble models produce probability distributions for temperature, precipitation, snowfall. Compare to Kalshi weather contract prices. When models diverge from market, trade. Update 4× daily (00Z, 06Z, 12Z, 18Z model runs).

**Cross-domain origin:** Numerical weather prediction. Ensemble forecasting was invented because no single model run is reliable — averaging across 31 perturbations produces a calibrated probability distribution. This is the same principle as Bayesian model averaging in statistics. Apply the ensemble to Kalshi pricing.

**LLM fit:** High. Synthesize multiple model outputs, parse NWS advisories, identify systematic model biases for specific geographies (e.g., wildfire haze causing under-forecasting of max temps), detect regime transitions (El Niño/La Niña). Also: read local weather discussion (NWS AFDs) which are free-text documents with nuanced forecaster commentary that contradicts models.

**Trade density:** Daily. Multiple cities × multiple contract types (high temp, low temp, rain, snow). Seasonal variation.

**Novelty:** Medium-high. Open-source weather bot exists ($1.8K profits documented). kalshi-autoagent has a weather market maker. What's new: a systematic ensemble-model-driven directional strategy with LLM interpretation of model biases.

**Structural:** Not inherently (directional per trade). But diversified across cities and days, uncorrelated with crypto portfolio. The "structure" is the ensemble model, not a convergence trade.

**Tractability:** High. GFS data is free (NOAA). Kalshi weather contracts are liquid and well-structured.

---

## 13. Informed vs. uninformed flow classification (market microstructure → Kalshi/crypto)

**Shape:** Classify recent order flow as informed (news-driven, likely to persist) or uninformed (retail, noise, mean-reverting). Trade accordingly: follow informed flow, fade uninformed flow. Use order characteristics (size distribution, timing relative to news, price impact, clustering) as features.

**Cross-domain origin:** Kyle (1985), Glosten-Milgrom (1985) — the two most-cited papers in market microstructure. Market makers implicitly do this: they widen spreads when they detect informed flow. The LLM automates the classification step.

**LLM fit:** High. The classification "is this order flow news-driven?" is a natural language task when you can access the news timeline. The LLM reads recent headlines and compares to the timing of order flow changes.

**Trade density:** Continuous in crypto. Lower on Kalshi (thinner order flow).

**Novelty:** High. Kyle/Glosten-Milgrom have been implemented in HFT at institutional scale for equities. Nobody has applied the classification step via LLM in prediction markets or crypto.

**Structural:** Approximately. Following informed flow is directional but high-probability. Fading uninformed flow is mean-reversion. The combined portfolio is mixed.

**Tractability:** Moderate. Requires order-level data (Kalshi provides fills; Hyperliquid provides trade stream). News timeline needed for correlation.

---

## 14. Crypto convenience yield arbitrage (commodity economics → crypto)

**Shape:** In commodities, futures trade above spot when storage costs exceed convenience yield. In crypto, perpetuals trade above spot when bullish leverage demand is high (positive funding). But crypto has zero storage cost — so positive funding is PURE directional premium, not a real cost. When funding is positive and no fundamental reason exists (no airdrop, no staking event, no narrative catalyst), the premium is noise. Fade it. When funding is positive AND there's a catalyst, the premium is signal. Let it ride.

**Cross-domain origin:** Commodity storage economics (Working 1949, Brennan 1958). The theory of normal backwardation (Keynes 1930) says producers hedge by selling futures, creating a risk premium that speculators collect. In crypto, the "producers" are leveraged longs who pay funding to maintain their positions. The "speculators" (us) collect funding by providing the other side.

**LLM fit:** High. The key decision is: "is this funding rate driven by a real catalyst (airdrop, staking event, regulatory news) or by speculative excess?" That's a classification task over recent news and on-chain data.

**Trade density:** Continuous. Funding pays every hour on Hyperliquid.

**Novelty:** Medium-high. Funding arb is known; the convenience-yield framing with LLM-classified catalyst assessment is new.

**Structural:** Yes when delta-neutral (spot + short perp). The LLM classification determines whether to overlay directional tilt.

**Tractability:** High. Funding data is public. Already have Hyperliquid integration.

---

## Revised summary table

| # | Family | LLM fit | Density | Novelty | Structural | Pick |
|---|---|---|---|---|---|---|
| 1–8 | (original families) | (see above) | | | | |
| **9** | **PM underwriting (actuarial)** | **V.High** | **V.High** | **V.High** | **~Yes** | **→ deep-dive** |
| 10 | **Cross-market implied probability (Kalshi × Hyperliquid)** | High | Med | V.High | Yes | **→ deep-dive** (second R&D track, 2026-04-22) |
| 11 | Cross-exchange funding spread | Low-Med | High | Low | Yes | Proven baseline |
| 12 | Weather ensemble model | High | Daily | Med-High | ~No | Parallel track |
| 13 | Flow classification (microstructure) | High | High | High | ~Yes | Research candidate |
| 14 | Crypto convenience yield | High | High | Med-High | Yes | Enhances #11 |

## Why #9 for the deep dive

1. **It's the most genuinely novel.** Nobody treats Kalshi as an insurance book. The calibration-curve framework from actuarial science has never been applied systematically across a prediction market's full universe.

2. **It directly complements the existing portfolio.** kalshi-autoagent exploits mathematical violations (prices must sum to 1.0); this exploits statistical violations (prices should be calibrated to actual resolution rates but aren't). Different signal source, same data and execution.

3. **It has the cleanest kill criterion.** Construct the calibration curve from 420K historical markets. If the curve is flat (well-calibrated), there's no edge and we stop. If it has persistent slope deviations, the edge is measured and the strategy is bounded. A one-week data exercise answers the question.

4. **The LLM's role is deeply natural.** Categorizing events, assessing correlation, detecting regime shifts — all categorical reasoning tasks. No continuous optimization anywhere.

5. **It's leverage-friendly and scales with diversification.** The Acum model: small edge per trade, many trades, high leverage on the portfolio. Exactly the insurance-underwriting structure.

The deep-dive is in `deep-dive-prediction-market-underwriting.md`.

---

# Second R&D track selected — 2026-04-22

With PM Underwriting (#9) now in Phase 3 paper trading, #10 (Cross-market implied probability, Kalshi × Hyperliquid) has been selected as the second R&D track to run in parallel. Rationale:

- Fills the single biggest portfolio gap (every sibling project trades within one venue).
- Returns structurally uncorrelated with the PM Underwriting book (directional calibration vs. delta-neutral convergence).
- Kalshi `KXBTC-*` / `KXETH-*` range ladders are a literal 40-strike implied CDF — no surface-fitting required.
- Cleanest kill criterion of anything in the queue: one-week parquet-level divergence study against Hyperliquid perp-implied distribution gives a binary go/no-go.

Deep-dive: [`deep-dive-kalshi-hyperliquid-vol-surface.md`](deep-dive-kalshi-hyperliquid-vol-surface.md).

Fallback if #10 fails the Week-1 spike: #4 (Kalshi ↔ crypto narrative spread) — deep-dive already written, 1-week FOMC event study ready to run.

**Update (2026-04-22):** Week-1 spike failed the pre-registered convergence criterion, but the real/null gap ratio of 0.37 indicates real cross-market information the specific formulation didn't capture. Decision: *not* pivoting to #4 yet. Entering a three-phase investigation (diagnostic → in-house data pipeline → re-validate on clean data) to exhaust the systematic-exploit possibility. See [`deep-dive-kalshi-hyperliquid-vol-surface.md`](deep-dive-kalshi-hyperliquid-vol-surface.md) §13 for the plan and [`../implementation/data-pipeline.md`](../implementation/data-pipeline.md) for the now-core-competency data infrastructure scope.
