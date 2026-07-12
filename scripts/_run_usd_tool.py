"""Shared launcher for source-tree USD tools.

The project uses Isaac Sim's Python executable to run these scripts, so this
launcher intentionally avoids importing Isaac Sim itself.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def run_usd_tool(filename: str) -> None:
    root = Path(__file__).resolve().parents[1]
    tool = root / "src" / "mining_asset_pipeline" / "usd" / filename
    runpy.run_path(str(tool), run_name="__main__")
