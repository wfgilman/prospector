# LLM Alternative-Data Extraction

> Pattern: use a local LLM as a feature generator over unstructured text
> that humans don't have time to read systematically. The LLM's output
> becomes a tradeable feature, not a trade decision.

**Status:** Designed (2026-04-25). Not yet implemented. Surfaced in
fresh-eyes review as candidate T6 (NWS Area Forecast Discussions for
weather contracts).

---

## What it does

Some categories of unstructured text contain expert judgment that's
**not present in the structured data products downstream**:

- **NWS Area Forecast Discussions** — meteorologists publish 2× daily
  per station, paragraphs of narrative explicitly contradicting model
  output ("models probably underforecast max temps due to wildfire haze
  reducing radiational cooling")
- **SEC 8-K filings** — material events with narrative context that ML-
  based parsers often misclassify
- **FOMC minutes** — tone, hedge language, dissent indicators
- **Project Discord / Twitter / Medium posts** — for token-unlock work,
  the team's positioning around an unlock window matters

The pattern: pull the unstructured text, feed it to a local LLM with a
narrow extraction prompt, persist the structured output as features that
strategy code can read alongside numerical inputs.

---

## Why this is the LLM's natural niche

Per [`charter/axioms.md`](../charter/axioms.md) §5: the LLM's comparative
advantage is **categorical reasoning over text**. Generating structured
features from unstructured text is the cleanest example of that advantage.
This is what NLP-shop hedge funds built over the last decade — but local
Ollama at the 7-13B scale brings that capability to a solo operator.

This is *not* what the Elder track tried to do. Elder asked the LLM to do
continuous parameter optimization; that failed cleanly. Feature extraction
from text is structurally different: it's a per-document classification
task, not an optimization loop.

---

## The pattern

Five layers, all atomic:

1. **Source pull.** A scheduled job fetches the source documents (NOAA
   FTP for AFDs; SEC EDGAR; Twitter / Medium APIs). Cron-friendly,
   idempotent.
2. **Document store.** Append-only parquet at `data/altdata/<source>/`,
   partitioned by date. One row per document. Raw text preserved.
3. **Feature extraction.** A separate cron job scans new documents,
   prompts the LLM, parses structured output (JSON or YAML), persists.
4. **Feature store.** Parquet at `data/altdata/<source>/features/`,
   keyed by source-document timestamp. Strategy code reads via DuckDB.
5. **Strategy integration.** A strategy that uses the feature treats it
   like any other input — joins by timestamp, applies as an overlay on
   the underlying signal.

Critically: layers 3-5 can fail or lag without breaking layer 1-2. The raw
text archive is the load-bearing piece; features can be re-extracted later
if the prompt changes.

---

## Prompt discipline

The LLM extraction prompt has a narrow shape:

```
Read the following <document type>. Extract:
- <feature 1>: <type>, <description>
- <feature 2>: <type>, <description>
- ...
Output JSON matching the schema. If a feature can't be extracted, use null.
Do not include any commentary or explanation.

<document text>
```

Why narrow:
- **Bounded output space.** Strict JSON schema prevents hallucination
  drift.
- **Auditable per-document.** Can re-run on a single document and inspect.
- **Versionable prompt.** Prompt + schema are checked into the repo;
  changes trigger feature re-extraction with provenance.

---

## Hardware footprint

Local Ollama (`qwen2.5-coder:7b` or similar 7-13B model) on the M3 16GB.
Per-document inference budget: a few hundred tokens out, a few thousand
in. Latency under 2s per document. Comfortable for a few thousand
documents per day; AFDs are 2× daily × ~12 cities = 24 docs/day, trivial.

---

## What this is NOT

- **Not LLM-as-trader.** The LLM does not decide to enter or exit
  positions. It generates features that strategies use.
- **Not LLM-as-ranker.** Use the calibration curve and σ-table for that.
- **Not real-time.** Document fetches and feature extraction run on a
  schedule; strategies use the latest available extraction.
- **Not the Elder approach.** Elder used the LLM as a continuous
  optimizer, which failed. This uses the LLM as a per-document
  classifier, which is its strength.

---

## Where it would apply

Currently scoped only to the **weather ensemble candidate** (NWS AFD
extraction). Other applications worth considering once the pattern proves
out:

- **SEC 8-K filings** for any future strategy that touches token unlocks
  or governance events
- **FOMC minutes / press conference transcripts** for #4 narrative-spread
  reformulation if revisited
- **CryptoSlate / The Block** for narrative-spread refinement (T12)

---

## Implementation pointer

When implemented:

```
src/prospector/altdata/
├── nws_afd/
│   ├── source.py       # NOAA FTP fetcher
│   ├── extract.py      # LLM extraction with locked prompt + schema
│   └── store.py        # Parquet writer
├── store.py            # Generic AltDataStore (read-side helpers)
└── prompts/
    └── nws_afd_v1.txt  # Versioned prompt — changes trigger re-extraction

scripts/
├── pull_nws_afd.py         # cron-friendly source-pull
└── extract_nws_features.py # cron-friendly feature-extraction
```

Estimated: ~400-500 LOC for the pattern + first source. Subsequent sources
reuse `AltDataStore` and add a source-specific extractor.

---

## Trade-offs

**Why this works:** Captures information that's unambiguously present in
the source text but not in the structured products downstream. The LLM is
doing exactly what it's good at (text classification with structured
output). Atomic component pattern means each layer can be developed,
tested, and replaced independently.

**What it gives up:**
- **Prompt brittleness.** A change to the prompt or schema invalidates
  prior feature extractions. Mitigated by versioned prompts + ability to
  re-extract from the raw archive.
- **LLM drift across model versions.** Ollama updates may change behavior.
  Mitigated by pinning model versions and running a sanity test on a
  small held-out set when models change.
- **Hallucination risk.** Even with strict JSON schema, LLMs can invent
  values. Mitigated by spot-checking a sample of extractions vs. source
  text before deploying a new prompt to live use.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Designed during fresh-eyes review (T6) | The "LLM as feature generator" niche has not been tried in this project; pairs naturally with the queued #12 weather work |
| 2026-04-25 | Atomic 5-layer pattern (source / doc store / extract / feature store / strategy) | Each layer fails independently; raw archive is load-bearing; re-extraction is cheap |
| 2026-04-25 | Versioned prompts with re-extraction discipline | Treat the prompt as code; schema changes trigger backfill |
