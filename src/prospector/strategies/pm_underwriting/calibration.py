"""Calibration store for the PM underwriting strategy.

A calibration is a set of per-category bins over implied probability. Each bin
records how often the market *actually* resolved YES at that implied price,
together with a Wilson-interval confidence band and the fee-adjusted edge. The
scanner looks up a live market's implied price against this store to decide
whether to trade and on which side.

Persisted as JSON (one file per calibration snapshot) so it's small, diff-able,
and easy to hand-inspect. Rebuild from Kalshi history with `refresh()`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KALSHI_TAKER_FEE = 0.07
KALSHI_ROUND_TRIP_FEE_FACTOR = 2 * KALSHI_TAKER_FEE


@dataclass(frozen=True)
class CalibrationBin:
    """A single implied-probability bin in a calibration curve.

    `bin_low` and `bin_high` are in cents (0–100); `actual_rate` is in [0, 1].
    `side` is one of "sell_yes" (implied > actual), "buy_yes" (implied < actual),
    or "" if the bin is not tradeable.
    """

    bin_low: int
    bin_high: int
    n: int
    yes_count: int
    actual_rate: float
    ci_low: float
    ci_high: float
    fee_adj_edge: float
    side: str

    @property
    def implied_mid(self) -> float:
        return (self.bin_low + self.bin_high) / 2 / 100

    @property
    def deviation_pp(self) -> float:
        return (self.actual_rate - self.implied_mid) * 100

    def contains(self, implied: float) -> bool:
        return self.bin_low / 100 <= implied < self.bin_high / 100


@dataclass
class Calibration:
    """A full calibration snapshot: curves keyed by category, plus metadata."""

    built_at: datetime
    data_window_start: str
    data_window_end: str
    min_volume: int
    curves: dict[str, list[CalibrationBin]] = field(default_factory=dict)

    def bins_for(self, category: str) -> list[CalibrationBin]:
        """Return the curve for a category, falling back to aggregate."""
        if category in self.curves:
            return self.curves[category]
        return self.curves.get("aggregate", [])

    def lookup(self, category: str, implied_price: float) -> CalibrationBin | None:
        """Return the bin that covers an implied price for a category."""
        for b in self.bins_for(category):
            if b.contains(implied_price):
                return b
        return None


def fee_adjusted_edge(implied: float, actual: float) -> float:
    """Raw edge minus round-trip Kalshi taker fees.

    Fee model: taker fee per side is 0.07 * p * (1 - p). A round trip
    (open + resolution) therefore costs 2 * 0.07 * p * (1 - p). We subtract
    that from the absolute deviation |actual - implied|.
    """
    raw = abs(actual - implied)
    fee = KALSHI_ROUND_TRIP_FEE_FACTOR * implied * (1 - implied)
    return raw - fee


def trade_side(implied: float, actual: float) -> str:
    """Return 'sell_yes' if overpriced, 'buy_yes' if underpriced, '' if flat."""
    if actual < implied:
        return "sell_yes"
    if actual > implied:
        return "buy_yes"
    return ""


class CalibrationStore:
    """Persist and load calibration snapshots from disk.

    Format: one JSON file per snapshot. The `current` symlink/pointer inside
    the directory names the active snapshot; readers load that by default.
    """

    CURRENT_POINTER = "current.json"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, calibration: Calibration, name: str | None = None) -> Path:
        name = name or f"calibration-{calibration.built_at:%Y%m%dT%H%M%SZ}.json"
        path = self.root / name
        payload = {
            "built_at": calibration.built_at.isoformat(),
            "data_window_start": calibration.data_window_start,
            "data_window_end": calibration.data_window_end,
            "min_volume": calibration.min_volume,
            "curves": {
                cat: [asdict(b) for b in bins]
                for cat, bins in calibration.curves.items()
            },
        }
        with path.open("w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        self._set_current(name)
        return path

    def load_current(self) -> Calibration:
        pointer = self.root / self.CURRENT_POINTER
        if not pointer.exists():
            raise FileNotFoundError(f"No current calibration pointer at {pointer}")
        name = pointer.read_text().strip()
        return self.load(name)

    def load(self, name: str) -> Calibration:
        path = self.root / name
        with path.open() as f:
            payload = json.load(f)
        curves = {
            cat: [CalibrationBin(**b) for b in bins]
            for cat, bins in payload["curves"].items()
        }
        return Calibration(
            built_at=datetime.fromisoformat(payload["built_at"]),
            data_window_start=payload["data_window_start"],
            data_window_end=payload["data_window_end"],
            min_volume=payload["min_volume"],
            curves=curves,
        )

    def _set_current(self, name: str) -> None:
        (self.root / self.CURRENT_POINTER).write_text(name)


def build_bins_from_rows(
    rows: list[tuple[int, int, int, int]],
    min_n: int = 100,
    min_deviation_pp: float = 3.0,
) -> list[CalibrationBin]:
    """Assemble `CalibrationBin`s from raw (bin_low, bin_high, n, yes_count) rows.

    A bin is only marked tradeable (`side` set) if:
      - n >= min_n
      - |deviation| >= min_deviation_pp
      - fee_adjusted_edge > 0

    The caller decides what rows to pass in — typically the output of a
    bin-aggregation SQL query over PIT-priced resolved markets.
    """
    bins: list[CalibrationBin] = []
    for bin_low, bin_high, n, yes_count in rows:
        if n == 0:
            continue
        actual = yes_count / n
        implied = (bin_low + bin_high) / 2 / 100
        ci_low, ci_high = _wilson_ci(yes_count, n)
        edge = fee_adjusted_edge(implied, actual)
        side = ""
        if (
            n >= min_n
            and abs(actual - implied) * 100 >= min_deviation_pp
            and edge > 0
        ):
            side = trade_side(implied, actual)
        bins.append(
            CalibrationBin(
                bin_low=int(bin_low),
                bin_high=int(bin_high),
                n=int(n),
                yes_count=int(yes_count),
                actual_rate=actual,
                ci_low=ci_low,
                ci_high=ci_high,
                fee_adj_edge=edge,
                side=side,
            )
        )
    return bins


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p_hat = successes / n
    denom = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denom
    # sqrt((p_hat(1-p_hat) + z²/4n) / n)
    radicand = (p_hat * (1 - p_hat) + z**2 / (4 * n)) / n
    spread = z * (radicand**0.5) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def _category_scopes() -> tuple[str, ...]:
    return (
        "aggregate",
        "sports",
        "crypto",
        "financial",
        "weather",
        "economics",
        "politics",
        "other",
    )


def build_calibration_from_duckdb(
    con,
    *,
    data_window_start: str,
    data_window_end: str,
    min_volume: int,
    built_at: datetime | None = None,
) -> Calibration:
    """Build a full calibration from an already-prepared `pit_final` table.

    The caller is responsible for creating `pit_final` (see
    `scripts/build_calibration_curve.py` for the canonical recipe). This
    function only does the aggregation and bin construction.
    """
    curves: dict[str, list[CalibrationBin]] = {}
    for scope in _category_scopes():
        where = "1=1" if scope == "aggregate" else f"category = '{scope}'"
        rows = con.execute(
            f"""
            SELECT
                FLOOR(pit_price / 5) * 5 AS bin_low,
                FLOOR(pit_price / 5) * 5 + 5 AS bin_high,
                COUNT(*) AS n,
                SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) AS yes_count
            FROM pit_final
            WHERE {where}
              AND pit_price BETWEEN 1 AND 99
            GROUP BY bin_low, bin_high
            ORDER BY bin_low
            """
        ).fetchall()
        if not rows:
            continue
        curves[scope] = build_bins_from_rows(rows)
    return Calibration(
        built_at=built_at or datetime.now(timezone.utc),
        data_window_start=data_window_start,
        data_window_end=data_window_end,
        min_volume=min_volume,
        curves=curves,
    )
