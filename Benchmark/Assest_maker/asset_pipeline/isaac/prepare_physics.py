"""Deprecated compatibility entry point; use scripts/prepare_physics.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[4] / "src/mining_asset_pipeline/usd/prepare_physics.py"), run_name="__main__")
