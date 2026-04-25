# Kalshi Client

> `src/prospector/kalshi/` — REST client, RSA-PSS auth, retention-window
> handling, and the live-vs-historical endpoint split.

---

## Modules

| File | Purpose |
|---|---|
| `client.py` | `KalshiClient` — synchronous httpx-based REST client. Pagination, retries, signed requests. |
| `models.py` | Typed dataclasses for Market, Trade, Orderbook, Position. Handles both legacy cents and new `*_dollars` schema. |

---

## Authentication

RSA-PSS-SHA256 over `{ts_ms}{METHOD}{path_without_qs}`. Headers:
`KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`.

Credentials via env (the user owns the key — agents never read or write
the .env):

```
KALSHI_API_KEY_ID=...
KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/private.pem
# OR
KALSHI_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\n..."
```

---

## Endpoints we use

### Live (auth required, retention-gated)

| Method | Path | Purpose |
|---|---|---|
| `iter_markets(status, event_ticker)` | `/markets` | Paginated active-market scan |
| `iter_events(status, series_ticker)` | `/events` | Paginated event scan; status takes single value only |
| `fetch_market(ticker)` | `/markets/{ticker}` | One market with current bid/ask/last_price |
| `fetch_event(event_ticker)` | `/events/{event_ticker}` | One event with embedded markets (the only way to get markets for resolved events) |
| `fetch_orderbook(ticker, depth)` | `/markets/{ticker}/orderbook` | L2 — retention-gated, no historical alternative |
| `iter_trades(ticker, min_ts, max_ts)` | `/markets/trades` | Paginated trades for a ticker; retention-gated |

### Historical (public, no auth, full history)

| Method | Path | Purpose |
|---|---|---|
| `iter_historical_trades(ticker, min_ts, max_ts)` | `/historical/trades` | Full trade history, ticker-filtered, back to ≥ Jan 2025 |
| `iter_historical_markets(ticker, event_ticker)` | `/historical/markets` | Rich-schema market metadata; includes `settlement_ts`, `rules_primary` |
| `fetch_historical_cutoff()` | `/historical/cutoff` | Per-field boundary timestamps; tells us where live vs. historical splits |

The backfill driver fetches the cutoff once per run and routes each event
based on `strike_date < cutoff`: older → `/historical/*`, newer → live.

---

## Retention model

| Data type | Live retention | Historical alternative |
|---|---|---|
| Trades | Recent only (~weeks) | `/historical/trades` — full history |
| Market metadata | Recent only | `/historical/markets` — full history with richer schema |
| Event metadata | Full history | n/a (live `/events` works back to 2021) |
| L2 orderbook | Recent only | **None — unrecoverable** |
| Account orders | n/a | `/historical/orders` (auth-required) |

L2 orderbook history is the one thing we cannot backfill. Strategies that
need depth must capture forward in time.

---

## API gotchas (memorialize-once)

1. **`/events?status=` is single-value only.** Comma-separated silently
   returns 0 results. The client's `iter_events` was updated 2026-04-22.
2. **`FED-YYMMM` legacy event tickers live under `KXFED` series**, not
   `FED`. Affects the backfill default series list.
3. **`/markets?event_ticker=X` returns empty for resolved events.** Use
   `/events/{event_ticker}` which embeds markets, or `/historical/markets`.
4. **`count_fp` (fractional)** has replaced legacy `count` in trades. Both
   parsers handle both.
5. **Markets schema migrated to `*_dollars` string fields** in January 2026.
   `_parse_market` parses dollars; falls back to legacy cents fields.
6. **`yes_price` is float [0, 1]** in our parsed `Trade` dataclass, not
   integer cents.

---

## Module surface (Python)

```python
from prospector.kalshi import KalshiClient

with KalshiClient() as client:
    # live
    for market in client.iter_markets(status="open"):
        ...
    market = client.fetch_market("KXNFL-...")
    book = client.fetch_orderbook("KXNFL-...", depth=5)

    # historical
    cutoff = client.fetch_historical_cutoff()
    for trade in client.iter_historical_trades(
        "KXNFL-...", min_ts=..., max_ts=...
    ):
        ...
```

The credentials are picked up from env on `KalshiClient()`.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-22 | Built our own client (no dependency on `kalshi-arb-trader`) | Own every line that touches our data |
| 2026-04-22 | `iter_events` series_ticker filter added | Status filter is single-value only; series filter narrows the universe |
| 2026-04-23 | `/historical/*` namespace adopted | Public, no-auth, full history. Routes most backfill traffic; cross-check vs. TrevorJS HF passes byte-for-byte |
| 2026-04-25 | Doc consolidated into platform/ | Was distributed across implementation/data-pipeline.md and inline source comments |
