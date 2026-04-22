"""Streamlit dashboard entry point.

Run with:
    streamlit run scripts/dashboard.py

By default the script loads ``data/paper/manifest.toml`` (relative to the
repo root). Set ``PROSPECTOR_MANIFEST`` to point at a different manifest —
useful for smoke-testing against a copy of the production DB before
cutover.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from prospector.dashboard import (
    inject_theme,
    load_tick_history,
    render_strategy,
)
from prospector.manifest import load_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "data" / "paper" / "manifest.toml"


def main() -> None:
    st.set_page_config(page_title="Prospector paper trading", layout="wide")
    inject_theme()

    manifest_path = Path(os.environ.get("PROSPECTOR_MANIFEST", DEFAULT_MANIFEST))
    if not manifest_path.exists():
        st.error(f"Manifest not found: {manifest_path}")
        return

    entries = [e for e in load_manifest(manifest_path) if e.enabled]

    st.markdown(
        """
        <div style="margin-bottom:1.5rem;">
            <div class="qt-eyebrow">Prospector</div>
            <div class="qt-display">Paper trading</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not entries:
        st.info("No enabled strategies in the manifest.")
        return

    # Freshness strip — last tick per strategy.
    header = st.columns(len(entries), gap="small")
    for col, entry in zip(header, entries):
        ticks = load_tick_history(entry.log_dir, limit=1)
        last = ticks[-1] if ticks else None
        last_str = (
            last.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            if last and last.timestamp
            else "—"
        )
        col.markdown(
            f"""
            <div class="qt-kpi">
                <div class="qt-kpi-label">{entry.display_name} · last tick</div>
                <div class="qt-kpi-value">{last_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    for entry in entries:
        st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
        render_strategy(entry)


main()
