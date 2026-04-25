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
    render_comparison,
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
        <div style="margin-bottom:1rem; display:flex; align-items:baseline; gap:0.6rem;">
            <div class="qt-eyebrow">Prospector</div>
            <div class="qt-eyebrow" style="color:var(--qt-text);">· Paper trading</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not entries:
        st.info("No enabled strategies in the manifest.")
        return

    # Single strategy → render directly (no tab chrome). Two or more →
    # top-level tabs with a "Compare" tab first; per-strategy tabs after.
    if len(entries) == 1:
        render_strategy(entries[0])
        return

    tab_labels = ["Compare", *[e.display_name for e in entries]]
    tabs = st.tabs(tab_labels)
    with tabs[0]:
        render_comparison(entries)
    for tab, entry in zip(tabs[1:], entries):
        with tab:
            render_strategy(entry)


main()
