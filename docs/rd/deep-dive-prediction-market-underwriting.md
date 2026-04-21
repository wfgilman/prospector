# Deep Dive — Prediction Market Underwriting

> **Revision note (2026-04-21):** This doc is the original strategy *prospectus* from mid-April 2026, preserved as the design intent. Empirical measurement during Phase 3 shows that edge ranking systematically fills the extreme-price bins, which are 9:1 lottery-ticket payoffs rather than the insurance-premium payoff profile described in §0-3 below. The "write many small policies" framing captures the *portfolio-construction philosophy* (diversified, calibration-driven, LLN-reliant) but misrepresents the *per-trade payoff shape* the ranker actually produces. For the empirical distribution and the consequent sizing-framework reevaluation, see [`docs/rd/sizing-reevaluation.md`](sizing-reevaluation.md). For per-phase methodology, see [`docs/implementation/methodology.md`](../implementation/methodology.md) §4.7 and §6.

## 0. TL;DR

Insurance companies don't predict individual fires. They price portfolios of risks by calibrating their frequency models against decades of claims data, then charge a premium above expected loss, and rely on diversification across independent policies to converge to expected value.

This strategy applies the same framework to Kalshi. Build a master calibration curve from 420K+ historical market resolutions: at each implied probability level, measure the actual resolution rate. Where the curve deviates from the 45-degree line, systematically trade the gap. Size using Kelly criterion. Diversify across hundreds of independent contracts. Manage the portfolio like an insurance underwriter manages a policy book.

The LLM's role: (a) segment events by category for targeted calibration, (b) assess pairwise correlation between contracts to ensure true diversification, (c) detect regime changes that might shift the calibration curve, (d) flag individual contracts where its probability estimate diverges most from the market.

This complements kalshi-autoagent's existing strategies (which exploit mathematical violations like "prices must sum to 1.0") by adding a new signal source: statistical violations ("prices should be calibrated to actual hit rates but aren't").

---

## 1. The actuarial parallel

### How insurance underwriting works

An auto insurer prices a policy for a 25-year-old male driver in Houston. They don't predict whether *this specific person* will crash. They know that the historical claim rate for this demographic × geography × vehicle class is 4.2%. They charge a premium that covers 4.2% expected loss + operating costs + profit margin. They write 100,000 such policies. The law of large numbers guarantees that actual claims converge to expected claims. The profit is the premium minus the true expected loss, multiplied by volume.

Three things make this work:
1. **Calibration** — the insurer's 4.2% estimate is accurate (from decades of claims data)
2. **Independence** — individual claims are mostly independent (one crash doesn't cause another)
3. **Volume** — enough policies that the portfolio converges to the mean

### How it maps to Kalshi

A Kalshi contract priced at $0.20 (implied probability = 20%) is an insurance policy. Buying "Yes" at $0.20 is like buying a policy that pays $1.00 if the event happens. Selling "No" at $0.80 is like writing that policy.

If contracts priced at 20% actually resolve "Yes" only 15% of the time, the market is systematically overpricing these events. An underwriter who sells "No" across many such contracts earns the 5pp gap × volume.

The three requirements map exactly:
1. **Calibration** — build from 420K historical Kalshi resolutions (we have the data via kalshi-data-collector)
2. **Independence** — LLM classifies which contracts are truly independent
3. **Volume** — Kalshi has hundreds of active contracts across weather, politics, economics, crypto, sports

### Why this framework hasn't been applied

Prediction markets are young. Kalshi launched in 2021. Historical resolution data at scale has only become available in the last 1-2 years. Nobody has had enough data to build a credible calibration curve until now.

Additionally, most prediction market traders are domain specialists (a weather trader, a politics trader). They optimize within their domain. Nobody has approached Kalshi as a cross-domain insurance book because that requires (a) the actuarial framing (from a different discipline) and (b) the ability to assess correlation across domains (weather vs. politics vs. crypto). The LLM provides (b).

---

## 2. The calibration curve — the core artifact

### What it is

A calibration curve plots *implied probability* (x-axis) against *actual resolution rate* (y-axis). For a perfectly calibrated market, every point lies on the 45-degree line: contracts priced at 30% resolve "Yes" 30% of the time.

Real markets are not perfectly calibrated. Known biases:

- **Favorite-longshot bias** — longshots (5-15% implied) overpriced; favorites (85-95% implied) underpriced. Documented across sports betting, horse racing, and prediction markets for decades. Driven by prospect theory: people overweight small probabilities.
- **Calibration varies by category** — weather contracts may be well-calibrated (because ensemble models are good); political contracts may be poorly calibrated (because crowd wisdom is noisy on rare events).
- **Calibration shifts over time** — new market participants, regulatory changes, fee structure changes, and market maturation all shift the curve.

### How to build it

From kalshi-data-collector's 420K historical markets:

1. Bin contracts by their implied probability at a fixed point in time (e.g., at 50% of the contract's duration — PIT pricing, already built in kalshi-autoagent).
2. For each bin (e.g., 15-25% implied), count: how many resolved "Yes"? That's the actual resolution rate.
3. Plot implied vs. actual across all bins.
4. Repeat, segmented by category (weather, politics, economics, crypto, sports).
5. Compute confidence intervals (Wilson binomial) for each bin. Bins with <50 samples are unreliable.

### What we expect to find

Based on the academic literature and the longshot bias research:

- **Longshot overpricing** (5-15% implied) is the most robust finding. Expect actual resolution rate 2-5pp below implied.
- **Favorite underpricing** (85-95% implied) is the mirror image. Expect actual resolution rate 2-5pp above implied.
- **Mid-range** (30-70% implied) is likely well-calibrated on aggregate but may have category-specific biases.
- **Category variation** is expected: weather contracts (informed by models) should be better-calibrated than political contracts (informed by vibes).

### Kill criterion

If the calibration curve is within ±2pp of the 45-degree line across all bins with n > 100, the market is well-calibrated and there's no edge. Stop. This is a clean, measurable gate.

---

## 3. The portfolio construction — how the underwriter trades

### Step 1: Identify mispriced contracts

For each active Kalshi contract:
- Look up its implied probability.
- Compare to the empirical resolution rate for that bin × category.
- Compute the edge: `edge = implied_probability - actual_resolution_rate` (for "No" trades).
- If edge > minimum threshold (e.g., 3pp after fees), it's a candidate.

### Step 2: Assess correlation

This is where the LLM earns its keep. Before adding a contract to the portfolio, classify its independence from existing positions:

- **Same-event contracts** are perfectly correlated (e.g., "BTC > 50k by June" and "BTC > 55k by June" — if the first resolves Yes, the second is likely Yes too). Don't count both.
- **Same-category same-day contracts** may be correlated (e.g., two weather contracts for NYC and Newark on the same day). Discount.
- **Cross-category contracts** are generally independent (a weather contract and a political contract). Full diversification credit.

The LLM prompt: "Given contract A ('{contract_A_description}') and contract B ('{contract_B_description}'), assess whether their outcomes are likely correlated. Answer: independent, weakly correlated, or strongly correlated. One sentence explaining why."

This is a categorical reasoning task. It's the most natural LLM application in the entire strategy.

### Step 3: Size using Kelly

For each position:
```
kelly_fraction = (p_true - p_market) / (1 - p_market)    # for "No" trades
```
where `p_true` is from the calibration curve and `p_market` is the Kalshi price.

Use fractional Kelly (25-50%) to account for calibration uncertainty. Cap individual position at 1% of portfolio NAV.

### Step 4: Manage the book

- **Rebalance weekly** — re-check calibration, add new contracts, close contracts approaching resolution (avoid terminal gamma).
- **Monitor correlation** — if an external shock creates cross-contract correlation (e.g., a weather system affecting multiple cities), reduce exposure.
- **Track actual vs expected P&L** — if cumulative P&L deviates >2 standard deviations below expected, pause and re-examine calibration curve.

---

## 4. The LLM's role, specifically

Four discrete jobs:

### 4a. Category segmentation (offline, weekly)

Classify every active Kalshi contract into a category (weather/temperature, weather/precipitation, politics/US, politics/international, economics/inflation, economics/employment, crypto/price, sports/NFL, etc.). This determines which calibration bin to use.

Input: contract description text.
Output: category label.
Difficulty: easy (contract descriptions are structured).

### 4b. Correlation assessment (inline, per-new-position)

When a new contract is a candidate for the portfolio, assess its correlation with every existing position.

Input: two contract descriptions + metadata (same event? same date? same geography? same underlying?).
Output: independent / weakly correlated / strongly correlated.
Difficulty: moderate (requires understanding causal relationships between events).

### 4c. Regime change detection (offline, weekly)

Assess whether current conditions differ from the historical calibration period in ways that might shift the curve.

Input: recent Kalshi resolution data (last 30 days) + current news summary.
Output: "Calibration for category X may have shifted because [reason]. Recommend adjusting bin Y by Z pp." OR "No regime change detected."
Difficulty: moderate-hard (requires judgment about structural market changes).

### 4d. Individual contract probability estimation (inline, per-contract)

For high-edge candidates (edge > 5pp per the calibration curve), the LLM provides a second-opinion probability estimate using available information (news, data, model outputs). If the LLM agrees with the calibration curve that the market is mispriced, increase conviction. If the LLM disagrees, reduce or skip.

Input: contract description + recent relevant news + calibration-curve edge.
Output: LLM's probability estimate + one-sentence rationale.
Difficulty: varies by category (weather = easy with model data; politics = hard).

---

## 5. What makes this genuinely novel

### 5a. Universal calibration across ALL contract types

Individual Kalshi traders calibrate within their domain. Weather traders know weather. Crypto traders know crypto. Nobody has built a master surface across all categories and traded the portfolio-level expected value. The cross-category diversification is the edge multiplier that makes small per-trade edges compound into meaningful returns.

### 5b. LLM-assessed correlation structure

Insurance companies use actuarial tables for correlation (geographic proximity, demographic overlap). There is no actuarial table for prediction market correlation. The LLM fills this gap by reasoning about causal relationships between events in natural language. "Is the probability that it snows in NYC tomorrow correlated with the probability that CPI comes in hot?" The LLM says no. "Is the probability of snow in NYC correlated with snow in Newark?" The LLM says yes. No statistical table encodes this; the LLM does.

### 5c. Fractional Kelly on binary outcomes with measured edge

Kelly criterion was designed for binary outcomes with known edge (Kelly 1956, originally for telephone line capacity). Prediction market contracts are literally binary outcomes. The calibration curve measures the edge empirically. This is the cleanest possible application of Kelly — cleaner than in equity markets where outcomes are continuous and edge is estimated.

### 5d. The "insurance provider of last resort" positioning

On Kalshi, retail participants are natural buyers of tail protection (longshots). Nobody systematically provides the other side. In insurance, this role earns the risk premium. On Kalshi, this role earns the favorite-longshot premium. The strategy positions us as the systematic counterparty to behavioral bias.

---

## 6. Cross-domain precedents

| Discipline | Framework borrowed | How it applies |
|---|---|---|
| **Actuarial science** | Calibration curves, loss ratios, policy pooling | Master calibration across Kalshi's universe; portfolio-level convergence |
| **Sports betting** | Calibration scoring, closing line value | Build calibration at each price level; measure whether our "closing line" (empirical rate) beats the market |
| **Reinsurance** | Correlation assessment for catastrophe risk | LLM assesses correlation between contracts, replacing the catastrophe models that reinsurers use |
| **Information theory** | Shannon entropy for uncertainty pricing | High-entropy contracts (near 50/50) have maximum premium for resolution; systematic sellers earn theta |
| **Commodity trading** | Convenience yield, contango/backwardation | The "convenience yield" of holding a Kalshi position is the information value of resolution; it decays as resolution approaches |
| **Market microstructure** | Kyle (1985) informed vs uninformed flow | Classify whether recent order flow is informed (news) or uninformed (retail). Trade against uninformed flow where calibration says the price is wrong. |

---

## 7. Risks and failure modes

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| **Calibration curve is flat** (market is well-calibrated) | Medium | Fatal | Kill criterion: if ±2pp across all bins, no edge. Find out in week 1 |
| **Calibration shifts after we deploy** (market matures, becomes more efficient) | Medium | High | Rolling re-calibration (quarterly). Monitor P&L deviation vs expected |
| **Correlation misclassification** — LLM says "independent" but events are correlated | Medium | High | Conservative correlation discounting (treat "weakly" as "strongly"). Stress-test with worst-case correlation assumptions |
| **Kalshi fee structure changes** | Low | Medium | Monitor. Current: zero maker fees, 0.07 × P × (1−P) taker fees. Strategy works at current fees |
| **Liquidity constraints** — can't get sufficient size | Medium | Medium | Per-position cap at 1% NAV. Kalshi max position varies by market. Accept lower AUM deployment |
| **Adverse selection** — we're the dumb money | Low | High | The calibration curve IS our edge; if we're trading against informed flow, the curve should reveal it (actual > implied for our sells). Monitor continuously |
| **Regulatory change on Kalshi** | Low | High | Can't mitigate. Pause if CFTC rules change |

The single biggest risk is that the calibration curve is flat. We find out in week 1. If it is, we move to Family #10 or #12 with no sunk cost.

---

## 8. Validation plan

### Phase 1: Calibration curve construction (week 1)

1. Pull all resolved Kalshi markets from kalshi-data-collector (420K+ markets).
2. For each market, extract the PIT price at 50% of duration (methodology from kalshi-autoagent's `precompute_pit.py`).
3. Bin by implied probability (5% bins: 0-5%, 5-10%, ..., 95-100%).
4. Compute actual resolution rate per bin with Wilson confidence intervals.
5. Repeat, segmented by top-level category.
6. Report the curve with error bars. Decide go/no-go.

**Go criterion:** at least 3 bins with >3pp deviation from 45° and n > 100, after fees.

### Phase 2: Historical backtest (weeks 2-3)

Using the calibration curve from Phase 1:
1. Walk-forward: build curve on first 70% of history, test on last 30%.
2. For the test period, simulate the portfolio: for each active contract, compute edge, size via fractional Kelly, track P&L.
3. Use LLM-assessed correlation to compute portfolio-level risk (or use a conservative flat correlation assumption as a lower bound).
4. Report: Sharpe, max drawdown, realized hit rate vs calibration-predicted hit rate, number of trades, capital deployed.

**Go criterion:** Walk-forward Sharpe > 1.0, hit rate within 2pp of calibration prediction, no catastrophic drawdown period.

### Phase 3: Paper trading (weeks 4-8)

Live monitoring of Kalshi markets using the calibration curve + LLM classification. Paper-trade the portfolio:
- Track: actual P&L, hit rate, average edge per trade, correlation incidents, LLM classification accuracy.
- Hand-label 100 LLM correlation assessments to grade accuracy.
- Re-calibrate curve monthly.

**Go criterion:** Sharpe > 1.0, LLM correlation accuracy > 80%, no adverse selection signal (actual resolution rate matches calibration within ±2pp).

### Phase 4: Live, small (weeks 9-12)

Deploy with 5% of intended NAV. $5 max per position. Weekly P&L review.

---

## 9. Transaction cost analysis

Kalshi fee structure (as of 2026):
- **Maker:** zero fees (resting limit orders)
- **Taker:** 0.07 × P × (1 − P) per contract per side

For a contract at P = 0.20 (our "No" position at $0.80):
- Taker fee per side: 0.07 × 0.20 × 0.80 = $0.0112
- Round-trip: $0.0224
- On a $0.80 position, that's 2.8%

For a contract at P = 0.50:
- Taker fee per side: 0.07 × 0.50 × 0.50 = $0.0175
- Round-trip: $0.035
- On a $0.50 position, that's 7.0%

**Implication:** The edge must exceed taker round-trip costs. For longshot positions (P = 0.05–0.20), costs are low (1-3%) and the calibration bias is largest (Favorite-Longshot Bias). For mid-range positions (P = 0.40–0.60), costs are highest (6-7%) and the calibration bias is smallest. The strategy naturally concentrates in the wings, which is where the literature says the edge is fattest.

**Optimization:** Use maker orders (limit resting) where possible. Zero fees. The strategy is not latency-sensitive — resting orders at calibration-implied fair value is natural.

---

## 10. How this builds on kalshi-autoagent

kalshi-autoagent's five strategies all exploit **mathematical identity violations** — prices that must satisfy a constraint by definition (sum to 1.0, monotonicity, threshold-bucket identity). These are risk-free in principle: if the math holds, the trade pays off with certainty.

This strategy exploits **statistical violations** — prices that should be calibrated to historical resolution rates but aren't. These are not risk-free per trade (any individual binary contract can go either way). The edge is at portfolio level, via the law of large numbers.

The two signal types are independent. A contract can be:
- Mathematically mispriced (autoagent trades it) AND statistically mispriced (we trade it): both strategies profit.
- Only mathematically mispriced: autoagent trades it.
- Only statistically mispriced: we trade it.
- Neither: nobody trades it.

The strategies share the same data pipeline, execution infrastructure, and risk management framework. They just listen for different signals.

---

## 11. Open questions

1. **Access to kalshi-data-collector.** The calibration curve requires historical resolution data. kalshi-autoagent uses a local SQLite database with 420K+ markets and 16M+ trades. Can prospector access this, or do we need to build our own historical data pipeline? (Likely: just point at the same database.)

2. **Category taxonomy.** Kalshi's internal categories may not align with the calibration-optimal segmentation. We may need to build our own taxonomy. The LLM can propose one; we validate by checking whether segmented curves are more predictive than the aggregate curve.

3. **Frequency of re-calibration.** The curve is built on historical data; how quickly does it decay? Monthly re-calibration is a reasonable starting assumption; empirical decay rate will be observed during paper trading.

4. **Integration with kalshi-autoagent vs standalone.** This strategy could be a new module within kalshi-autoagent (sharing the two-loop architecture) or a standalone prospector strategy. Architecturally, the former is cleaner because the execution infrastructure already exists. But the user may prefer to keep prospector as a separate system.

5. **Position sizing and capital allocation.** How much total NAV to deploy across the underwriting portfolio? Initial suggestion: start small ($500), scale to $5K after Phase 3, based on realized Sharpe.

---

## 12. Empirical results (2026-04-16)

### Data source

TrevorJS/kalshi-trades HuggingFace dataset: 154M trades, 17.5M markets, June 2021 – January 2026. CC-BY-4.0. Internal consistency validated: 99.71% exact trade/market volume match, zero duplicate trade IDs, perfectly monotonic last-price calibration. Direct API cross-validation limited (Kalshi purges old settled markets) but known outcomes confirmed (elections, NFL, NYC mayor).

### Phase 1: Calibration curve (completed)

**Method:** PIT pricing at 50% of market duration via ASOF join on 140M trades. 453K resolved markets survived the ≤25% time-offset filter. 5% implied-probability bins, Wilson confidence intervals.

**Aggregate result — GO (6 qualifying bins):**

The market systematically overprices events. Actual resolution rates fall 3–4pp below implied prices across the 25–70% range. Fee-adjusted edges (maker pricing) are 0.1–0.5pp. However, the aggregate signal is heavily composition-driven — sports dominate.

**Per-category breakdown:**

| Category | n | Signal bins | Key finding |
|---|---|---|---|
| Sports | 205K | 16/20 | Dominated by parlay overpricing (multi-leg bets). Deviations reach 8–15pp at mid-to-high implied. Structural, driven by prospect theory. Only ~6 months of history. |
| Crypto | 117K | 5/20 | Longshot overpricing (10–30% implied, 3–4.5pp deviation). Classic favorite-longshot bias. Most consistent with original thesis. |
| Other | 91K | 12/20 | Broad overpricing, similar pattern to sports. Needs decomposition. |
| Financial | 28.5K | 2/20 | Mostly well-calibrated. Edge only at 35–40% and 95–100%. |
| Weather | 9.6K | 4/20 | Noisy but promising. Small samples at tails. |
| Economics | 1.3K | 1/20 | Too small for conclusions. |
| Politics | 385 | 0/20 | Insufficient sample. |

**Sensitivity tests passed:**
- Filter relaxation: signal persists at 10%, 15%, 25%, 35%, 50% offset thresholds
- Temporal stability: bias present from 2024 H2 onward; early years (2021–2024 H1) too sparse for signal

**Key revision to thesis:** The bias is NOT the classic favorite-longshot pattern predicted by literature. It's dominated by (1) sports parlay overpricing and (2) crypto longshot overpricing. Financial/weather markets are near-efficient.

### Phase 2: Walk-forward backtest (completed)

**Method:** Train on first 70% of markets (pre-Jan 2026), test on last 30% (~136K markets). Fractional Kelly (25%), flat sizing on initial NAV ($10K), 1% max position, 2pp minimum edge, maker pricing (zero fees).

**Results:**

| Metric | Value |
|---|---|
| Total trades | 83,578 |
| Win rate | 66.9% |
| Total P&L | $1,590,561 |
| Sharpe | 7.44 |
| Max drawdown | 0.0% (see caveats) |

| Category | Trades | P&L | Win rate |
|---|---|---|---|
| Sports | 58,601 | $815,887 | 66.2% |
| Other | 14,364 | $616,553 | 63.8% |
| Financial | 995 | $131,019 | 28.2% |
| Crypto | 9,550 | $27,319 | 79.5% |

**Calibration accuracy:** Train-period curves predict test-period resolution rates within 0.3–2.0pp for most bins (15–65% implied). Degradation at tails (85–100%: 5–8pp gap).

**Caveats:**
1. Test period is ~1 month (Jan 2026) — very short for regime robustness
2. 83K trades/month requires ~2,800/day — execution-unrealistic without full automation
3. No concurrent-exposure or correlation modeling — same-day sports parlays are correlated
4. 0% drawdown is an artifact of daily aggregation across many trades
5. Capital requirement with concurrent positions far exceeds $10K initial NAV

### Next steps

1. **Phase 3: Paper trading** — live monitoring with the calibration curve + LLM classification. Start with crypto + weather (most defensible, ties to existing infrastructure). Add sports at lower sizing.
2. **Correlation model** — LLM-assessed pairwise correlation before adding positions. Critical for sports parlays.
3. **Execution infrastructure** — adapt kalshi-arb-trader's execution agent for resting maker orders.
4. **Rolling recalibration** — monthly curve refresh with circuit breaker if realized P&L deviates >2σ from expected.
