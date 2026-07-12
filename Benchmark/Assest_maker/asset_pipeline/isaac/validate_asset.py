"""Deprecated compatibility entry point; use scripts/validate_asset.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[4] / "src/mining_asset_pipeline/usd/validate_asset.py"), run_name="__main__")
