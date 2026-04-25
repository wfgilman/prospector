# MVT Rolling-Quality Threshold

> Charnov's Marginal Value Theorem applied to scanner admission. Don't
> fill a scarce slot with a candidate below the rolling-window quality
> average — wait for the next tick.

**Status:** Designed (2026-04-25). Not yet implemented. Surfaced in the
fresh-eyes review as candidate T2.

---

## What it does

The scanner currently picks the highest-edge candidates *that meet the
static `min_edge_pp` floor*. If on a particular tick the best edge
available is 5.2pp (just above the 5pp floor), the runner takes it. But
if a different tick offers 12pp, that scarce daily slot was used on a
mediocrity.

MVT-rolling-threshold replaces the static floor with a **rolling
empirical bar**: don't take a candidate whose `edge_pp / σ_bin` is below
the rolling-window average across recently-entered trades. Wait for a
better tick.

---

## The MVT analogy

In Charnov 1976: a forager experiences diminishing returns inside a patch
and faces travel time between patches. Optimal rule: leave the patch when
in-patch capture rate equals the long-run average across the habitat.

Translation:

| Foraging | Scanner |
|---|---|
| Patch | One scan tick's universe of candidates |
| In-patch capture rate | Quality (`edge_pp / σ_bin`) of available candidates *now* |
| Travel time | 15-min interval between scans |
| Average capture rate over habitat | Rolling-window average quality across recent ticks |

Subtle disanalogy: foraging treats *time* as the resource; we treat
*daily-cap slots* as the resource. The math is identical — don't fill a
scarce slot with a mediocre opportunity if the average is better.

---

## Math

Maintain rolling stats of recently-entered candidates' `edge_pp / σ_bin`
across the last `N` candidates (default N=100, ~1 week of fills).

```
quality_i = edge_pp_i / σ_bin_i
rolling_avg = mean(quality across last N entered candidates)

# Admission rule
admit candidate iff quality_i ≥ rolling_avg
```

Three guardrails:
- **Warmup:** for first M ticks (default M=50 entered candidates), use
  static `min_edge_pp` floor only — need data to compute the avg.
- **Bounded adjustment:** the threshold can move at most ±X% per day to
  prevent feedback chase (rising threshold → fewer fills → those few are
  higher-quality → threshold rises further).
- **Backstop:** the static `min_edge_pp` floor still applies — MVT can
  raise the bar but never lower it below the absolute minimum.

---

## Variants worth considering

1. **Single global threshold** (recommended starting point): one rolling
   avg across all entered candidates. Simplest, may be too coarse (a 60¢
   crypto candidate competing against an 85¢ sports candidate is
   apples-oranges).
2. **Per-(category, side, 5¢ bin) threshold:** more accurate but sparse
   bins are unstable. Worth trying after (1) shows promise.
3. **Per-tick percentile cutoff** (e.g., 75th of recent N): self-
   calibrating, behaviorally identical to (1) at smooth distributions.

---

## What signal to use

**v1 — calibration edge.** Use `edge_pp / σ_bin` since that's what we
have. This is the only signal available pre-CLV.

**v2 — realized CLV by bin** (after ~30 days of CLV data). CLV is what
the market actually does, not what calibration *predicts*. Re-anchor MVT
to: "take candidates whose bin has historically shown CLV ≥ rolling avg."
Much stronger signal because it sidesteps calibration drift.

The v1 implementation should be shaped so swapping in v2 later doesn't
require a rewrite — keep the quality function pluggable.

---

## Implementation sketch

When implemented:

```
src/prospector/strategies/pm_underwriting/quality_history.py
  - MVTGate class: maintains rolling stats, emits admit/reject decisions
  - Persists rolling state to a small new SQLite table on the portfolio
  - Plugs into runner.run_once() between sizing and entry

RunnerConfig.mvt_window: int = 0  # 0 = disabled (default)
RunnerConfig.mvt_warmup: int = 50
RunnerConfig.mvt_max_daily_drift_pct: float = 0.20

Tests:
  - First-N-tick warmup (gate inactive)
  - Rolling stat correctness across boundary cases
  - Threshold move within bounded-adjustment cap
  - Rejection triggers correct logging + counter
```

Estimated: ~80 LOC + ~30 LOC tests.

---

## Where it would apply

**Recommended first deployment: insurance book only.** It has more daily-
cap headroom (lottery is already pinning at 20/day, so MVT can't shift much
without leaving slots empty). The lottery book stays on static floor until
we see whether MVT meaningfully changes which trades land.

If MVT works on insurance, the lottery book gets it next.

---

## Trade-offs

**Why this works:** Directly tests the CLV finding ("scanner is filling
slots with mediocrities that don't survive 15 min"). Self-tuning — no
fixed knob to tune; the threshold is data-driven. Trivial code if the
rolling stat is structured cleanly.

**What it gives up:**
- **Slots may go empty.** If a tick has no candidate above rolling avg, the
  daily count drops. This is the *point* — better to leave a slot empty
  than fill it with mediocrity — but it changes the throughput profile.
- **Feedback chase risk.** Mitigated by warmup + bounded daily adjustment,
  but the loop is real.
- **Doesn't address calibration accuracy.** If the calibration is wrong by
  5pp at 90¢, MVT's "high-quality" candidates are still wrong — they're
  just consistently wrong. CLV (component) catches this; MVT doesn't.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-25 | Designed during fresh-eyes review (T2) | The static `min_edge_pp` floor is too crude given CLV evidence that scanner is admitting trades that don't survive 15 min |
| 2026-04-25 | Recommended insurance-book first deployment | Lottery is at daily cap; insurance has headroom for MVT to shift without leaving slots empty |
| 2026-04-25 | Pluggable quality-function design (v1=edge, v2=CLV) | Don't bake in calibration-edge as the only signal; CLV is the better anchor once we have data |
