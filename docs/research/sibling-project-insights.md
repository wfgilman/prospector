# Sibling Project Insights

Lessons from the four active trading systems in `/Users/wgilman/workspace/other-trading-projects/` that should inform prospector's research phase. The goal is to stand on these shoulders, not duplicate them.

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
kalshi-autoagent runs five strategies, all exploiting mathematical constraint violations:

1. **Crypto bucket arb** (94.9% WR) — bucket prices should sum to 1.0; buy when underpriced, sell when overpriced.
2. **Financial bucket arb** (91.2% WR) — same logic on NASDAQ/SPX/INX buckets.
3. **Threshold ladder arb** (79.3% WR) — monotonicity: P(BTC > 55k) ≤ P(BTC > 50k).
4. **Cross-event consistency** (74.6% WR) — NASDAQ↔INX, BTC↔ETH correlation-based.
5. **Cross-product consistency** (65.5% WR) — threshold vs bucket-sum identity arb. Novel: P(underlying > X) == Σ P(bucket_i) for buckets with strike ≥ X. 324 of 766 events have both -T and -B contracts.

Plus a **weather market maker** (zero maker fees on Kalshi, resting two-sided quotes).

**Prospector should not rebuild these.** Instead, build strategies that *complement* them — especially cross-market strategies that use Kalshi + crypto together.

### Funding rate arb (spot-futures)
crypto-copy-bot runs this on Kraken: long spot + short futures, collect funding. Parameters: min_apr=15%, exit_apr=2%, max $2500/position, max 5 positions, 30-min scan.

**Prospector could extend this** to perp-perp cross-exchange arb (Hyperliquid vs Binance/Bybit), which is structurally different and not currently running.

### Copy trading
crypto-copy-bot scores 31K+ Hyperliquid traders, copies the top scorers with Bayesian confidence updating. Sophisticated: trailing stops, take-profit, consensus vs alpha lanes, AI regime classification (Sonnet every 30 min), anomaly detection, daily auto-tuning.

**Not a prospector concern.** Different problem entirely.

---

## Architectural lessons to import

### 1. Two-loop architecture (proven twice)
Both autoagent projects use:
- **Inner loop** (7B Ollama, autonomous): proposes JSON configs, evaluates against tasks, keeps/discards by score.
- **Outer loop** (Claude, on-demand): reads results, spots patterns, adds new features/knobs.

This is the same architecture prospector was built around, and it works — but only when the inner-loop problem is categorical (which config to try) not continuous (what parameter value to use). The kalshi strategies have small discrete search spaces with clear mathematical signal. Elder templates had large continuous spaces with noisy signal.

### 2. Point-in-time (PIT) pricing is sacred
kalshi-autoagent learned this the hard way: using terminal `last_price` inflated scores from 45 to 140 (phantom profits). All evaluations must use real traded prices at market midpoint (50% of contract duration). `precompute_pit.py` builds a SQLite table for fast task generation.

**For prospector:** any backtest on Kalshi data must use PIT pricing. Import the methodology.

### 3. Execution realism eats the edge
Backtesting at `last_price` showed +$0.024/trade. Backtesting at executable prices (yes_ask for buys) showed −$0.018/trade. The spread eats 100% of the "edge" and then some. `min_edge_threshold` had to be 3.5× higher (0.35 vs 0.10) to survive real execution.

**For prospector:** never evaluate a strategy without executable-price backtesting. Build orderbook-aware evaluation into the harness from day 1.

### 4. Scoring defines what you optimize
EV scoring (maximize total $) and composite scoring (maximize per-trade quality) produce *opposite configs* from the same strategy code. This is first-order, not a tuning footnote.

**For prospector:** choose the objective function deliberately. The Elder track's NAV-based scoring was sensible but conflated single-window performance with durability.

### 5. Orderbook depth is a first-class constraint
All three live executors check depth before firing. crypto-copy-bot rejects entries where current mid differs >5% from trader's entry. kalshi-arb-trader pre-checks ALL legs at 100% depth before firing any cross-event trade. options-autoagent uses bid/ask (not mid) for all evaluations.

### 6. Concurrent meta-loop locking
kalshi-autoagent had a collision bug where two meta-loops clobbered each other's config writes. Fixed with PID-based lockfile at `/tmp/kalshi_meta_loop.lock`. Apply to any multi-process orchestration.

### 7. Bayesian confidence for regime stability
crypto-copy-bot uses Bayesian score updating: incumbents' scores move slowly (3% of raw delta at confidence=30). New candidates must beat the lowest incumbent by 5+ points. This prevents daily churn from noise.

**For prospector:** any regime classifier (e.g., "is this funding rate sustainable?") should use Bayesian updating, not point estimates.

---

## Portfolio gaps (where prospector adds value)

Every current strategy operates **within a single market**:
- kalshi-autoagent: Kalshi only
- crypto-copy-bot: Hyperliquid only (copy) or Kraken only (funding)
- options-autoagent: IBKR options only

**Nobody is trading across markets.** The biggest gap in the portfolio is cross-market strategies that use information from one venue to trade on another:

1. **Kalshi ↔ Hyperliquid** — Kalshi crypto-price contracts encode an implied probability distribution for BTC/ETH/SOL/XRP. Hyperliquid perps encode a different (funding-rate-implied, basis-implied) distribution. When they disagree, someone is wrong.
2. **Hyperliquid ↔ other exchange perps** — cross-exchange funding spread, different from Kraken spot-futures arb.
3. **Kalshi ↔ Kalshi (new angles)** — kalshi-autoagent covers the mathematical constraints. What it doesn't cover: time-decay exploitation (systematic, not market-making), longshot bias harvesting, and weather-model-driven directional strategies.

---

## Data and infrastructure already available

From the sibling projects, these data sources and integrations already exist:

| Resource | Source project | What it provides |
|---|---|---|
| Kalshi API client (RSA-PSS auth) | kalshi-arb-trader | Orders, events, positions, fills, orderbooks |
| Kalshi historical data (420K markets, 16M trades) | kalshi-autoagent (via kalshi-data-collector) | PIT pricing, task generation |
| Hyperliquid execution client | crypto-copy-bot | Orders, positions, leverage, balance |
| Hyperliquid OHLCV + orderbook | prospector | Historical candles, live L2 depth |
| Kraken spot + futures (CCXT) | crypto-copy-bot | Spot buy, futures short, funding collection |
| FRED economic data (21 series) | kalshi-autoagent | Macro context for PM strategies |
| NWS weather data (12 cities) | kalshi-autoagent | Weather context for PM strategies |
| PIT pricing methodology | kalshi-autoagent | precompute_pit.py + SQLite pit_prices table |
| Two-loop orchestration framework | kalshi-autoagent, options-autoagent | Inner loop (Ollama), outer loop (Claude), config format, scoring |

Prospector doesn't need to build any of these from scratch. Adapt and import.
