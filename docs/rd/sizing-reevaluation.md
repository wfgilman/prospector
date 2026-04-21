# Sizing-Framework Reevaluation

**Status:** In progress (2026-04-21).
**Predecessors:** Phase 2b capital-constrained sim, Phase 3 paper trading (live since 2026-04-20).
**Related code:** `scripts/return_distribution.py`, `src/prospector/underwriting/portfolio.py`.

---

## 1. Why we're reevaluating

The Phase 3 paper book is running Kelly-per-bet sizing with a stack of safety caps: quarter-Kelly, `max_position_frac=0.01`, `max_event_frac=0.05`, `max_category_frac=0.20`, plus count-based guardrails on event/subseries/series. Each of these was added for a good reason, but the ensemble has a structural mismatch with the strategy's actual payoff profile.

The tension surfaced mid-Phase-3 while tuning the live caps:

- **Insurance-underwriting framing is misleading.** The deep-dive prospectus sold the strategy as "write many small policies, collect premiums." The capital-constrained sim (and the live book) ranks candidates by edge and systematically fills the extreme-price bins (80-95¢ implied), which are **9:1 lottery tickets** — small-frequent-losses + rare-big-wins. That's the opposite payoff shape of the insurance label. See `docs/implementation/methodology.md` §4.7.
- **Kelly assumes known edge.** We don't know our edge — we *forecast* it from a calibration curve with non-trivial sampling noise (±2-8pp depending on the bin). Full Kelly over-sizes when edge is overestimated; quarter-Kelly is a crude response that scales every bet down by the same factor regardless of the forecast's credibility.
- **The caps chase a count, not a confidence target.** `max_category_frac=0.20` was chosen because 20% of NAV felt like a tolerable concentrated-drawdown ceiling. But the question the strategy actually needs to answer is: *how many independent bets, each how large, give us P(book positive) ≥ 90% over the horizon?* That's a portfolio-level statement, and nothing in the current framework directly targets it.

The practical consequence: with ~36 open positions on a 29% win-rate, 9:1 payoff profile, we are in a regime where streaks of 15+ losses are the *modal* experience — not because anything is broken, but because the LLN hasn't had a chance to work.

## 2. The empirical distribution

We ran `scripts/return_distribution.py` on the walk-forward test set (January 2026, 81,556 tradeable trades). Per-trade return is expressed as `pnl / risk_budget`, so it's dimensionless and comparable across bins.

### 2.1 Aggregate

| Stratum | n | Win rate | μ (per $1 risk) | σ (per $1 risk) | Sharpe | N for P≥90% | N for P≥95% |
|---|---|---|---|---|---|---|---|
| **All trades** | 81,556 | 66.2% | +0.196 | 3.462 | **0.057** | 511 | 841 |
| **High-edge slice (edge ≥ 5pp)** | 6,523 | 39.4% | +0.205 | 1.863 | **0.110** | 136 | 223 |

*Confidence N formula:* `N ≥ (z_target / Sharpe)²`, with z₀.₉₀ = 1.28, z₀.₉₅ = 1.64. Assumes independent bets, Gaussian aggregate.

### 2.2 By price bin × side (top slices by Sharpe)

| Side | Bin | n | Win rate | avg payoff/$ | Sharpe | N@90% |
|---|---|---|---|---|---|---|
| sell_yes | 95-100¢ | 1,563 | 12.5% | 65.7 | **0.285** | 21 |
| sell_yes | 85-90¢ | 1,015 | 20.2% | 6.72 | **0.180** | 51 |
| sell_yes | 90-95¢ | 334 | 14.1% | 11.3 | **0.169** | 58 |
| buy_yes | 0-5¢ | 201 | 6.0% | 47.8 | **0.149** | 75 |
| sell_yes | 10-15¢ | 2,558 | 91.7% | 0.13 | 0.128 | 100 |
| sell_yes | 65-70¢ | 1,906 | 38.5% | 2.02 | 0.111 | 134 |

Three things worth noticing:
1. **Per-bet Sharpe varies ~5× across bins.** A sizing framework that treats all trades identically leaves this dispersion on the table.
2. **The best Sharpe slices are the extreme-price lottery tickets.** Exactly what the edge ranker already selects — good.
3. **The sub-10pp-edge filler bins drag the aggregate Sharpe down** from 0.11 to 0.06 without adding proportional return. Minimum-edge should probably be raised.

### 2.3 By category

| Category | n | Win rate | Sharpe | N@90% |
|---|---|---|---|---|
| financial | 997 | 28.3% | 0.130 | 98 |
| other | 14,369 | 63.8% | 0.076 | 283 |
| crypto | 7,535 | 75.2% | 0.054 | 561 |
| sports | 58,588 | 66.2% | 0.054 | 567 |

Financial has the highest per-bet Sharpe but thin volume. Sports and crypto have comparable (low) Sharpe; sports wins on throughput. Politics (n=17, Sharpe 0.285) is too noisy to act on.

## 3. The CI-based sizing framework

### 3.1 Setup

Let `μ_i`, `σ_i` be per-bet mean and std of a candidate in bin/side stratum `i`, expressed per dollar of risk (i.e. `pnl / risk_budget`). If we hold N concurrent positions, each risking `r_i`, with bets independent:

- Total expected P&L: `Σ r_i · μ_i`
- Total std: `sqrt(Σ (r_i · σ_i)²)`
- Aggregate Sharpe: `(Σ r_i μ_i) / sqrt(Σ (r_i σ_i)²)`

For a target book confidence `P(book positive) ≥ α` over the resolution horizon, we need:

```
aggregate_Sharpe ≥ z_α
```

where `z_0.90 = 1.28`, `z_0.95 = 1.64`, `z_0.99 = 2.33`.

### 3.2 Two sizing rules fall out

**Equal-risk-per-bet (simplest).** Set `r_i = r` for all bets. Then aggregate Sharpe = `(per-bet mean Sharpe) · √N`. Required N is:

```
N ≥ (z_α / per-bet_Sharpe)²
```

From §2.1: at high-edge Sharpe 0.110, N=136 for 90% confidence. At aggregate Sharpe 0.057, N=511. The current book (~36) is between 4× and 14× undersized.

**Risk-parity-by-stratum (sharper).** Size each bet so its per-dollar contribution to portfolio variance is equal: `r_i ∝ 1/σ_i`. This pushes capital toward high-Sharpe bins and away from noisy ones. It's the cleanest generalization of Kelly to a heterogeneous book: each bet contributes the same marginal risk, proportional to its Sharpe.

### 3.3 Where this changes behavior vs. the current framework

Concrete example at $10K NAV:
- **Current caps:** `max_position_frac=0.01` → $100/position. `max_category_frac=0.20` → $2K/category → **20 max-sized positions per category** before the cap binds. Across two categories (sports + crypto), the ceiling is ~40 positions. That's well below the 136 high-edge target.
- **CI-framework at 90%:** N=136 effective positions. At equal risk per bet, each takes `1/136` of the book's daily risk budget. If we target 20% book vol per resolution, each bet absorbs `20%·NAV / 136 ≈ 1.5%` of NAV per $1 of σ. The *dollar* cap per position falls out of the vol target, not an arbitrary 1%.
- **Count caps become derivative.** Correlation caps (per-event, per-subseries, per-series) get reinterpreted as effective-N reduction factors — e.g. "10 positions on one NFL weekend counts as ~3 independent bets" — rather than as hard upper bounds divorced from sizing.

The big practical shift: **the book should be running ~3-4× more concurrent positions at ~25-35% smaller per-position size**, and the minimum-edge should be raised to keep capital concentrated in the high-Sharpe slices.

## 4. What this does *not* solve

1. **σ is still a forecast.** The per-bin σ estimates come from 200-10,000 historical resolutions. Small bins (politics, financial) have wide confidence intervals on Sharpe itself. A robust implementation should shrink Sharpe estimates toward a Bayesian prior or use the lower CI bound.
2. **Gaussian tail assumption is wrong.** The 95-100¢ sell_yes bin has Sharpe 0.285 but **kurtosis of dead cats** — one bad cluster of losses blows through the Gaussian 95% CI. A more honest framework would be VaR/CVaR-based rather than Sharpe-based. For now, Sharpe gives us the right *direction* (more positions, more granular sizing) even if the CI numbers aren't precise.
3. **Independence is fiction.** Same-event parlay legs are highly correlated; same-weekend NFL games are moderately correlated; cross-category bets are roughly independent. The correlation caps we already have are the main tool against this, but they currently aren't quantitatively derived from a correlation model.
4. **Doesn't change that we need the calibration to hold.** If the calibration curve is wrong by 5pp at 90¢, all sizing frameworks lose money — just at different rates.

## 5. Candidate next actions (ranked)

1. **Raise min_edge_pp and tighten category filter.** Setting `min_edge_pp=5` (from 3) drops ~90% of low-Sharpe noise trades while keeping the high-Sharpe slice (per §2.1). Cheap, reversible, and meaningful immediately. **Do this first.**
2. **Switch per-position sizing from Kelly to equal-σ.** Each position takes `book_σ_target / (N_target · σ_bin)` of NAV. Loosens the 1% per-position cap in low-σ bins, tightens it in high-σ bins. Net effect: more positions, better-differentiated.
3. **Raise N-ceiling caps.** With equal-σ sizing, `max_category_frac` becomes the wrong knob; the right one is an effective-N ceiling (and that's already roughly enforced by the daily throughput cap and correlation caps). Probably want to raise `max_category_frac` to 0.35-0.40 once equal-σ is in place, or retire it.
4. **Run a parallel paper portfolio** with the new sizer against the current one, same calibration snapshot, same market feed. Compare realized Sharpe and drawdown over 4-6 weeks before changing the production book.
5. **Longer-term: VaR-based sizing for tail-heavy bins.** The 95-100¢ sell_yes bin needs special treatment; one cluster of consecutive losses can eat 30%+ of the book. Either cap its dollar allocation at a low absolute number or drop the bin entirely.

## 6. Open questions

- Is the walk-forward test period (Jan 2026, 1 month) enough to trust the per-bin Sharpe estimates? The narrow bins (n=200-500) are especially suspect.
- Should we weight recent data more heavily when building per-bin σ? Kalshi sports launched mid-2024; the 95-100¢ bin's behavior may be non-stationary.
- What's the right `book_σ_target`? 10% daily? 20% weekly? This is a user-facing knob — drawdown tolerance expressed as one number.
- At what point does correlation erode the independence assumption so badly that N-needed balloons past what the book can hold? We probably need a correlation estimate to answer this rigorously.

## 7. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-20 | Added `max_category_frac=0.20` | User principle: "% of NAV as boundaries, counts derivative." Cap correlated-category drawdown without dictating count. |
| 2026-04-21 | Recognized payoff-profile mismatch | The edge ranker selects lottery-ticket bins, not insurance bins; current framework is sized for the wrong distribution. |
| 2026-04-21 | Built `scripts/return_distribution.py` | Need empirical per-bin μ/σ before committing to a new framework. |
| 2026-04-21 | **This doc** | Journey record + framework proposal. No code change yet. |

## Pointers

- Methodology: [`docs/implementation/methodology.md`](../implementation/methodology.md) §3.4 (current Kelly math), §4.7 (why the win rate is 29%)
- Strategy prospectus: [`docs/rd/deep-dive-prediction-market-underwriting.md`](deep-dive-prediction-market-underwriting.md) — note the insurance framing pre-dates empirical discovery; treat §0-3 as the *intent*, not the observed distribution
- Script: [`scripts/return_distribution.py`](../../scripts/return_distribution.py)
- Portfolio impl: [`src/prospector/underwriting/portfolio.py`](../../src/prospector/underwriting/portfolio.py)
