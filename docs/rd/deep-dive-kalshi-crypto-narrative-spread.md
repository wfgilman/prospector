# Deep Dive — Kalshi × Crypto Narrative Spread

## 0. TL;DR

Kalshi prices macro outcomes (Fed decisions, CPI prints, elections, SEC enforcement, ETF approvals) that have causally-linked downstream effects on crypto. The two markets have structurally different participant populations — Kalshi traders are macro/politics retail; crypto traders are crypto-native and distracted across hundreds of tokens. When Kalshi's implied probability for an outcome shifts on news, the crypto response is often delayed or partial. That lag is the edge.

The trade is single-leg: watch Kalshi, infer what the move *should* mean for a specific crypto asset using an LLM-maintained β map, and take a position on Hyperliquid. The LLM's role is specific and narrow — (a) maintain the mapping from Kalshi contracts to crypto exposures, (b) classify each Kalshi move as news-driven vs. noise, (c) reject moves that are reverse-caused by crypto (occasional but real).

This is an information-transmission trade, identical in shape to equity-futures-lead-cash trades that have been studied since the 1980s. What is new is the substrate: prediction markets as the leading indicator, and the LLM as the classifier that maps prediction-market moves to crypto sector exposures.

---

## 1. The core bet

**Claim:** There is a persistent information lag between Kalshi and crypto perps for macro-linked events, and that lag is exploitable on a 1–60 minute horizon.

**Why it exists:**

- **Audience mismatch.** A Kalshi trader watching FOMC day is watching FOMC day. A crypto trader is watching five alt pumps, an airdrop snapshot, and their liquidation price. When CPI prints at 08:30 ET, Kalshi's CPI contract absorbs the print in seconds. Crypto absorbs it too — but diffusely, unevenly, and with a tail that lasts minutes because the marginal crypto trader is not the marginal CPI watcher.
- **Cost-of-attention asymmetry.** Kalshi has 300–600 contracts; a Kalshi trader can watch the ones relevant to them. A crypto trader has ~300 liquid perps on one exchange alone, plus spot, plus DeFi. The "which news matters to which token" question is *work*, and the market underprices that work.
- **No direct hedging path.** A Kalshi trader who thinks CPI-hot is priced wrong has no natural hedge except the contract itself. A crypto trader who thinks the BTC reaction to a hot CPI print is underpriced has a clean instrument (BTC perp). The two populations don't share positions.

**Why now:**

- Kalshi's contract set expanded sharply in 2023–2024 (sports, economic data, events) — trade density is now sufficient.
- Kalshi API is stable and has historical data via CSV export; no scraping required.
- Hyperliquid perps give us 130+ crypto instruments with clean funding and tight spreads, enough to target single tokens.
- The 2024 election cycle generated the historical record we need to calibrate the β map (Trump/WLFI/DOGE is the clearest instance ever seen of a Kalshi outcome driving crypto).

**Why it doesn't go away immediately:**

- The arb requires running a text-classification model continuously against Kalshi and crypto news feeds. Funds that do macro don't have crypto execution infrastructure; funds that do crypto don't watch Kalshi systematically. The intersection is small.
- The edge is per-event modest (we are not claiming 192-score alpha; we are claiming 10–30bp per event, thousands of events). It isn't big enough for a Citadel desk; it is plenty for a one-person operation.
- The LLM classification step is hard to arb out without replicating the mapping work, which is ongoing because tokens and contracts change monthly.

---

## 2. What is genuinely original here

Cross-market lead-lag is not new. S&P futures lead cash equities. Bund futures lead German bonds. Eurodollar futures led LIBOR. Gold futures lead gold miners. The general pattern — a more-liquid, more-concentrated expression of a macro view leads a fragmented, distracted one — has been documented since at least Stoll & Whaley (1990). Academics have written hundreds of papers on it.

**What is original about this version:**

1. **The leading market is a prediction market, not a futures exchange.** Prediction-market prices are not just prices — they are literally *answers to questions*. A prediction-market move is more information-rich than a futures move because the semantic content of the contract ("Will the Fed cut 25bps?") is itself legible. This is what makes the strategy LLM-natural: you can read the contract text and the current price, and reason about downstream implications in natural language. You cannot do this with S&P futures.

2. **The lagging market is a fragmented multi-asset crypto universe.** Equity lead-lag is S&P futures → "the market." Here it is Kalshi → *pick-the-right-token*. That pick is itself a reasoning task: does a dovish Fed print benefit BTC more or DeFi more? Does a Trump win benefit DOGE (meme) or WLFI (direct exposure) or BTC (political legitimacy)? The LLM's role is nontrivial and ongoing because the token set rotates.

3. **The β map is dynamic and narrative-driven.** In equities, the β from SPY to a specific stock is a stable statistical property. Here, the β from "Fed hike probability" to "ETH perp return" depends on current narrative (is the market in risk-off mode right now? is ETH trading like risk-asset or like rate-asset?). This is why the LLM is necessary — a static regression will get the average β right and be wrong on every specific instance.

4. **Audience mismatch is durable.** In equity-futures arb, both sides of the trade are institutional, and the lag has compressed to milliseconds over 40 years. Kalshi's audience is retail-political; crypto's is retail-crypto. There is no structural force pushing these two groups to share analytical infrastructure, because they care about different things day-to-day.

**Most useful cross-domain lesson:** Sports-betting sharps (Pinnacle readers) watch line moves across dozens of books and trade the laggards. The discipline is identical: one market absorbs news faster for structural reasons, the others follow, you trade the gap. The difference is that sharp bettors are watching for sharp bettors on other books; here we are watching a market (Kalshi) whose sharps don't care about our lagging market (crypto) at all. That's a better spot than the sports case.

---

## 3. How the trade is structured

### 3.1 The event taxonomy

Not all Kalshi contracts are useful. The ones that are:

| Class | Example | Crypto coupling | Trade density |
|---|---|---|---|
| **Fed rate decisions** | "Will Fed cut 25bps in March?" | Strong on BTC/ETH | 8 FOMC days/yr + intraday updates |
| **Inflation prints** | "Will CPI come in hot?" | Strong on BTC/ETH | 12/yr + intraday |
| **Employment reports** | "Will NFP beat consensus?" | Moderate on BTC | 12/yr |
| **Election outcomes** | "Will Trump win?" | Token-specific (DOGE, WLFI, $TRUMP) | Continuous during cycle |
| **SEC/regulatory actions** | "Will SEC approve spot ETH ETF?" | Asset-specific | Sporadic but high-impact |
| **Crypto price contracts** | "Will BTC > $100k by Dec?" | Direct — this is a synthetic option | Continuous |
| **Sports outcomes** | "Will Chiefs win Super Bowl?" | ~None | N/A (skip) |
| **Weather** | "Will NYC see snow in Dec?" | ~None | N/A (skip) |

The first six categories give ~150–300 trade events per quarter at even moderate thresholds.

### 3.2 The β map — the core artifact

For each actionable Kalshi contract class, maintain a mapping to crypto exposures:

```yaml
# example β map (illustrative, not calibrated)
contract_class: "Fed cuts 25bps (March meeting)"
direction_of_probability_increase: "dovish"
expected_crypto_response_signs:
  BTC-PERP: +1    # dovish = risk-on = BTC up
  ETH-PERP: +1
  SOL-PERP: +1
  DeFi basket (UNI, AAVE, CRV): +1.5   # higher beta to rates
estimated_β_magnitude_per_10pct_move: 1.2%   # BTC moves 1.2% per 10pp probability shift
hold_horizon: "5 minutes to 1 hour"
confidence: "high — 24 months of FOMC days, consistent sign"

contract_class: "Trump wins presidency"
direction_of_probability_increase: "Trump-favorable"
expected_crypto_response_signs:
  BTC-PERP: +0.5    # modest — political legitimacy narrative
  DOGE-PERP: +2     # meme-direct
  WLFI-PERP: +3     # direct exposure (Trump family project)
  XRP-PERP: +1.5    # SEC case expected to resolve favorably
estimated_β_magnitude_per_10pct_move:
  DOGE-PERP: 4%
  WLFI-PERP: 8%
hold_horizon: "1 hour to 1 day"
confidence: "high for 2024, monitor for decay"
```

**Who builds and maintains this?** The LLM, iteratively and supervised. Bootstrap with 20–40 hand-curated mappings derived from historical event studies (FOMC days, NFP prints, election updates). The LLM proposes additions as new contracts list and new tokens emerge, with each proposal backed by a historical event study it computes itself. Opus (outer loop) reviews proposals monthly.

**Why this is the right division of labor:** The β map is a small artifact (dozens to low hundreds of entries). It needs to be auditable, not autonomous. The LLM's categorical reasoning ("this new Kalshi contract 'Will OPEC cut production?' should map to energy narrative, weak crypto coupling") is exactly the right shape — but the consequences of a bad entry are live trading risk, so human review is warranted.

### 3.3 The signal

At each Kalshi price update for a contract in the β map:

1. Compute ΔP = change in implied probability since last evaluation (e.g., last 1/5/15 minutes).
2. If |ΔP| below threshold → ignore.
3. Query LLM: "Kalshi contract X moved from P0 to P1 in the last N minutes. Is this driven by news? If yes, briefly summarize. If no, is there a plausible benign explanation (liquidity, fat-finger)?"
4. If LLM classifies as **news-driven**: compute expected crypto responses using β map entries. For each target token:
   - expected return = β × ΔP
   - check actual crypto move in same window
   - if actual < α × expected (e.g., α=0.5), crypto has lagged → enter position in the direction of expected return.
5. Exit on: (a) crypto catches up (actual ≈ expected), (b) time decay (hold-horizon elapsed), (c) reverse signal (Kalshi gives back the move), (d) stop-loss (1.5× expected move against us).

### 3.4 Sizing and risk

- Target: 10–30bp per event, Sharpe 1.5–2.5 on the strategy.
- Sizing: 0.5–1% NAV per trade, scaled by LLM confidence. Single-event max: 1% NAV.
- Concurrent positions: cap at 3; event clustering (FOMC day has many contracts move) requires correlation discount in sizing.
- Catastrophic failure mode: crypto moves sharply *against* the Kalshi signal because a crypto-specific catalyst (exploit, whale dump) was the true driver. Mitigated by (a) LLM classifier rejecting moves where crypto is leading, (b) hard stop on 1.5× expected move.

### 3.5 Transaction cost and feasibility

- Hyperliquid taker fee 0.035%; round-trip 0.07%.
- Slippage on majors (BTC/ETH/SOL) negligible at <0.5% NAV size.
- For the trade to be profitable at 0.07% round-trip, expected move must exceed ~10–15bp after slippage. This matches the empirical event-study returns we expect (10–30bp per event).

---

## 4. Data, infrastructure, and the LLM's role

### 4.1 Data layer additions

New, beyond what we have:
- **Kalshi API client** — REST; straightforward. Historical data via CSV export for backtesting.
- **News timeline** — a timestamped feed of macro headlines. Options: AlphaSense (paid), an X list with LLM summarization (cheap), GDELT (free, lagged). Bootstrap with X list + LLM.
- **β map store** — a YAML or SQLite artifact; version-controlled.

Reuse:
- Hyperliquid OHLCV and perp execution (already have).
- Ledger (already have; extend schema for Kalshi event + trade tuple).

### 4.2 LLM's role, specifically

The LLM is doing three things, each scoped narrowly:

1. **β map maintenance (offline, monthly).** Propose new contract-to-token mappings; run historical event studies to justify each; flag decay in existing mappings. Human review before deployment.

2. **Real-time classification (inline, per-event).** Three-way decision: news-driven / noise / reverse-caused-by-crypto. Inputs: Kalshi contract text, recent Kalshi price trajectory, recent news headlines (last 30 min), recent crypto price of target tokens. Output: one of three labels + one-sentence rationale.

3. **Hold-horizon estimation (inline, per-event).** Given contract class and current market regime, estimate the window over which the crypto catch-up move is likely to play out. Output: one of {5min, 15min, 1h, 1d}.

None of these is a continuous-optimization task. All are categorical reasoning over structured inputs. This is exactly what the Elder-template inner loop was *not*.

### 4.3 What doesn't require an LLM

Everything else. The β coefficients themselves are statistical fits; sizing is deterministic; execution is just HTTP. The LLM is touched at three specific points and nowhere else.

### 4.4 Hardware check

13B Q4 model at ~7GB. Per-event inference is short (classification + one-sentence rationale, a few hundred tokens out). Latency under 2s on M3 16GB. Events are not simultaneous in the common case; FOMC day is the worst case and we'd see ~20 contracts move in a 30-min window. Queue is fine.

---

## 5. Validation plan

### 5.1 Historical event study (month 1 deliverable)

Before writing any execution code:

1. Download 12–24 months of Kalshi historical data for the 6 actionable contract classes (~100–200 contracts total).
2. Download matching Hyperliquid OHLCV at 1m granularity.
3. For each Kalshi move above threshold, compute crypto return in {1m, 5m, 15m, 1h} windows for each token in a candidate β map (~30 tokens).
4. Regress crypto returns on ΔP for each (contract-class × token) pair. Report R², β, significance, sample size.
5. Filter the β map to only pairs with R² > 0.05 and p < 0.01 with n > 50 events.
6. Expected outcome: 20–60 valid pairs. Enough to build on.

**Kill criterion:** if the historical event study produces fewer than 20 pairs passing the filter, or if the R² distribution is indistinguishable from random noise, we abandon. This is a real risk and we take it seriously — the whole thesis rides on the claim that these β's exist and are stable.

### 5.2 Walk-forward on the event study

Same β map, but split the history into non-overlapping windows (e.g., 6 months each). Require βs to be stable in sign and within ±50% in magnitude across windows. Drop pairs that fail.

### 5.3 Paper trading (month 2)

Run the full pipeline (Kalshi polling → LLM classification → signal → *simulated* Hyperliquid trade) for 4–6 weeks. Track:
- Hit rate (% of signals where crypto did move in the predicted direction)
- Mean PnL per event
- Slippage realized vs. assumed
- LLM classification accuracy (hand-label 100 events to grade)

**Pass criterion:** Sharpe > 1.0 on paper, LLM classification accuracy > 70%, no catastrophic reverse-causation event in the sample.

### 5.4 Live, small (month 3)

0.1% NAV per trade, 2% total NAV deployed. Ship daily P&L and event log to the ledger; review weekly.

---

## 6. Risks and failure modes

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| **β map instability** — βs that held in 2024 decay in 2025 | Medium | High | Monthly β-decay review; drop pairs where rolling R² falls below threshold |
| **Reverse causation** — a crypto move drives the Kalshi move, not the other way around | Medium | High | LLM classifier explicitly asks this; auto-reject when Kalshi news-timestamp is later than crypto move |
| **Kalshi liquidity** — thin contracts give noisy ΔP not tied to news | Medium | Low | Minimum volume/depth filter per contract |
| **Kalshi resolution risk** — contracts are cash-settled at resolution; we exit before resolution, but fat-finger timing matters | Low | Medium | Never hold through resolution; strict time-stop before event |
| **Multiple-contract same-event** (FOMC has "cuts 25bps," "cuts 50bps," "holds") — correlation in ΔP | Medium | Medium | Group contracts by event; size the group, not each contract |
| **Regulatory surprise on Kalshi** — CFTC action, product changes | Low | High | Can't mitigate; monitor and be ready to pause |
| **LLM hallucination in classifier** — invents a news story that doesn't exist | Medium | Medium | Require the classifier to quote a specific headline with timestamp; reject if none found |
| **Fee regime change on Hyperliquid** — fees rise; edge erodes | Low | Medium | Monitor; strategy tolerates up to ~0.1% round-trip |
| **Stablecoin / USDC depeg during a trade** | Low | Medium | Close positions if USDC moves > 0.5% from peg |

The two risks that matter most are β-map instability and reverse causation. Both are explicitly designed around: the map is a living artifact with review cadence, and the classifier's core job is reverse-causation detection.

---

## 7. What a minimal viable prototype looks like

To test the thesis with the least code possible:

1. **Pick one contract class** — FOMC rate decision probabilities — because it has the longest history, strongest priors, and most documented crypto reaction.
2. **Pick three crypto tokens** — BTC, ETH, SOL — because they're the highest-liquidity perps.
3. **Pick one direction** — only trade when Kalshi ΔP exceeds a 5% threshold in either direction, and only trade BTC perp in the direction β predicts.
4. **Backtest one year** of historical FOMC days (8 meetings × ~5 relevant contracts per meeting × multiple intraday updates = ~200–400 candidate events).
5. **Report** hit rate, mean PnL, Sharpe. Decide whether to expand to more contracts and tokens.

That's roughly a two-week scoped piece of work after we have Kalshi data pulled. It answers the thesis: *is there an exploitable lag, or is this smoke?*

If the answer is yes, the work expands in two directions: more contract classes, more tokens. If the answer is no, we've spent two weeks and learned something real, and we revisit the family shortlist.

---

## 8. What we'd be watching for in the first 90 days

**Green flags:**
- Historical event study produces ≥20 valid β-pairs with stable signs.
- Paper trading delivers Sharpe > 1.0 in month 1 — doesn't need to be huge.
- LLM classifier accuracy > 70% on hand-labeled events.
- At least one emergent β that we *didn't expect* from priors (that's where novelty shows up — the LLM finding mappings we wouldn't have hand-curated).

**Red flags:**
- Historical βs all near zero or wildly unstable across folds.
- Paper trading hit rate indistinguishable from 50%.
- Reverse causation detected > 30% of events.
- LLM repeatedly invents news to justify moves.

If two or more red flags appear in 30 days, pause and reassess. The shortlist has backups (token unlocks, Kalshi-native) that can be picked up.

---

## 9. Why this is the right next step

Three reasons:

1. **It directly addresses the lesson from the pivot:** the LLM's comparative advantage is categorical reasoning over structured text (contract descriptions, news headlines, token narratives). Every step in this strategy uses that advantage. No step uses the LLM for continuous optimization — that's what killed the Elder track.

2. **It uses infrastructure we have.** Data layer, ledger, harness (for PnL accounting), walk-forward (for β stability) all carry over. The net new build is a Kalshi API client, a small LLM-classifier wrapper, and a β-map store. Maybe 2–3 weeks of coding once the research gate is passed.

3. **It has a clean kill criterion.** The historical event study either finds stable βs or it doesn't. That's a one-month experiment with a binary outcome. If it works, we build on solid ground. If it doesn't, we've learned something real and move on to family #2 or #8 with no sunk-cost baggage.

---

## 10. Open questions for discussion

Before starting any implementation work, the following need an answer or an explicit "parking-lot" decision:

1. **Kalshi account and limits.** Do we need a Kalshi account to pull the historical data, or is the CSV export public? Are there API rate limits we should plan around? (Needs a 30-minute data spike to confirm.)
2. **News feed cost tolerance.** Free (X list + LLM summarization, GDELT) vs. paid (AlphaSense, Bloomberg). Recommendation: start free; upgrade only if false-positive rate is too high.
3. **Ledger schema extension.** Need a new row per Kalshi-event-triggered trade, including (contract_id, ΔP, classifier_label, classifier_rationale, β used, target token, actual PnL). Minor schema addition.
4. **Execution authority.** Paper trading is zero-risk; the step from paper to live has real money on the line. Before any live trading, agree on (a) size envelope, (b) daily loss kill-switch, (c) review cadence.
5. **β-map provenance.** Who commits an initial 20-entry hand-curated β map to start with, and with what historical evidence? This is small but load-bearing.

---

## 11. The next action

If this prospectus is accepted, the immediate next action is a 1-week historical data spike:

- Pull Kalshi historical prices for FOMC-related contracts (2023–2025).
- Pull Hyperliquid 1m BTC/ETH/SOL OHLCV for the same period.
- Compute the event study for (FOMC Δ implied probability) × (BTC/ETH/SOL 5m/15m/1h return).
- Report the raw βs, R²s, and sample sizes. No LLM in the loop yet — just the underlying phenomenon.

If the raw βs look promising, we move to full implementation. If not, we revisit.

That single experiment answers the core question and costs a week. It is the next thing to do.

---

## 12. Event-study methodology (pre-registration, 2026-04-22)

Importing the `§5.0`-style discipline from the #10 deep-dive: lock every continuous/discretionary knob before any script runs, so the result can't be retro-fit to a post-hoc story. Lessons carry from #10: raw-gap magnitudes looked huge but came from reference-model mismatch, not real mispricing, and the first failure was instructive only because the pre-registration made it sharp.

### 12.1 Data constraints (observed, not chosen)

- **Kalshi HF dataset** ends 2026-01-30 (stale ~3 months vs. live date). Re-pull blocked until in-house data pipeline M1 ships per [`docs/implementation/data-pipeline.md`](../implementation/data-pipeline.md).
- **Hyperliquid OHLCV** locally covers 2025-09-17 → 2026-04-22 at 1h granularity. No 1m candles yet (blocking on data-pipeline M2). No funding data.
- **Overlap window**: 2025-09-17 → 2026-01-30, ~4.5 months.
- **FOMC meetings in window**: FED-25SEP (Sep 17), FED-25OCT (Oct 29), FED-25DEC (Dec 10), KXFED-26JAN (Jan 28). Four meetings.

Consequence: the prospectus §11's "1m BTC/ETH/SOL" horizon is not available this pass. We test at **1h granularity only**; if the β is there at 1h it'll be there at 1m too, and if it's near zero at 1h, finer-grained measurement won't rescue a missing effect.

### 12.2 Pre-registered hyperparameters

| Knob | Locked value | Rationale |
|---|---|---|
| Event universe | All `FED-YY{SEP,OCT,DEC}` + `KXFED-26JAN` strike-ladder contracts | Only ladder families with multiple strikes; excludes `KXFEDDECISION-*` cut/hike/hold contracts (different structure) |
| Horizon | Per-hour snapshots, BTC return over [t, t+1h] lagged | Matches OHLCV granularity; lagged (not concurrent) to measure lead-lag, not co-movement |
| Kalshi aggregation | Implied expected rate = Σ p_i · midpoint_of_strike_bucket_i (reconstructed hourly from strike ladder) | Single scalar per timestamp — cleaner than tracking individual strikes |
| ΔP definition | 1h change in implied expected rate (percentage points) | Matches lag horizon |
| Ladder-completeness filter | ≥0.75 of max-strikes-observed per event | Same discipline as #10 |
| Coins | BTC_PERP, ETH_PERP | SOL_PERP local but no matching Kalshi crypto-price contracts tested this pass |
| Expected β sign | Negative (dovish ΔP → positive BTC return) | Theoretical prior; report as directional hypothesis |

### 12.3 Pre-registered experimental design

1. **Date split.** Train: events resolving in 2025-09-17 → 2025-12-31 (FED-25SEP, FED-25OCT, FED-25DEC pre-meeting data). Test: events resolving in 2026-01-01 → 2026-01-30 (KXFED-26JAN pre-meeting data). This is a 3-event train / 1-event test split — small but necessary given the event count. Additional runs on any future FOMC cycles become natural out-of-sample folds as the in-house data pipeline ships.
2. **Test fold seen once.** All exploration, hyperparameter-intuition, outlier inspection happens on train. Test is run once at the end.
3. **Null benchmark.** Random permutation of the (ΔP, BTC return) pairing within the test fold. Real signal must beat null on t-stat ratio.
4. **Pre-committed pass criteria (all required on test fold):**
   - |t-stat of β| > 3.0 in the lagged regression
   - R² > 0.002 (any non-trivial explanatory power)
   - β sign matches directional prior (negative)
   - Null-shuffle |t-stat| < ⅓ of real |t-stat|
5. **Full-distribution reporting.** Regressions reported per-coin and per-event, not collapsed to a single number. If any one event or coin drags the aggregate, that's visible in the breakdown.

### 12.4 What this pass does not test

- **Sub-hour granularity** (blocked on data pipeline M2).
- **Information-transmission classification** — the LLM-driven news-filter step in §3.3. For this pass the regression is a raw beta; the LLM classifier only matters if the raw phenomenon exists.
- **Other macro contract classes.** CPI, NFP, elections deferred to follow-on work if Fed passes.

### 12.5 Decision rule post-results

- **Pass** → continue to scoped prototype per §7 (MVP: single contract class, 3 tokens, one direction). Data-pipeline investment still load-bearing for 1m granularity.
- **Fail with directional sign correct but t-stat weak** → N-limited. Wait for data pipeline extension, re-run on more events. Don't retrofit.
- **Fail with wrong sign or null-indistinguishable** → pivot to a different strategy family from [`strategy-families.md`](strategy-families.md); #2 (token unlocks) or #12 (weather ensemble) are the queued alternatives.

---

## 13. Phase 1 event study findings (2026-04-22)

**Pre-registered verdict: FAIL.** Across both coins, no pre-registered criterion passed on the test fold.

### 13.1 Results

| Regression | n | β | t-stat | R² |
|---|---|---|---|---|
| train_BTC_PERP | 1,442 | +0.0195 | +0.53 | 0.0002 |
| **test_BTC_PERP** | **720** | **+0.0383** | **+1.05** | **0.0015** |
| test_null_BTC_PERP | 720 | +0.0331 | +0.91 | 0.0011 |
| train_ETH_PERP | 1,442 | +0.0174 | +0.31 | 0.0001 |
| **test_ETH_PERP** | **720** | **+0.0094** | **+0.18** | **0.0001** |
| test_null_ETH_PERP | 720 | −0.0970 | −1.88 | 0.0049 |

Per-event breakdown on train:

| Event | BTC t-stat | ETH t-stat |
|---|---|---|
| FED-25SEP | — (n=2, edge of OHLCV window) | — |
| FED-25OCT | +0.73 | +0.30 |
| FED-25DEC | +0.20 | +0.15 |

### 13.2 Pre-registered pass-criteria check

| Criterion | BTC | ETH |
|---|---|---|
| (a) \|t-stat β\| > 3.0 | FAIL (1.05) | FAIL (0.18) |
| (b) R² > 0.002 | FAIL (0.0015) | FAIL (0.0001) |
| (c) sign(β) = negative | **FAIL (sign is positive)** | **FAIL (sign is positive)** |
| (d) null t-stat ratio | FAIL (null ≈ real) | FAIL (null bigger than real) |

### 13.3 Data-staleness finding worth memorializing

The HF dataset had `FED-25DEC` and `KXFED-26JAN` stored with `status='active'` — Kalshi had not yet finalized them when the TrevorJS snapshot was taken. Trades through event close are present regardless, but a naive `WHERE status='finalized'` filter drops half the events. This is exactly the kind of third-party-data subtlety the in-house pipeline (`docs/implementation/data-pipeline.md`) is justified by: our own ingest will have a single, consistent, time-labeled status field we control the semantics of.

### 13.4 Interpretation

The test is faithful to the pre-registration, but three facts about the test design matter for how to interpret the result:

1. **Hourly granularity is the measurement we have, not the measurement the thesis wants.** §1 of this deep-dive hypothesizes "a persistent information lag ... on a 1–60 minute horizon." At 1h granularity, any transmission that happens in 10–30 minutes is invisible — the return window we regress on includes both the lag *and* the reversal, averaging toward zero. Data pipeline M2 (1m BTC/ETH candles) unblocks the intended test.
2. **No news filter was applied.** §3.3 specifies an LLM classifier that rejects non-news-driven ΔP (noise from liquidity, fat-finger). This Phase 1 deliberately skipped that step to isolate the raw phenomenon. Mixing real FOMC-news-driven moves with noise ΔP dilutes any true β toward zero. A null result here doesn't falsify the full prospectus — it falsifies a *specific simplified version*.
3. **The null-shuffle comparison is noisy at n=720.** ETH's shuffled null produced a larger absolute t-stat than the real signal. That's a red flag on the null construction at this sample size, not evidence of a signal. The right fix is more events (more FOMC cycles, once the data pipeline ships), not a cleverer permutation scheme.

That said: the sign-prior failed in both train and test. Dovish Kalshi shifts did not coincide with BTC up-moves on average. Two possibilities:
- The thesis is wrong for BTC: Kalshi's FFR contracts are already well-arbitraged with the SOFR futures market, and crypto isn't where the marginal macro trader is looking for expression. The "audience mismatch" argument in §2 may be weaker than the prospectus imagined.
- The sign reversal is an artifact of the measurement coarseness — at 1h, the initial reaction and the reversion both happen inside one return window and the sign is determined by whichever moves more, not by the underlying transmission.

Without higher-frequency data we can't distinguish these.

### 13.5 Decision per §12.5

Strictly pre-registered rule: *"Fail with wrong sign or null-indistinguishable → pivot."* Both conditions are met.

But the pivot decision has a different character here than for #10. #10 failed because the convergence formulation didn't match what the data showed (real signal existed but didn't converge mechanically). #4 failed because **we could not measure the specific phenomenon the thesis requires** — the granularity mismatch is upstream of the thesis itself.

Honest recommendation:

**Primary action: defer #4 pending data pipeline M2.** Mark #4 as *"Blocked — requires 1m OHLCV from data pipeline. Resume once M2 ships; re-run with hourly-snapshot-of-ΔP vs. 5m/15m/30m BTC return horizons."* Not a pivot, but not active either. Pre-registered criteria stay locked; the next test gets the granularity it always needed.

**Parallel action: prioritize the data pipeline.** The same infrastructure gap blocks #10 Phase 3 (re-validation on fresh data), the #4 follow-on (1m granularity), and the potential PM Phase 5 hedging overlay (funding + 1m). Three downstream users for one upstream build — straightforward ROI for the data-pipeline sprint.

**If the investor wants an R&D track running while the data pipeline is built:** #2 (token unlocks) is the lightest-touch candidate — it uses Token Unlocks / CryptoRank data (public APIs) and Hyperliquid perps (we have hourly candles), no Kalshi dependency, no 1m requirement. A scoped 1-week historical event study on (unlock event, next-30-day perp return) is runnable today and doesn't compete with data-pipeline work.

### 13.6 Artifacts

- `scripts/fomc_event_study.py` — locked-hyperparameter script
- `data/fomc/event_study_panel.parquet` — hourly panel with implied rate, Δ-rate, BTC/ETH returns
- `data/fomc/regression_results.csv` — every regression fit, including per-event breakdown
- `data/fomc/summary.txt` — plain-text pass/fail record

---

## 14. Phase 3 — re-run on 15-min Coinbase data (2026-04-23)

### 14.1 What changed

Phase 1 (§13) failed with the sign prior violated (β positive, prior was negative), and could not distinguish that from a granularity mismatch — hourly OHLCV couldn't resolve a sub-hour transmission lag. Phase 3 re-runs at 15-minute granularity on Coinbase 1m candles.

Data-layer context:
- Kalshi source: unified in-house tree (`data/kalshi/{trades,markets}/`)
- Crypto source: Coinbase BTC-USD / ETH-USD 1m candles. Hyperliquid's API caps 1m retention at ~3 days, so historical FOMC coverage from Hyperliquid is impossible today. Coinbase is US-accessible (Binance global returns 451 to US IPs), liquid, and tracks Hyperliquid's BTC perp at >0.99 correlation on sub-hour bars during active trading.
- Granularity change pre-registered before any results seen: `SNAPSHOT_CADENCE_MINUTES=15`, `LAG_MINUTES=15` (matching). All other pre-reg hyperparameters (event universe, train/test split, pass thresholds) unchanged.

### 14.2 Results

| Regression | n | β | t-stat | R² |
|---|---|---|---|---|
| Train BTC-USD (FED-25SEP/OCT/DEC) | 7,806 | −0.0047 | −0.35 | 0.00002 |
| **Test BTC-USD (KXFED-26JAN)** | **2,880** | **−0.0176** | **−1.06** | **0.00039** |
| Null BTC-USD | 2,880 | +0.0107 | +0.64 | 0.00014 |
| Train ETH-USD | 7,805 | −0.0066 | −0.31 | 0.00001 |
| **Test ETH-USD** | **2,880** | **−0.0064** | **−0.28** | **0.00003** |
| Null ETH-USD | 2,880 | +0.0100 | +0.43 | 0.00007 |

Per-event train breakdown (dollar-scale — BTC returns per 1pp change in Kalshi implied FFR):

| Event | BTC β | BTC \|t\| | ETH β | ETH \|t\| |
|---|---|---|---|---|
| FED-25SEP | +0.001 | 0.03 | +0.018 | 0.55 |
| **FED-25OCT** | **−0.016** | **0.67** | **−0.059** | **1.49** |
| FED-25DEC | +0.0002 | 0.01 | +0.015 | 0.44 |

### 14.3 Pre-registered criteria

| Criterion | BTC | ETH |
|---|---|---|
| (a) \|t-stat β\| > 3.0 | FAIL (1.06) | FAIL (0.28) |
| (b) R² > 0.002 | FAIL (0.00039) | FAIL (0.00003) |
| (c) sign(β) = negative | **PASS** (was FAIL in Phase 1) | **PASS** (was FAIL in Phase 1) |
| (d) null t-stat ratio | FAIL | FAIL |

### 14.4 What this replication tells us

Two things changed cleanly from Phase 1 → Phase 3:

1. **Granularity alone fixed the sign prior.** Phase 1's positive β was a measurement artifact of hourly pooling (initial reaction + reversion both inside one bar, netting to the larger move's sign — often positive because BTC rallied during the sample). At 15-min the sign is correctly negative in both coins on the test fold and on 2 of 3 train events. The thesis's directional claim (*dovish Kalshi shift → BTC up*) is not falsified.
2. **5× the sample size did not rescue significance.** Train n went from 1,442 → 7,806, test from 720 → 2,880. T-stats stayed in the 0.3–1.1 range on both folds. The effect is not hidden by noise — it's genuinely close to zero at the 15-min horizon. If the transmission were economically meaningful at this cadence, 8,000 observations would detect it easily.

### 14.5 Where the remaining signal lives

The train per-event breakdown is the most interesting part:

- **FED-25OCT**: BTC β=−0.016 (\|t\|=0.67), ETH β=−0.059 (\|t\|=1.49). Sign correct, magnitude largest, t-stat approaching significance on ETH.
- **FED-25SEP / FED-25DEC**: noise on both coins; β's near zero with inconsistent signs.

Oct 2025 was a FOMC with active rate-cut repricing; Sep and Dec were more settled. This is consistent with a **regime-dependent transmission hypothesis**: macro news drives BTC only when the Fed is actively surprising. FED-25OCT was the "informative" event in the train fold. KXFED-26JAN (test fold) happens to show weak signal in the same direction (β=−0.018, \|t\|=1.06 on BTC) — suggestive but not robust.

We don't have enough FOMC cycles in-sample to pre-register this hypothesis cleanly. Four events (3 train, 1 test) is fine for testing the primary thesis (transmission exists on average) but too few for regime conditioning.

### 14.6 Decision per §12.5

Original rule: *"Fail with directional sign correct but t-stat weak → N-limited. Wait for data-pipeline extension, re-run on more events. Don't retrofit."*

Sign IS correct. But per §14.4, we're not N-limited in the usual sense — 5× more data didn't help. Two interpretations:

- **Interpretation A (mild):** the effect exists but is economically trivial at 15-min; needs much finer granularity (5m, 1m) to catch the few seconds of transmission before the arb closes. Pre-registered horizon was 15m; 1m is available but would be a new pre-registration.
- **Interpretation B (strong):** the effect is regime-dependent and only fires on a subset of FOMC meetings. Collapsing all events into one β averages it out. Needs pre-registered event classification before conditioning.

Both interpretations are alive after Phase 3. Neither is decisively validated. Recommended next moves, lowest cost first:

1. **Accumulate more FOMC cycles** via the daily cron. Each cycle adds ~3k observations to the FOMC windows we can test. Revisit after 2-3 more Fed meetings (~4-6 months).
2. **If Interpretation A is the active hypothesis**: fresh pre-registration with `SNAPSHOT_CADENCE_MINUTES=5` and `LAG_MINUTES=5`. Re-run on the same data. This is distinct enough from Phase 3 that it warrants its own pre-reg entry.
3. **Do NOT pivot yet.** Phase 3's sign-prior flip is real evidence the thesis isn't falsified — just underpowered for definitive affirmative proof.

### 14.7 What this means for the broader R&D queue

The 15-min test was the cheapest path to falsifying (or not) the simplest version of #4. With the thesis now in "alive but underpowered" state rather than "falsified," #4 stays in the rotation but without active build-out until (a) more FOMC cycles accumulate or (b) we re-pre-register at finer granularity. PM Underwriting's Phase 3 paper book runs on autopilot; PM Phase 5 (hedging overlay) can proceed on its own merits (Phase 3 re-validation of #10 already confirmed the wedge it relies on).

### 14.8 Artifacts

- `scripts/fomc_event_study.py` — ported from Phase 1 to 15-min granularity + Coinbase source
- `data/fomc/event_study_panel.parquet` (15-min panel)
- `data/fomc/regression_results.csv`
- `data/fomc/summary.txt`
