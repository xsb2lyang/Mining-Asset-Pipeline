"""Dependency-light tests for the unattended asset workflow."""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus, ToolResult
from mining_asset_pipeline.agent.inspection import inspect_sam3, select_sam3_candidate
from mining_asset_pipeline.agent.physics_agents import PhysicsAuthorAgent, PhysicsCriticAgent
from mining_asset_pipeline.agent.policy import RuleBasedPolicy
from mining_asset_pipeline.agent.storage import AssetStore
from mining_asset_pipeline.agent.workflow import AssetWorkflow


def _glb_bytes() -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 3}, {"count": 3}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 0}, "indices": 1}]}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    return struct.pack("<4sII", b"glTF", 2, 20 + len(payload)) + struct.pack("<I4s", len(payload), b"JSON") + payload


class FakeRunner:
    def run(self, name, command, cwd, log_path, env=None):
        return self.stream(name, command, cwd, log_path, env)

    def stream(self, name, command, cwd, log_path, env=None):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake tool completed\n", encoding="utf-8")
        def value(flag: str) -> Path:
            return Path(command[command.index(flag) + 1])
        if name == "sam3":
            out = value("--out-dir")
            out.mkdir(parents=True, exist_ok=True)
            mask = np.zeros((10, 10), dtype=np.uint8)
            mask[2:8, 2:8] = 1
            np.savez(out / "mask.npz", mask=mask, candidate_masks=mask[None, ...], boxes=np.array([[1, 1, 8, 8]]), scores=np.array([0.99]), best_index=0, selected_index=0, prompt=np.array("mug"))
            (out / "meta.json").write_text(json.dumps({"image_size": [10, 10]}), encoding="utf-8")
            Image.new("RGB", (10, 10), "red").save(out / "preview.png")
        elif name.startswith("sam3d_seed_"):
            out = value("--out-dir")
            out.mkdir(parents=True, exist_ok=True)
            (out / "mug.glb").write_bytes(_glb_bytes())
            (out / "summary.json").write_text("{}", encoding="utf-8")
            Image.new("RGB", (20, 20), "gray").save(out / "views.png")
        elif name == "inspect_physics":
            out = value("--out")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"status": "ok", "checks": {"has_mesh": True}}), encoding="utf-8")
        elif name in {"convert_to_usd", "prepare_physics", "apply_physics_material"}:
            out = value("--output")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("#usda 1.0\n", encoding="utf-8")
            if name == "apply_physics_material":
                value("--report").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        return ToolResult(returncode=0, command=command, log_path=str(log_path))


class InvalidMaskRunner(FakeRunner):
    def stream(self, name, command, cwd, log_path, env=None):
        result = super().stream(name, command, cwd, log_path, env)
        if name == "sam3":
            out = Path(command[command.index("--out-dir") + 1])
            mask = np.zeros((10, 10), dtype=np.uint8)
            np.savez(
                out / "mask.npz",
                mask=mask,
                candidate_masks=mask[None, ...],
                boxes=np.array([[0, 0, 1, 1]]),
                scores=np.array([0.99]),
                best_index=0,
                selected_index=0,
            )
        return result


class AssetStoreTests(unittest.TestCase):
    def test_bundle_isolated_and_transitions_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "input.png"
            Image.new("RGB", (4, 4)).save(image)
            store = AssetStore(root / "outputs")
            asset_id = store.create(image, AssetRequest(prompt="rock"))
            bundle = store.root(asset_id)
            self.assertEqual(store.manifest(asset_id)["schema_version"], 3)
            self.assertEqual(set(path.name for path in bundle.iterdir()), {"input", "agent", "visual", "physics", "final", "request.json", "manifest.json"})
            with self.assertRaises(ValueError):
                store.transition(asset_id, AssetStatus.COMPLETE, "skip")


class WorkflowTests(unittest.TestCase):
    def test_visual_checks_then_automatic_physics_review_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            image = temp_root / "red_mug.jpg"
            Image.new("RGB", (20, 20), "red").save(image)
            isaac = temp_root / "isaac"
            isaac.mkdir()
            (isaac / "python.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            workflow = AssetWorkflow(ROOT, temp_root / "outputs", runner=FakeRunner())
            asset_id = workflow.create_asset(image, AssetRequest(prompt="red ceramic mug", asset_category="cup"))
            visual = workflow.run_visual(asset_id)
            self.assertEqual(visual["status"], AssetStatus.PHYSICS_REVIEW_RUNNING.value)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                complete = workflow.run_physics_pipeline(asset_id)
            self.assertEqual(complete["status"], AssetStatus.COMPLETE.value)
            final_usd = workflow.store.artifact_path(asset_id, "final_usd")
            self.assertTrue(final_usd.is_file())
            self.assertNotEqual(final_usd.name, "asset.usd")
            self.assertFalse((workflow.store.root(asset_id) / "visual" / "review.json").exists())
            spec = (workflow.store.root(asset_id) / "physics" / "physics_spec.yaml").read_text(encoding="utf-8")
            self.assertIn("profile: ceramic", spec)
            self.assertIn("approximation: sdf", spec)
            review = workflow.store.read_json(workflow.store.root(asset_id) / "physics" / "physics_review_001.json")
            self.assertTrue(review["accepted"])
            for artifact in complete["artifacts"].values():
                self.assertFalse(Path(artifact).is_absolute())

    def test_failed_visual_checks_stop_before_physics_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "input.png"
            Image.new("RGB", (4, 4)).save(image)
            workflow = AssetWorkflow(ROOT, root / "outputs", runner=InvalidMaskRunner())
            asset_id = workflow.create_asset(image, AssetRequest(prompt="object"))
            manifest = workflow.run_visual(asset_id)
            self.assertEqual(manifest["status"], AssetStatus.FAILED.value)
            self.assertIn("SAM3 automatic checks failed", manifest["error"])
            self.assertFalse((workflow.store.root(asset_id) / "physics" / "physics_proposal.json").exists())

    def test_human_review_api_and_states_are_removed(self) -> None:
        self.assertFalse(hasattr(AssetWorkflow, "submit_review"))
        self.assertFalse(hasattr(AssetWorkflow, "begin_physics_review"))
        self.assertNotIn("review_required", {status.value for status in AssetStatus})
        self.assertNotIn("visual_approved", {status.value for status in AssetStatus})


class PolicyTests(unittest.TestCase):
    def test_mug_proposes_ceramic_open_container(self) -> None:
        proposal = RuleBasedPolicy().physics_proposal(AssetRequest(prompt="red ceramic mug"))
        self.assertEqual(proposal["material_profile"], "ceramic")
        self.assertEqual(proposal["collision_profile"], "open_container")


class PhysicsAgentTests(unittest.TestCase):
    def test_critic_rejects_sealing_a_container_and_author_repairs_it(self) -> None:
        materials = {"ceramic": {"density_kg_m3": 2500, "static_friction": 0.5, "dynamic_friction": 0.4, "restitution": 0.05}}
        collisions = {"open_container": {"preferred_approximation": "sdf"}}
        author = PhysicsAuthorAgent()
        spec = author.initial_spec(AssetRequest(prompt="ceramic mug"), {"material_profile": "ceramic", "collision_profile": "open_container"}, materials, collisions)
        spec["collision"]["approximation"] = "convexHull"
        critic = PhysicsCriticAgent()
        first_review = critic.review(spec)
        self.assertFalse(first_review.accepted)
        self.assertIn("collision.container_sealed", {item["code"] for item in first_review.findings})
        revised = author.revise(spec, first_review.findings)
        self.assertEqual(revised["collision"]["approximation"], "sdf")
        self.assertTrue(critic.review(revised).accepted)

    def test_critic_rejects_nonfinite_values_unknown_profiles_and_container_hull(self) -> None:
        spec = {
            "schema_version": 1,
            "asset": {"prompt": "a ceramic mug", "category": "cup"},
            "material": {"profile": "invented", "density_kg_m3": float("nan"), "static_friction": float("nan"), "dynamic_friction": 0.4, "restitution": 0.1, "friction_combine_mode": "average", "restitution_combine_mode": "average"},
            "mass": {"mode": "density", "density_kg_m3": float("nan")},
            "collision": {"profile": "generic_solid", "enabled": True, "approximation": "convexHull"},
            "rigid_body": {"enabled": True, "enable_ccd": False, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0},
        }
        review = PhysicsCriticAgent().review(spec)
        self.assertFalse(review.accepted)
        codes = {item["code"] for item in review.findings}
        self.assertIn("material.unknown_profile", codes)
        self.assertIn("material.friction_order", codes)
        self.assertIn("mass.invalid", codes)
        self.assertIn("collision.container_sealed", codes)


class InspectionTests(unittest.TestCase):
    def test_alternate_sam3_candidate_can_be_selected_without_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "input.png"
            Image.new("RGB", (10, 10), "red").save(image)
            first = np.zeros((10, 10), dtype=np.uint8)
            second = np.zeros((10, 10), dtype=np.uint8)
            second[2:8, 2:8] = 1
            np.savez(root / "mask.npz", mask=first, candidate_masks=np.stack([first, second]), boxes=np.array([[0, 0, 1, 1], [2, 2, 8, 8]]), scores=np.array([0.9, 0.8]), best_index=0, selected_index=0)
            (root / "meta.json").write_text(json.dumps({"image_size": [10, 10]}), encoding="utf-8")
            report = inspect_sam3(root / "mask.npz", root / "meta.json")
            self.assertEqual(report["recommended_candidate_index"], 1)
            select_sam3_candidate(root / "mask.npz", root / "meta.json", image, 1)
            self.assertEqual(inspect_sam3(root / "mask.npz", root / "meta.json")["status"], "pass")


if __name__ == "__main__":
    unittest.main()
