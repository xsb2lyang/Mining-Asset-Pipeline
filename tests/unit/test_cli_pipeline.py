"""Smoke tests for the unattended workflow and command-line arguments."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus  # noqa: E402
from mining_asset_pipeline.agent.workflow import AssetWorkflow  # noqa: E402
from tests.unit.test_asset_agent import FakeRunner  # noqa: E402


def _stub_isaac(temp_root: Path) -> Path:
    isaac = temp_root / "isaac"
    isaac.mkdir()
    (isaac / "python.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return isaac


class UnattendedFlowTests(unittest.TestCase):
    def test_unattended_flow_produces_final_asset_usd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            image = temp_root / "red_mug.jpg"
            Image.new("RGB", (20, 20), "red").save(image)
            isaac = _stub_isaac(temp_root)

            workflow = AssetWorkflow(ROOT, temp_root / "outputs", runner=FakeRunner())
            asset_id = workflow.create_asset(image, AssetRequest(prompt="red ceramic mug", asset_category="cup"))
            visual = workflow.run_visual(asset_id)
            self.assertEqual(visual["status"], AssetStatus.PHYSICS_REVIEW_RUNNING.value)

            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = workflow.run_physics_pipeline(asset_id)

            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            final_usd = workflow.store.artifact_path(asset_id, "final_usd")
            self.assertTrue(final_usd.is_file())
            self.assertEqual(final_usd.name, "red_ceramic_mug.usd")

    def test_blocked_after_three_failed_review_rounds(self) -> None:
        """Force BLOCKED by pinning the author's initial spec and stubbing revise()
        so the Author/Critic loop never satisfies the critic."""
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            image = temp_root / "open_container.jpg"
            Image.new("RGB", (20, 20), "white").save(image)
            isaac = _stub_isaac(temp_root)

            workflow = AssetWorkflow(ROOT, temp_root / "outputs", runner=FakeRunner())
            asset_id = workflow.create_asset(image, AssetRequest(prompt="open cup", asset_category="open_container"))
            visual = workflow.run_visual(asset_id)
            self.assertEqual(visual["status"], AssetStatus.PHYSICS_REVIEW_RUNNING.value)

            def stuck_initial(req, proposal, materials, collisions):
                return {
                    "schema_version": 1,
                    "asset": {"prompt": req.prompt},
                    "material": materials["ceramic"],
                    "collision": {"approximation": "convexHull", "preferred_approximation": "convexHull"},
                    "mass": {"mode": "density", "density_kg_m3": 2500},
                    "rigid_body": {"enabled": True, "enable_ccd": False, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0},
                }

            workflow.physics_author.initial_spec = stuck_initial
            workflow.physics_author.revise = lambda spec, findings: spec  # type: ignore[assignment]

            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = workflow.run_physics_pipeline(asset_id)

            self.assertEqual(manifest["status"], AssetStatus.BLOCKED.value)
            self.assertEqual(list((workflow.store.root(asset_id) / "final").glob("*.usd")), [])
            review_paths = sorted((workflow.store.root(asset_id) / "physics").glob("physics_review_*.json"))
            self.assertGreaterEqual(len(review_paths), 1)
            any_rejected = any(
                not json.loads(p.read_text(encoding="utf-8")).get("accepted") for p in review_paths
            )
            self.assertTrue(any_rejected)


class CliArgparseTests(unittest.TestCase):
    def test_help_exits_cleanly(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_pipeline.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--image", result.stdout)
        self.assertIn("--prompt", result.stdout)
        self.assertIn("--isaac-sim-path", result.stdout)
        self.assertIn("--resume", result.stdout)
        self.assertIn("--model", result.stdout)
        self.assertIn("--max-llm-calls", result.stdout)
        self.assertNotIn("--rewrite-prompt", result.stdout)
        self.assertNotIn("--use-llm-critic", result.stdout)
        self.assertNotIn("--anthropic-api-key", result.stdout)

    def test_missing_image_exits_with_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            isaac = _stub_isaac(temp_root)
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "run_pipeline.py"),
                    "--image", "/nonexistent/red_mug.jpg",
                    "--prompt", "a red mug",
                    "--isaac-sim-path", str(isaac),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("--image not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
