"""Load the per-bin σ table and look up per-trade σ for equal-σ sizing.

The σ table is produced by `scripts/compute_sigma_table.py` from the
walk-forward test set. Lookup priority: exact (category, side, price_bin) →
pooled (category, side) → global aggregate. A failed lookup raises
`MissingSigma` so the runner rejects the candidate rather than guessing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class MissingSigma(KeyError):
    """Raised when no σ estimate exists for a (category, side, price) lookup."""


@dataclass(frozen=True)
class SigmaEntry:
    n: int
    mu: float
    sigma: float


@dataclass(frozen=True)
class SigmaTable:
    built_at: str
    source_window: str
    aggregate: SigmaEntry
    pooled: dict[tuple[str, str], SigmaEntry]
    bins: dict[tuple[str, str, int], SigmaEntry]

    def lookup(self, category: str, side: str, entry_price: float) -> SigmaEntry:
        """Return the best σ estimate, preferring the narrowest scope available."""
        bin_low = _price_to_bin(entry_price)
        exact = self.bins.get((category, side, bin_low))
        if exact is not None:
            return exact
        pool = self.pooled.get((category, side))
        if pool is not None:
            return pool
        if self.aggregate.sigma > 0:
            return self.aggregate
        raise MissingSigma(
            f"no σ entry for category={category!r} side={side!r} "
            f"bin={bin_low}-{bin_low + 5} (and no fallback)"
        )


def _price_to_bin(entry_price: float) -> int:
    """Map a fractional entry price (0-1) to a 5¢-wide bin_low in [0, 95]."""
    if not 0.0 < entry_price < 1.0:
        raise ValueError(f"entry_price must be in (0, 1), got {entry_price}")
    cents = int(entry_price * 100)
    return min(95, (cents // 5) * 5)


def load_sigma_table(path: str | Path) -> SigmaTable:
    """Load the JSON σ table produced by `compute_sigma_table.py`."""
    with Path(path).open() as f:
        payload = json.load(f)
    agg = payload["aggregate"]
    aggregate = SigmaEntry(n=int(agg["n"]), mu=float(agg["mu"]), sigma=float(agg["sigma"]))

    pooled: dict[tuple[str, str], SigmaEntry] = {}
    for row in payload["pooled"]:
        cat, side = row["key"].split("|", 1)
        pooled[(cat, side)] = SigmaEntry(
            n=int(row["n"]), mu=float(row["mu"]), sigma=float(row["sigma"])
        )

    bins: dict[tuple[str, str, int], SigmaEntry] = {}
    for row in payload["bins"]:
        key = (row["category"], row["side"], int(row["bin_low"]))
        bins[key] = SigmaEntry(
            n=int(row["n"]),
            mu=float(row["mu"]),
            sigma=float(row["sigma_shrunk"]),
        )

    return SigmaTable(
        built_at=payload["built_at"],
        source_window=payload["source_window"],
        aggregate=aggregate,
        pooled=pooled,
        bins=bins,
    )
