# Literature Survey

> Academic papers, industry research, and open-source implementations
> relevant to structural arbitrage in non-securitized markets. The
> reading list this project has consulted; updated when material new
> research surfaces.

This is a reading-list reference, not a strategy queue. Strategies that
emerged from this survey live in [`../rd/candidates/`](../rd/candidates/).

This file is the primary anchor for [axiom 8 — *know what's already been
done*](../charter/axioms.md#8-know-whats-already-been-done). Every new
candidate's **Ideation → Prior art / existing applications** subsection
should cross-reference an entry here (or to
[`sibling-projects.md`](sibling-projects.md), or to a documented
external development). When a real search turns up new prior art that
isn't catalogued below, add a row.

---

## 1. Funding Rate Arbitrage (crypto perpetual futures)

### Spot-Perp Basis (Cash-and-Carry)

Long spot + short perp; collect funding. Delta-neutral by construction.
BTC/ETH funding averaged 7.8-12.6% annualized over 3 years including the
2022 bear. Basis reached 15-80% annualized during bull markets, ~25% in
Feb 2024, >20% in Nov 2024. Ethena (USDe) implements this at protocol
scale.

- Wharton: [Perpetual Futures Pricing](https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf)
- ScienceDirect: [Risk and Return of Funding Rate Arb on CEX/DEX](https://www.sciencedirect.com/science/article/pii/S2096720925000818)
- Paradigm: [Shape of Opportunity — Crypto Term Structure](https://www.paradigm.co/blog/the-shape-of-opportunity-futures-term-structure-in-crypto-vs-tradfi-and-impact-on-volatility)

### Cross-Exchange Perp-Perp Arb

Different exchanges calculate funding differently (premium index, impact
pricing, caps, intervals). Hyperliquid: hourly, 4% cap. Binance: 8h,
variable cap. Mechanical differences create persistent funding spreads
on the same asset.

- Bocconi: [Perpetual Complexity — Arbitrage Mechanics](https://bsic.it/perpetual-complexity-an-introduction-to-perpetual-future-arbitrage-mechanics-part-1/)
- MDPI: [Two-Tiered Structure of Funding Rate Markets](https://www.mdpi.com/2227-7390/14/2/346) — 35.7M observations across 26 exchanges; 17% show economically significant arb spreads but only 40% profitable after costs

**Implication for us:** funding arb is well-characterized. Alpha is in
execution and regime-timing, not discovery. `crypto-copy-bot` covers
the spot-futures axis on Kraken; cross-exchange perp-perp is a different
trade not currently running.

---

## 2. Prediction Market Arbitrage

### Intra-Market No-Arbitrage Violations

When Yes + No prices sum to less than $1.00, buying both guarantees
profit. **$40M+ extracted from Polymarket alone between Apr 2024-Apr 2025**
(86M bets). Mispricings fleeting (~2-7 seconds).

- arxiv: [Unravelling the Probabilistic Forest — Arbitrage in Prediction Markets](https://arxiv.org/abs/2508.03474)
- UCD: [Economics of the Kalshi Prediction Market](https://www.ucd.ie/economics/t4media/WP2025_19.pdf)

### Combinatorial / Cross-Market Consistency

Logically dependent markets priced inconsistently. P(X wins by >5%)
must be ≤ P(X wins). **Cross-platform: Polymarket vs Kalshi diverge by
>5% roughly 15-20% of the time.** Systematic cross-platform arb yields
10-20% annually.

- AhaSignals: [Prediction Market Arbitrage Strategies](https://ahasignals.com/research/prediction-market-arbitrage-strategies/)
- Dev.to: [Polymarket × Kalshi Arbitrage](https://dev.to/benjamin_martin_749c1d57f/polymarket-x-kalshi-arbitrage-27di)

### Market Making (Spread + Time Decay)

Binary contracts have theta decay accelerating into settlement. Zero
maker fees on Kalshi. 40%+ of profit in final 14 days. Reduce exposure
~65% in final week (terminal gamma).

- HangukQuant: [Digital Option Market Making](https://www.research.hangukquant.com/p/digital-option-market-making-on-prediction)
- Substack: [Mathematical Execution Behind Prediction Market Alpha](https://navnoorbawa.substack.com/p/the-mathematical-execution-behind)

### Favorite-Longshot Bias

Decades of academic evidence: bettors overvalue longshots
($0.05-0.10 contracts) and undervalue favorites ($0.85-0.95). Driven by
prospect theory.

- JPE: [Explaining the Favorite-Long Shot Bias](https://www.journals.uchicago.edu/doi/abs/10.1086/655844)
- Management Science: [The Longshot Bias Is a Context Effect](https://pubsonline.informs.org/doi/10.1287/mnsc.2023.4684)
- QuantPedia: [Systematic Edges in Prediction Markets](https://quantpedia.com/systematic-edges-in-prediction-markets/)

### Cross-Market: Prediction Markets vs. Derivatives

Vertical spread price / strike distance ≈ probability of asset expiring
above midpoint. Compare to prediction market price. Divergences persist
because different participant pools.

- Moontower Meta: [Prediction Market Arb Using Option Chains](https://moontowermeta.com/prediction-market-arbitrage-using-option-chains-to-find-mispriced-bets/)

**Implication for us:** Kalshi intra-market arb is proven (sibling
`kalshi-autoagent` already does it). Open frontier is cross-market:
Kalshi ↔ Polymarket (and now ↔ HIP-4) — see candidate
[`07-three-venue-pm-divergence`](../rd/candidates/07-three-venue-pm-divergence.md).

---

## 3. Crypto-Specific Structural Strategies

### Liquid Staking Token (LST) Basis

stETH/rETH/cbETH vs ETH. Known redemption mechanism → floor on basis.
Widens on: queue length, protocol risk, liquidity crunches. Mean-
reverting. Delta-neutral via perp hedge.

- Journal of Futures Markets: [Economics of Liquid Staking Derivatives — Basis Determinants](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22556) (Scharnowski 2024-2025)
- arxiv: [Market Dynamics of Liquid Staking Derivatives](https://arxiv.org/html/2402.17748v3)

### Stablecoin Depeg

USDT has only 6 active arbitrageurs (largest does 66% of volume). Median
discount 54bp. USDC has 521 arbitrageurs, median discount 1bp. USDT's
concentrated structure creates larger, more persistent mispricings.

- NBER: [Stablecoin Runs and Centralization of Arbitrage](https://www.nber.org/system/files/working_papers/w33882/w33882.pdf)
- BIS: [Public Information and Stablecoin Runs](https://www.bis.org/publ/work1164.pdf)

### MEV / DEX Arbitrage

90M+ successful arb transactions on Solana alone, $142.8M profits over
one year. Requires sub-second, block-level infrastructure (Flashbots,
Jito bundles, private mempools). Infrastructure arms race.

- arxiv: [Remeasuring MEV Arbitrage](https://arxiv.org/abs/2405.17944)
- ACM: [Cross-Chain Arbitrage — Next Frontier of MEV](https://arxiv.org/abs/2501.17335) — $868M in cross-chain arbs over one year

### DeFi Liquidation Arbitrage

Flash-loan-funded liquidations are risk-free (atomic; reverts if
unprofitable). 5-15% liquidation bonuses. Spiky: low in calm markets,
explosive during crashes.

- ACM IMC: [Empirical Study of DeFi Liquidations](https://arxiv.org/abs/2106.06389)

### DeFi Lending Rate Arbitrage

Borrow-lend spread across protocols. Limited by: double-capital
requirement, gas costs, rate convergence dynamics.

- Berkeley: [DeFi Protocols for Loanable Funds](https://berkeley-defi.github.io/assets/material/DeFi%20Protocols%20for%20Loanable%20Funds.pdf)
- arxiv: [Yield Curves in a Bondless Market](https://arxiv.org/html/2509.03964v1)

**Implication for us:** MEV is an arms race (skip — see
[`charter/operational-limits.md`](../charter/operational-limits.md)).
Liquidation arb is spiky (not systematic). LST basis and stablecoin
depeg are structural and LLM-classifiable but low-density. DeFi lending
rate arb is thin after costs.

---

## 4. Crypto Volatility Arbitrage

BTC implied vol exceeds realized ~70% of the time. Variance risk premium
(VRP) averages +15 points in contango. Strategies: short straddles with
2.5% delta thresholds, risk-reversal premium harvesting, calendar spreads.

- Deribit Insights: [Bitcoin Options — Four Years of Volatility Regimes](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)
- ScienceDirect: [Arbitrage Opportunities in Crypto Derivatives](https://www.sciencedirect.com/science/article/pii/S138641812400048X)
- QFin: [Delta Hedging Bitcoin Options with a Smile](https://www.tandfonline.com/doi/full/10.1080/14697688.2023.2181205)

**Note:** Deribit handles >85% of crypto options volume. Not a security,
but may have US-person access restrictions.

**Implication for us:** Vol arb is well-documented with persistent
structural edge. Standalone Deribit access is an open question for the
US-resident operator (see [`charter/constraints.md`](../charter/constraints.md)).
The vol-surface candidate ([`03-kalshi-hyperliquid-vol-surface`](../rd/candidates/03-kalshi-hyperliquid-vol-surface.md))
explored a no-Deribit version using Kalshi binary contracts as the
implied surface; convergence thesis falsified, longshot wedge folded
into the [perp-hedging component](../components/hedging-overlay-perp.md).

---

## 5. Weather / Climate Contract Trading

GFS 31-member ensemble models produce probability distributions. Compare
to Kalshi prices. Models diverge from market when systematic biases
exist (wildfire haze under-forecasting), regime transitions (El Niño /
La Niña). Open-source bot documented $1.8K profits.

- GitHub: [Weather Bot using GFS Ensembles](https://github.com/suislanchez/polymarket-kalshi-weather-bot)
- Kalshi: [Weather Markets](https://help.kalshi.com/en/articles/13823837-weather-markets)

**Implication for us:** High LLM fit (synthesizing model outputs +
NWS Area Forecast Discussions per [`llm-altdata-extraction`](../components/llm-altdata-extraction.md)),
daily density, uncorrelated with crypto. Candidate
[`05-weather-ensemble`](../rd/candidates/05-weather-ensemble.md).

---

## 6. Weather Variance Risk Premium

Bae/Jacobs/Jeon (AEA 2025) — weather implied variance exceeds realized;
systematic sellers earn premium. Same shape as equity VRP but applied
to weather contracts.

- AEA 2025: [Weather Variance Risk Premia](https://www.aeaweb.org/conference/2025/program/paper/NGaKfE2n)

**Implication for us:** strengthens the case for the [Kalshi × CME
weather convergence candidate](../rd/candidates/09-kalshi-cme-weather-convergence.md)
(if the employer-policy question on commodity futures resolves favorably).

---

## 7. Traditional Finance → Crypto Mappings

| TradFi strategy | Crypto analogue | Key difference |
|---|---|---|
| Convertible arb | LST basis (stETH/ETH + perp hedge) | Redemption mechanism replaces conversion right |
| Merger arb | Token migration spread (known swap ratio) | Governance risk replaces regulatory risk |
| Stat arb (pairs) | Correlated-token pairs on perps | Regime changes are narrative-driven (LLM classifies) |
| Vol arb (implied vs realized) | Deribit straddles or Kalshi binary surface vs perp basis | Kalshi surface is discrete binary points, not continuous |
| Capital structure arb | Gov token vs staked token vs lending deposit | Protocol risk replaces credit risk |
| Box spread arb | Options-autoagent style constraint violations | 100× contract multiplier makes tiny violations tradeable |
| Pari-mutuel cross-track arb | Kalshi (home, sharp) vs Polymarket (away, retail) — Hausch-Ziemba 1980s | Three-venue extension when HIP-4 ships |
| Index dispersion | Kalshi championship vs game-leg parlays | Same correlation-premium concept; binary substrate |

---

## 8. Key Academic Sources (consolidated)

| Topic | Source | Key finding |
|---|---|---|
| Funding rate arb | Wharton (AHJ) | Perpetual futures pricing, funding mechanics |
| Cross-exchange funding | MDPI (35.7M obs) | 17% arb-significant spreads, 40% profitable post-cost |
| PM arbitrage | arxiv (2508.03474) | $40M+ extracted from Polymarket; combinatorial arb |
| PM vs options | Moontower Meta | Vertical spreads replicate binary contracts |
| PM market making | HangukQuant | Black-Scholes pricing for digital options on PMs |
| Longshot bias | JPE, Management Science | Systematic overpricing of low-probability events |
| LST basis | JFM (Scharnowski) | Basis determinants, mean-reversion, price discovery |
| Stablecoin depeg | NBER, BIS | Concentrated arb structure (6 players for USDT) |
| Crypto vol | Deribit Insights | VRP +15 points, 70% of time implied > realized |
| DeFi liquidations | ACM IMC | 5-15% bonus, flash-loan execution |
| MEV/DEX | arxiv (multiple) | $142.8M on Solana alone; arms race |
| Cross-chain | ACM (2501.17335) | $868M in arbs; inventory-based = 9s settlement |
| Weather VRP | Bae/Jacobs/Jeon AEA 2025 | Weather IV > realized; systematic sellers earn premium |
| MVT (foraging) | Charnov 1976 (Theoretical Population Biology) | Optimal patch-leaving when in-patch rate = habitat avg |
| Parimutuel cross-track | Hausch-Ziemba 1980s | Use sharp track to infer correct odds; trade soft tracks |
| Dispersion trading | Cboe DSPX index | Index IV vs. component IV gap |

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-15 | Initial literature survey | Inform strategy-family selection |
| 2026-04-25 | Doc moved from `rd/literature-review.md` to `reference/literature-survey.md` | Reorg: this is reference / reading list, not active R&D. Strategy candidates derived from this list now live in [`../rd/candidates/`](../rd/candidates/) |
| 2026-04-25 | Added Charnov MVT, Hausch-Ziemba parimutuel, Cboe dispersion, Bae weather VRP rows | Surfaced in fresh-eyes review; complete the cross-domain reading list |
| 2026-04-25 | Designated as primary anchor for axiom 8 (literature review) | New axiom added to charter; this file is what candidates' prior-art subsections should cross-reference |
