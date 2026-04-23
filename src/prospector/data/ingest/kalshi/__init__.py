"""In-house Kalshi ingest: REST-based historical backfill + incremental pull.

See `docs/implementation/data-pipeline.md` for scope, design principles, and
the M1-M5 milestone plan.
"""

from prospector.data.ingest.kalshi import watermark, writer
from prospector.data.ingest.kalshi.backfill import (
    BackfillPlan,
    BackfillResult,
    backfill_series,
    run_plan,
)
from prospector.data.ingest.kalshi.incremental import pull_incremental

__all__ = [
    "BackfillPlan",
    "BackfillResult",
    "backfill_series",
    "run_plan",
    "pull_incremental",
    "watermark",
    "writer",
]
