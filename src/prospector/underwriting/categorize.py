"""Map a Kalshi event_ticker to a strategy category.

The same category taxonomy is used by the offline calibration builder (SQL) and
by the live market scanner (Python). `CATEGORY_PREFIXES` is the single source of
truth; `category_sql()` renders it as a DuckDB CASE expression; `classify()`
evaluates it in Python.
"""

from __future__ import annotations

CATEGORY_PREFIXES: dict[str, tuple[str, ...]] = {
    "sports": (
        "KXMVESPORTS",
        "KXMVENFL",
        "KXMVENBA",
        "KXNCAA",
        "KXNFLGAME",
        "KXNFL",
        "KXNBA",
    ),
    "crypto": (
        "KXBTC",
        "KXETH",
        "KXDOGE",
        "KXXRP",
        "KXSOL",
        "KXSHIBA",
    ),
    "financial": (
        "KXNASDAQ",
        "KXINX",
        "NASDAQ",
        "INX",
    ),
    "weather": (
        "KXCITIES",
        "HIGH",
        "LOW",
    ),
    "economics": (
        "CPI",
        "FED",
        "KXFED",
        "GDP",
    ),
    "politics": (
        "PRES",
        "SENATE",
        "HOUSE",
        "KXGOV",
        "KXMAYOR",
    ),
}

CATEGORY_SUBSTRINGS: dict[str, tuple[str, ...]] = {
    "financial": ("USDJPY", "EURUSD"),
}


def classify(event_ticker: str) -> str:
    """Return the category label for an event_ticker, or 'other' if unmatched."""
    if not event_ticker:
        return "other"
    for category, prefixes in CATEGORY_PREFIXES.items():
        if any(event_ticker.startswith(p) for p in prefixes):
            return category
    for category, needles in CATEGORY_SUBSTRINGS.items():
        if any(n in event_ticker for n in needles):
            return category
    return "other"


def category_sql(column: str = "event_ticker") -> str:
    """Render the category taxonomy as a DuckDB CASE expression."""
    lines = ["CASE"]
    # Emit prefix rules first (matches `classify()` precedence), then substrings.
    for category, prefixes in CATEGORY_PREFIXES.items():
        conds = " OR ".join(f"{column} LIKE '{p}%'" for p in prefixes)
        substrs = CATEGORY_SUBSTRINGS.get(category, ())
        if substrs:
            conds += " OR " + " OR ".join(f"{column} LIKE '%{s}%'" for s in substrs)
        lines.append(f"    WHEN {conds} THEN '{category}'")
    # Substrings for categories that had no prefix rules (none today, but
    # guard against that case for completeness).
    for category, substrs in CATEGORY_SUBSTRINGS.items():
        if category in CATEGORY_PREFIXES:
            continue
        conds = " OR ".join(f"{column} LIKE '%{s}%'" for s in substrs)
        lines.append(f"    WHEN {conds} THEN '{category}'")
    lines.append("    ELSE 'other'")
    lines.append("END")
    return "\n".join(lines)
