from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from prospector.manifest import StrategyEntry, load_manifest


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "manifest.toml"
    path.write_text(textwrap.dedent(body))
    return path


def test_load_manifest_resolves_paths_and_preserves_order(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        """
        [[strategy]]
        name = "pm_underwriting"
        display_name = "PM Underwriting"
        schema = "kalshi_binary"
        portfolio_db = "pm_underwriting/portfolio.db"
        log_dir = "pm_underwriting/logs"
        launchd_label = "com.prospector.paper-trade"
        enabled = true
        """,
    )

    entries = load_manifest(manifest)

    assert entries == [
        StrategyEntry(
            name="pm_underwriting",
            display_name="PM Underwriting",
            schema="kalshi_binary",
            portfolio_db=(tmp_path / "pm_underwriting" / "portfolio.db").resolve(),
            log_dir=(tmp_path / "pm_underwriting" / "logs").resolve(),
            launchd_label="com.prospector.paper-trade",
            enabled=True,
        )
    ]


def test_load_manifest_rejects_unknown_schema(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        """
        [[strategy]]
        name = "mystery"
        display_name = "Mystery"
        schema = "crypto_perp"
        portfolio_db = "mystery/portfolio.db"
        log_dir = "mystery/logs"
        launchd_label = "com.example"
        enabled = true
        """,
    )
    with pytest.raises(ValueError, match="unsupported schema"):
        load_manifest(manifest)


def test_load_manifest_rejects_duplicate_names(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        """
        [[strategy]]
        name = "dup"
        display_name = "A"
        schema = "kalshi_binary"
        portfolio_db = "a/portfolio.db"
        log_dir = "a/logs"
        launchd_label = "com.a"
        enabled = true

        [[strategy]]
        name = "dup"
        display_name = "B"
        schema = "kalshi_binary"
        portfolio_db = "b/portfolio.db"
        log_dir = "b/logs"
        launchd_label = "com.b"
        enabled = false
        """,
    )
    with pytest.raises(ValueError, match="duplicate strategy name"):
        load_manifest(manifest)


def test_load_manifest_missing_required_field(tmp_path: Path) -> None:
    manifest = _write(
        tmp_path,
        """
        [[strategy]]
        name = "incomplete"
        display_name = "Incomplete"
        schema = "kalshi_binary"
        portfolio_db = "x/portfolio.db"
        log_dir = "x/logs"
        launchd_label = "com.x"
        """,
    )
    with pytest.raises(KeyError, match="enabled"):
        load_manifest(manifest)
