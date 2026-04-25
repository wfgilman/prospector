# Constraints

> The hard external boundaries every strategy must respect by construction.

These are not preferences or design tradeoffs — they are non-negotiable
limits set by regulation, employment, or market access. A strategy that
violates a constraint is not "less attractive"; it is **disqualified**.

---

## 1. No securities

The user's employer prohibits trading in securities. This is the most
load-bearing constraint in the project: it has shaped strategy selection
since the project's origin.

**What's a security:** Anything regulated by the SEC under US securities
law. This includes equities, ETFs, options on equities/indices, REITs,
mutual funds, and most corporate debt. Crypto is currently in a contested
regulatory gray zone but is treated by this project as **not a security**
based on CFTC's posture (perpetual futures on Hyperliquid, prediction
contracts on Kalshi are CFTC-regulated event contracts or commodity
derivatives).

**What's explicitly OK:**
- **Kalshi event contracts** — CFTC-regulated designated contract market
- **Hyperliquid perpetual futures** — crypto perp DEX, no securities classification
- **Other crypto perp / spot venues** — provided no SEC entanglement
- **Polymarket** — global crypto-native prediction market (not US securities-regulated)
- **CME commodity futures** — agricultural, energy, weather, FX. CFTC-regulated commodity futures are categorically not securities. *Verify with employer's policy before trading; the verification is a 30-min conversation but has not happened.*

**What's contested / requires verification:**
- **CME weather futures (HDD/CDD)** — commodity futures, but employer policy
  may have its own scope. Flagged in the fresh-eyes review as worth a
  one-time check; not yet done.
- **HIP-3 builder-deployed perpetuals on Hyperliquid** — same regulatory
  category as standard Hyperliquid perps; no additional concern expected.
- **HIP-4 event perpetuals on Hyperliquid** — co-developed with Kalshi,
  expected to inherit Kalshi-style regulatory treatment.

If a strategy's most natural expression involves a security, the strategy
is rejected at ideation. No exceptions, no "small position to test" workarounds.

---

## 2. Solo operator infrastructure

The project runs on the user's MacBook Pro M3 with 16 GB RAM, home internet,
and no co-located servers. This is a real boundary that shapes operational
limits (see [`operational-limits.md`](operational-limits.md)) but it's listed
here as a constraint because some strategies are *categorically* impossible
under this footprint:

- **HFT / sub-second latency arb** — not credible from home internet
- **Co-lo MEV / cross-chain bot operation** — requires infrastructure investment
  the project hasn't authorized
- **Real-time L3 orderbook capture across many venues** — disk + network
  cost not in scope
- **Continuous market-making at scale** — would require always-on quoting infra

A strategy that requires any of these to work is rejected at ideation, OR is
rejected as `non-viable` if it gets that far.

---

## 3. US-resident market access

The user is US-resident. Some venues are accessible; some aren't.

| Venue | US-accessible? | Notes |
|---|---|---|
| Kalshi | Yes | CFTC-designated; primary US prediction market |
| Hyperliquid | Yes | Crypto perp DEX |
| Coinbase | Yes | US-regulated crypto exchange |
| Polymarket | Restricted (geofenced) | Global prediction market; technically inaccessible to US residents but workarounds documented |
| Binance.com (global) | No | Returns 451 to US IPs |
| Binance.US | Yes | Limited subset of pairs |
| Deribit | Restricted | Crypto options venue; may have US-person constraints |
| Pinnacle (sports) | No | Not US-accessible |
| Smarkets (UK PM) | No | UK-only |

A strategy that depends on a non-accessible venue is either rejected or
requires explicit acknowledgement of the access workaround risk.

---

## 4. No live trading without explicit approval

Even after a strategy passes paper-portfolio (Phase 4 in stage terms), the
transition to live capital requires the user's direct authorization. Agents
do not deploy capital, change live order limits, or move from paper to
production without an explicit pull-up.

This is operationally enforced by the daemon's separation of paper and live
modes. There is currently no live execution path wired in; adding one is a
deliberate Phase 4 build, not an incidental change.

---

## 5. Data + credentials handled by the user

- The user owns all API credentials (Kalshi RSA keypair, Hyperliquid signer,
  Coinbase keys). Agents never read or write `.env` files, secret stores, or
  credential paths.
- The project's local SQLite databases are personal; agents read them but
  don't sync them to remote services without explicit instruction.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| (pre-project) | No securities | Employer policy. Original constraint that shaped Prospector's universe selection. |
| 2026-04-23 | Operational triage formalized; cadence + throughput as project limits | Surface the implicit infrastructure boundary as a first-class filter. See [`operational-limits.md`](operational-limits.md). |
| 2026-04-25 | Constraints doc consolidated into charter | Previously distributed across deep-dives; Charter reorganization centralizes for discoverability. |
