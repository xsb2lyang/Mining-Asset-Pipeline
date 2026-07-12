"""Deprecated compatibility entry point; use scripts/apply_physics_material.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[4] / "src/mining_asset_pipeline/usd/apply_physics_material.py"), run_name="__main__")
