"""Launch the local human-in-the-loop asset-quality review UI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.web import main

raise SystemExit(main())
