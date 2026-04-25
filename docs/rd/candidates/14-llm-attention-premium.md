---
id: 14
name: LLM-scored attention premium
status: ideation
verdict: pending
last-update: 2026-04-25
related-components:
  - llm-altdata-extraction
---

# Candidate 14: LLM-Scored Attention Premium

## Status snapshot

- **Stage:** ideation
- **Verdict:** pending — Tier 3 from fresh-eyes review; narrower reformulation of #02 narrative spread
- **Next move:** No immediate action; revisit if narrative-spread (#02) is rescued and a finer-grained variant becomes interesting.

## Ideation

**Origin:** When a Kalshi contract (e.g., "Will Musk post X this week?")
goes viral on crypto Twitter, the correlated perp (DOGE, $TRUMP, WLFI)
moves on **attention**, not fundamentals. LLMs can score sentiment-
weighted volume in real time — i.e., not just sentiment, but how much
volume of attention the topic is generating across feeds.

Take a position when LLM-scored attention diverges from price (attention
high, price hasn't moved → buy; price moved, attention waning → fade).

**This is a narrower #04 narrative-spread reformulation:** instead of
mapping macro events → crypto via β maps, map *attention magnitude* →
specific meme tokens. Less ambitious because the universe is narrower
(meme tokens), but the LLM's role is sharper.

**Axiomatic fit:**
- *Combinations* — sentiment scoring (existing) + LLM-as-volume-weighter
  (less common) + crypto memes (large surface area)
- *LLM categorical role* — text classification with structured output
- *Operational* — would need real-time Twitter / Discord scraping;
  borderline cadence

## Deep dive

(Empty until promoted.)

## Statistical examination

(Empty.)

## Backtest

(Empty.)

## Paper portfolio

(Empty.)

## Live trading

(Empty.)

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Surfaced as T12 in fresh-eyes review (Tier 3) | Narrower #04 reformulation; defer until #04 is reopened |
| 2026-04-25 | Tier 3 — not urgent | Currently an idea, not a thesis with a clean kill criterion |

## Open questions

- Data source — X/Twitter API (cost), Discord (which servers), Reddit?
- Attention-weighting math — volume × sentiment? Volume / (recency)?
- Scope — meme tokens only, or any token-narrative mapping?
- Backtest methodology — historical Twitter data is hard to get cheaply

## Pointers

- Broader sister candidate: [`02-kalshi-crypto-narrative-spread.md`](02-kalshi-crypto-narrative-spread.md)
- LLM altdata pattern: [`components/llm-altdata-extraction.md`](../../components/llm-altdata-extraction.md)
