"""Strategy manifest loader.

The manifest (``data/paper/manifest.toml``) is the list of active strategies
the dashboard renders. Paper-trading daemons don't consult it — each daemon
owns its own portfolio DB — so the manifest is purely a discovery index.

Relative paths in the file are resolved against the manifest's directory so
the same manifest works whether invoked from the repo root or elsewhere.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SCHEMAS = frozenset({"kalshi_binary"})


@dataclass(frozen=True)
class StrategyEntry:
    name: str
    display_name: str
    schema: str
    portfolio_db: Path
    log_dir: Path
    launchd_label: str
    enabled: bool


def load_manifest(path: str | Path) -> list[StrategyEntry]:
    """Parse ``manifest.toml`` and return its strategies in file order.

    Raises ``ValueError`` if an entry references an unknown schema or a
    duplicate ``name``; raises ``KeyError`` if a required field is missing.
    """
    manifest_path = Path(path).resolve()
    base_dir = manifest_path.parent

    with manifest_path.open("rb") as fh:
        doc = tomllib.load(fh)

    raw_entries = doc.get("strategy", [])
    entries: list[StrategyEntry] = []
    seen: set[str] = set()

    for raw in raw_entries:
        name = raw["name"]
        if name in seen:
            raise ValueError(f"duplicate strategy name in manifest: {name}")
        seen.add(name)

        schema = raw["schema"]
        if schema not in SUPPORTED_SCHEMAS:
            raise ValueError(
                f"strategy {name!r}: unsupported schema {schema!r} "
                f"(supported: {sorted(SUPPORTED_SCHEMAS)})"
            )

        entries.append(
            StrategyEntry(
                name=name,
                display_name=raw["display_name"],
                schema=schema,
                portfolio_db=(base_dir / raw["portfolio_db"]).resolve(),
                log_dir=(base_dir / raw["log_dir"]).resolve(),
                launchd_label=raw["launchd_label"],
                enabled=bool(raw["enabled"]),
            )
        )

    return entries
