"""Deprecated compatibility entry point; use scripts/convert_to_usd.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[4] / "src/mining_asset_pipeline/usd/convert_glb_to_usd.py"), run_name="__main__")
