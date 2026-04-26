# Prospector — Agent Quick-Start

Entry point for any agent session. Read this first; it tells you where to
look for what without requiring a full doc review.

---

## Workflow mode — R&D (active 2026-04-25)

**Commit and push directly to `main`. No feature branches, no pull requests.**

The project is in R&D — solo operator, paper-trading only, sparse
engagement. PR review process is overhead that doesn't earn its weight at
this stage. We deploy and fix if necessary; correctness is enforced by
tests + ruff + the methodology discipline in
[`docs/reference/methodology.md`](docs/reference/methodology.md), not by
PR review.

This **overrides** the global `~/AGENTS.md` "feature branch + PR" mandate
while in R&D mode.

**Revisit when:** Phase 4 (live, real capital) or the user explicitly
asks. At that point, feature-branch + PR workflow comes back automatically.

What stays the same regardless:
- Run ruff + the full test suite before pushing
- Conventional-commit subject lines (`feat:`, `fix:`, `chore:`, etc.)
- Never skip hooks, never force-push to `main`, never amend published commits
- Stage files explicitly (no `git add -A`)
- All other Git Safety Rules in `~/AGENTS.md` still apply

---

## What this project is

**Prospector** is a locally-hosted trading strategy discovery and
deployment system. The active strategy family is **PM Underwriting** —
applying actuarial calibration curves to Kalshi prediction markets via
two parallel paper books (lottery + insurance variants). The original
LLM-driven Elder-template parameter search was rejected as non-viable
2026-04-14.

For the project's full constraint set, axioms, philosophy, operational
limits, and risk tolerance, see [`docs/charter/`](docs/charter/).

---

## Where to look

The documentation is structured into five categories with the same
discipline as the codebase:

| Question | Where to look |
|---|---|
| What is this project, and what may it not do? | [`docs/charter/`](docs/charter/) |
| What's running right now, and what's coming next? | [`docs/rd/pipeline.md`](docs/rd/pipeline.md) |
| How does the paper-trade daemon work? | [`docs/platform/paper-trade-daemon.md`](docs/platform/paper-trade-daemon.md) |
| What does "calibration curve" mean? | [`docs/components/calibration-curves.md`](docs/components/calibration-curves.md) |
| What's our testing rigor? | [`docs/reference/methodology.md`](docs/reference/methodology.md) |
| What does "ideation → live" mean precisely? | [`docs/reference/stages-and-verdicts.md`](docs/reference/stages-and-verdicts.md) |
| When/how do we do strategic re-evaluation? | [`docs/reference/fresh-eyes-playbook.md`](docs/reference/fresh-eyes-playbook.md) |
| What's HIP-4, what's Polymarket doing? | [`docs/reference/external-landscape.md`](docs/reference/external-landscape.md) |
| How do I run X? | [`docs/reference/runbook.md`](docs/reference/runbook.md) |

The full taxonomy is in [`docs/README.md`](docs/README.md).

---

## Current status (one-screen view)

For the live status table across all candidates, see
[`docs/rd/pipeline.md`](docs/rd/pipeline.md). Snapshot:

- **Active:** PM Underwriting · Lottery (paper, since 2026-04-20),
  PM Underwriting · Insurance (paper, since 2026-04-25),
  Elder templates + Bayesian optimization (backtest, since 2026-04-25 —
  reformulation of candidate 00)
- **Terminal:** Elder templates · LLM optimizer (rejected needs-iteration —
  reformulated as #15),
  #4 narrative spread (rejected needs-iteration),
  #10 vol surface (absorbed into PM Phase 5 hedging)
- **Ideation queue:** 10 candidates, see pipeline.md

---

## Repository layout

```
prospector/
├── AGENTS.md                         <- you are here
├── pyproject.toml
├── src/prospector/
│   ├── kalshi/                       <- REST client, RSA-PSS auth
│   ├── data/                         <- Hyperliquid + Coinbase + ingest
│   ├── strategies/pm_underwriting/   <- PM book code
│   ├── dashboard.py                  <- streamlit dashboard
│   ├── manifest.py                   <- strategy manifest loader
│   └── ledger.py, orchestrator.py    <- legacy Elder-track scaffolding
├── scripts/
│   ├── paper_trade.py                <- the runner; both books invoke this
│   ├── compute_clv.py                <- closing-line-value scoring
│   ├── backfill_kalshi.py            <- historical pull
│   ├── pull_kalshi_incremental.py    <- daily cron entry point
│   ├── refresh_calibration_store.py  <- rebuild calibration snapshot
│   ├── compute_sigma_table.py        <- rebuild σ-table
│   ├── dashboard.py                  <- streamlit entry
│   └── launchd/                      <- plists for the daemons
├── tests/
├── data/                             <- gitignored
│   ├── kalshi/{markets,trades}/      <- unified parquet tree
│   ├── hyperliquid/, coinbase/, ohlcv/
│   ├── calibration/                  <- store + σ-table
│   └── paper/<book>/                 <- per-book portfolio DB + logs
└── docs/
    ├── README.md                     <- entry point + taxonomy
    ├── charter/                      <- the brief; rarely changes
    ├── platform/                     <- infrastructure
    ├── components/                   <- reusable mechanisms
    ├── rd/                           <- candidate pipeline
    │   ├── pipeline.md               <- cross-strategy status
    │   └── candidates/               <- one file per candidate
    ├── reference/                    <- methodology, glossary, runbook,
    │   │                                playbooks, external landscape
    │   └── fresh-eyes-reviews/       <- dated review archive
    └── implementation/archived/      <- legacy Elder-track design specs
```

---

## Environment and tooling

```bash
source /Users/wgilman/workspace/prospector/.venv/bin/activate

PYTHONPATH=src pytest -q tests          # tests
ruff check src tests scripts             # lint

# Per-task scripts — full reference at docs/reference/runbook.md
python scripts/paper_trade.py --once
python scripts/compute_clv.py
streamlit run scripts/dashboard.py
```

See [`docs/reference/runbook.md`](docs/reference/runbook.md) for the full
operational guide.

---

## How to add a new candidate

1. Pick the next available ID from [`docs/rd/pipeline.md`](docs/rd/pipeline.md).
2. Copy the template from [`docs/rd/README.md`](docs/rd/README.md).
3. Create `docs/rd/candidates/NN-name.md`.
4. Fill in the **Status snapshot** + **Ideation** sections.
5. Add a row to `docs/rd/pipeline.md`.
6. Add the first decision-log entry.

Stage transitions follow [`docs/reference/stages-and-verdicts.md`](docs/reference/stages-and-verdicts.md).

---

## Sibling projects (don't duplicate)

The user's friend operates `kalshi-autoagent`, `kalshi-arb-trader`,
`crypto-copy-bot`, `options-autoagent` under
`~/workspace/other-trading-projects/`. Lessons we've imported and what's
already covered there is in
[`docs/reference/sibling-projects.md`](docs/reference/sibling-projects.md).
