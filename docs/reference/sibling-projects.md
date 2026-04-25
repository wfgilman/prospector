# Sibling Projects

> Notes on `kalshi-autoagent`, `kalshi-arb-trader`, `crypto-copy-bot`,
> `options-autoagent`. What's covered there, what we should not duplicate,
> lessons we import.

These are four active trading systems in the user's friend's portfolio
under `~/workspace/other-trading-projects/`. The user draws lessons from
these projects but didn't author them. The friend runs an inner loop on
an old MacBook Air. Knowing what's covered there lets us avoid
duplication and stand on shoulders.

---

## Portfolio inventory

| Project | Market | Strategy type | Status | Key metric |
|---|---|---|---|---|
| **kalshi-autoagent** | Kalshi PM | 5 structural arb strategies (two-loop) | Paper → live | $23K P&L, 290+ trades, 57% WR in 2 days |
| **kalshi-arb-trader** | Kalshi PM | Execution agent for autoagent configs | Live | — |
| **crypto-copy-bot** | Hyperliquid + Kraken | Copy trading + funding arb | Live | ~60 trades/day |
| **options-autoagent** | IBKR (options) | Constraint violation detection (two-loop) | Backtested | 100% WR composite, 95.8% EV |

---

## What's already covered (don't build)

### Kalshi intra-market structural arb

`kalshi-autoagent` runs five strategies, all exploiting **mathematical
constraint violations**:

1. **Crypto bucket arb** (94.9% WR) — bucket prices should sum to 1.0
2. **Financial bucket arb** (91.2% WR) — same logic on NASDAQ/SPX/INX
3. **Threshold ladder arb** (79.3% WR) — monotonicity: P(BTC > 55k) ≤ P(BTC > 50k)
4. **Cross-event consistency** (74.6% WR) — NASDAQ↔INX, BTC↔ETH correlation-based
5. **Cross-product consistency** (65.5% WR) — threshold vs bucket-sum identity

Plus a **weather market maker** (zero maker fees, resting two-sided quotes).

**Implication:** Prospector should not rebuild these. Build strategies
that **complement** them — especially cross-market strategies that use
Kalshi + crypto together. PM Underwriting exploits *statistical*
violations (calibration deviations); autoagent exploits *mathematical*
violations (sum-to-1, monotonicity). Different signal source, same data
+ execution infrastructure.

### Funding rate arb (spot-futures)

`crypto-copy-bot` runs this on Kraken: long spot + short futures, collect
funding. Parameters: `min_apr=15%`, `exit_apr=2%`, max $2500/position,
max 5 positions, 30-min scan.

**Implication:** Prospector could extend to **perp-perp cross-exchange**
arb (Hyperliquid vs. Binance/Bybit) which is structurally different and
not currently running. Listed in original `strategy-families.md` as #11.

### Copy trading

`crypto-copy-bot` scores 31K+ Hyperliquid traders, copies the top scorers
with Bayesian confidence updating, trailing stops, take-profit, consensus
vs. alpha lanes, AI regime classification (Sonnet every 30 min), anomaly
detection, daily auto-tuning.

**Implication:** Not a prospector concern. Different problem entirely.

---

## Architectural lessons to import

### 1. Two-loop architecture (proven twice)

Both autoagent projects use:
- **Inner loop** (7B Ollama, autonomous): proposes JSON configs,
  evaluates against tasks, keeps/discards by score
- **Outer loop** (Claude, on-demand): reads results, spots patterns,
  adds new features/knobs

This is the architecture prospector was originally built around, and it
works — **but only when the inner-loop problem is categorical** (which
config to try) not continuous (what parameter value to use). The kalshi
strategies have small discrete search spaces with clear mathematical
signal. Elder templates had large continuous spaces with noisy signal.
Codified as [axiom 5](../charter/axioms.md).

### 2. Point-in-time (PIT) pricing is sacred

`kalshi-autoagent` learned this the hard way: using terminal `last_price`
inflated scores from 45 to 140 (phantom profits). All evaluations must
use real traded prices at market midpoint (50% of contract duration).
`precompute_pit.py` builds a SQLite table for fast task generation.

**Imported:** [calibration-curves component](../components/calibration-curves.md)
uses ASOF join + 25% offset filter. PM Underwriting Phase 1 backtest
methodology is built on this.

### 3. Execution realism eats the edge

Backtesting at `last_price` showed +$0.024/trade. Backtesting at
executable prices (yes_ask for buys) showed −$0.018/trade. The spread
eats 100% of the "edge" and then some. `min_edge_threshold` had to be
3.5× higher (0.35 vs. 0.10) to survive real execution.

**Imported:** PM Underwriting scanner uses executable prices (yes_bid for
sell_yes, 1 - no_bid for buy_yes), not mids. CLV instrumentation is the
ongoing measurement of "are real fills tracking calibration prices?"

### 4. Scoring defines what you optimize

EV scoring (maximize total $) and composite scoring (maximize per-trade
quality) produce *opposite configs* from the same strategy code. This is
first-order, not a tuning footnote.

**Imported:** PM Underwriting objective function is explicit (book-level
Sharpe target via equal-σ sizing); the lottery-vs-insurance reframing is
a recognition that the *ranker* implicitly chooses the objective.

### 5. Orderbook depth is a first-class constraint

All three live executors check depth before firing. `crypto-copy-bot`
rejects entries where current mid differs >5% from trader's entry.
`kalshi-arb-trader` pre-checks ALL legs at 100% depth before firing any
cross-event trade. `options-autoagent` uses bid/ask (not mid) for all
evaluations.

**Imported:** PM Underwriting scanner uses orderbook depth (`scanner.py`
`_executable_prices`).

### 6. Concurrent meta-loop locking

`kalshi-autoagent` had a collision bug where two meta-loops clobbered
each other's config writes. Fixed with PID-based lockfile at
`/tmp/kalshi_meta_loop.lock`. Apply to any multi-process orchestration.

**Imported:** Not yet relevant — prospector currently has one daemon per
book, no multi-loop config writers. Worth knowing if/when we add a
meta-loop.

### 7. Bayesian confidence for regime stability

`crypto-copy-bot` uses Bayesian score updating: incumbents' scores move
slowly (3% of raw delta at confidence=30). New candidates must beat the
lowest incumbent by 5+ points. This prevents daily churn from noise.

**Imported as principle:** Any regime classifier (e.g., "is this funding
rate sustainable?") should use Bayesian updating, not point estimates.
Not yet applied to a prospector strategy; flagged here for future
candidates.

### 8. Stale `last_price` on illiquid OTM strikes

The sibling `kalshi-arb-trader` ran 0-14 win-rate on illiquid ladders for
three days before catching this. `last_price` can be hours stale on
markets with no recent trading.

**Imported:** [hedging-overlay-perp component](../components/hedging-overlay-perp.md)
explicitly flags this as a high-likelihood risk; the mitigation is to
reject any strike where `last_price` falls outside the live `[yes_bid,
yes_ask]` when a valid book exists. Sibling has `tests/test_staleness_gates.py`
as the template.

---

## Portfolio gaps where prospector adds value

Every current sibling strategy operates **within a single market**:

- `kalshi-autoagent`: Kalshi only
- `crypto-copy-bot`: Hyperliquid only (copy) or Kraken only (funding)
- `options-autoagent`: IBKR options only

**Nobody is trading across markets.** The biggest gap in the portfolio
is cross-market strategies that use information from one venue to trade
on another:

1. **Kalshi ↔ Hyperliquid** — explored in [#10](../rd/candidates/03-kalshi-hyperliquid-vol-surface.md)
   (closed as standalone; folded into [hedging-overlay-perp](../components/hedging-overlay-perp.md))
2. **Hyperliquid ↔ other exchange perps** — cross-exchange funding spread
   (different from Kraken spot-futures arb)
3. **Kalshi ↔ Polymarket ↔ HIP-4** — three-venue PM divergence
   ([#07](../rd/candidates/07-three-venue-pm-divergence.md))
4. **Kalshi ↔ CME weather** — same NOAA underlying, totally different
   audiences ([#09](../rd/candidates/09-kalshi-cme-weather-convergence.md))

Plus: Kalshi-native angles the autoagent doesn't cover — time-decay
exploitation, longshot-bias harvesting (PM Underwriting), weather model-
driven strategies.

---

## Data and infrastructure already available

From the sibling projects, these data sources and integrations exist
and could be referenced (not imported wholesale — we own our own clients):

| Resource | Source project | What it provides |
|---|---|---|
| Kalshi API client (RSA-PSS auth) | kalshi-arb-trader | Reference for auth patterns |
| Kalshi historical data (420K markets, 16M trades) | kalshi-autoagent (via kalshi-data-collector) | We've migrated this into our unified tree |
| Hyperliquid execution client | crypto-copy-bot | Reference for live perp execution patterns |
| Hyperliquid OHLCV + orderbook | prospector | Owned in-repo |
| Kraken spot + futures (CCXT) | crypto-copy-bot | Available if needed |
| FRED economic data (21 series) | kalshi-autoagent | Macro context for PM strategies |
| NWS weather data (12 cities) | kalshi-autoagent | Reference for weather work (#05) |
| PIT pricing methodology | kalshi-autoagent | Imported into PM Underwriting |
| Two-loop orchestration framework | autoagent projects | Reference, not currently imported |

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-15 | Sibling-project survey before strategy selection | Don't duplicate; stand on shoulders |
| 2026-04-22 | Built our own Kalshi client (no dependency on `kalshi-arb-trader`) | "Own every line that touches our data" — see [`platform/kalshi-client.md`](../platform/kalshi-client.md) |
| 2026-04-25 | Doc moved from `rd/sibling-project-insights.md` to `reference/sibling-projects.md` | Reorg: this is project-wide reference info, not R&D |
