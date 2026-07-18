"""Contract tests for the shared whitelisted AgentTools layer."""
from __future__ import annotations

import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import numpy as np

from tests.unit.test_asset_agent import FakeRunner

from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus
from mining_asset_pipeline.agent.physics_agents import PhysicsAuthorAgent
from mining_asset_pipeline.agent.policy import RuleBasedPolicy
from mining_asset_pipeline.agent.tools import AgentTools
from mining_asset_pipeline.agent.storage import asset_filename_stem


ROOT = Path(__file__).resolve().parents[2]


class CountingRunner(FakeRunner):
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def stream(self, name, command, cwd, log_path, env=None):
        self.calls[name] += 1
        return super().stream(name, command, cwd, log_path, env)


class AgentToolsTests(unittest.TestCase):
    def test_semantic_asset_filename_is_portable(self) -> None:
        self.assertEqual(asset_filename_stem("a Paper Tube"), "paper_tube")
        self.assertEqual(asset_filename_stem("矿用纸筒"), "矿用纸筒")
        self.assertEqual(asset_filename_stem("CON"), "asset_con")
        self.assertLessEqual(len(asset_filename_stem("x" * 100)), 64)

    def _create(self, temp_root: Path, runner=None) -> tuple[AgentTools, str]:
        image = temp_root / "mug.png"
        Image.new("RGB", (20, 20), "red").save(image)
        tools = AgentTools(ROOT, temp_root / "outputs", runner=runner or FakeRunner())
        result = tools.create(image, AssetRequest("a red ceramic mug", "cup"), controller="external_skill")
        return tools, result["asset_id"]

    def test_v3_bundle_and_path_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, asset_id = self._create(root)
            manifest = tools.store.manifest(asset_id)
            self.assertEqual(manifest["schema_version"], 3)
            self.assertEqual(manifest["quality"], "pending")
            self.assertTrue((tools.store.root(asset_id) / "agent" / "decisions").is_dir())
            second = tools.create(root / "mug.png", AssetRequest("a red ceramic mug", "cup"), controller="external_skill")
            self.assertNotEqual(asset_id, second["asset_id"])
            with self.assertRaises(ValueError):
                tools.status("../outside")

    def test_tools_read_the_same_safe_local_paths_as_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            (repo / "environments").mkdir(parents=True)
            (repo / "environments" / "local.env").write_text(
                'export SAM3_CHECKPOINT_DIR="${REPO_ROOT}/local/sam3"\n'
                'export SAM3D_CHECKPOINT_DIR="${REPO_ROOT}/local/sam3d"\n'
                'export ISAAC_SIM_PATH="${REPO_ROOT}/local/isaac"\n'
                'export SAM3_ENV=sam3-local\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                tools = AgentTools(repo, repo / "outputs", runner=FakeRunner())
            self.assertEqual(tools.sam3_env, "sam3-local")
            self.assertEqual(tools.sam3_checkpoint, repo / "local" / "sam3" / "sam3.pt")
            self.assertEqual(tools.sam3d_checkpoint, repo / "local" / "sam3d" / "pipeline.yaml")
            self.assertEqual(tools.isaac_sim_path, repo / "local" / "isaac")

    def test_source_image_hash_is_verified_before_resume_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tools, asset_id = self._create(Path(temp))
            source = tools.store.source_path(asset_id)
            source.write_bytes(source.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "source image hash mismatch"):
                tools.store.source_path(asset_id)
            brief = RuleBasedPolicy().asset_brief(AssetRequest("a red ceramic mug", "cup"))
            tools.record_brief(asset_id, brief.to_dict())
            with self.assertRaisesRegex(ValueError, "source image hash mismatch"):
                tools.run_sam3(asset_id, brief.sam3_prompts[0])

    def test_sam_attempts_are_idempotent_and_seed_is_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runner = CountingRunner()
            tools, asset_id = self._create(Path(temp), runner)
            brief = RuleBasedPolicy().asset_brief(AssetRequest("a red ceramic mug", "cup"))
            tools.record_brief(asset_id, brief.to_dict())
            first = tools.run_sam3(asset_id, brief.sam3_prompts[0])
            second = tools.run_sam3(asset_id, brief.sam3_prompts[0])
            self.assertTrue(first["ok"])
            self.assertTrue(second["reused"])
            self.assertEqual(runner.calls["sam3"], 1)
            tools.run_sam3d(asset_id, 42)
            tools.run_sam3d(asset_id, 42)
            self.assertEqual(runner.calls["sam3d_seed_42"], 1)
            mask_path = tools._require_artifact(asset_id, "sam3_mask")
            with np.load(mask_path, allow_pickle=False) as data:
                values = {name: data[name] for name in data.files}
            values["mask"] = np.roll(values["mask"], 1, axis=0)
            values["candidate_masks"] = values["mask"][None, ...]
            np.savez(mask_path, **values)
            tools.store.set_artifact(asset_id, "sam3_mask", mask_path)
            tools.run_sam3d(asset_id, 42)
            self.assertEqual(runner.calls["sam3d_seed_42"], 2)
            with self.assertRaises(ValueError):
                tools.run_sam3d(asset_id, 99)

    def test_full_whitelist_flow_finalizes_only_after_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, asset_id = self._create(root)
            request = AssetRequest("a red ceramic mug", "cup")
            policy = RuleBasedPolicy()
            brief = policy.asset_brief(request)
            tools.record_brief(asset_id, brief.to_dict())
            tools.run_sam3(asset_id, brief.sam3_prompts[0])
            tools.run_sam3d(asset_id, 42)
            tools.record_visual_review(asset_id, {"action": "accept", "summary": "Shape and opening match.", "findings": []})
            materials = {path.stem: __import__("yaml").safe_load(path.read_text()) for path in (ROOT / "configs" / "materials").glob("*.yaml")}
            collisions = {(__import__("yaml").safe_load(path.read_text())["name"]): __import__("yaml").safe_load(path.read_text()) for path in (ROOT / "configs" / "collision_profiles").glob("*.yaml")}
            spec = PhysicsAuthorAgent().initial_spec(request, policy.physics_proposal(request, brief), materials, collisions)
            tools.submit_physics(asset_id, spec)
            semantic = {"accepted": True, "summary": "safe", "findings": []}
            self.assertTrue(tools.check_physics(asset_id, semantic)["ok"])
            isaac = root / "isaac"
            isaac.mkdir()
            (isaac / "python.sh").write_text("#!/bin/sh\n")
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                tools.author_usd(asset_id)
            ready = tools._require_artifact(asset_id, "simulation_ready_usd")
            original_ready = ready.read_bytes()
            ready.write_bytes(original_ready + b"tampered")
            with self.assertRaises(ValueError):
                tools.finalize(asset_id, quality="agent_reviewed")
            ready.write_bytes(original_ready)
            completed = tools.finalize(asset_id, quality="agent_reviewed")
            self.assertTrue(completed["ok"])
            self.assertEqual(tools.store.manifest(asset_id)["status"], AssetStatus.COMPLETE.value)
            self.assertTrue((tools.store.root(asset_id) / "final" / "asset_report.json").is_file())
            # An Agent or CLI may retry a request after losing the first JSON
            # response. Exact successful actions must be harmless at any later phase.
            self.assertTrue(tools.run_sam3(asset_id, brief.sam3_prompts[0])["reused"])
            self.assertTrue(tools.select_mask(asset_id, 0)["reused"])
            self.assertTrue(tools.run_sam3d(asset_id, 42)["reused"])
            self.assertTrue(tools.record_visual_review(asset_id, {"action": "accept", "summary": "Shape and opening match.", "findings": []})["reused"])
            self.assertTrue(tools.submit_physics(asset_id, spec)["reused"])
            self.assertTrue(tools.check_physics(asset_id, semantic)["reused"])
            self.assertTrue(tools.author_usd(asset_id)["reused"])
            self.assertTrue(tools.finalize(asset_id, quality="agent_reviewed")["reused"])
            semantic = tools.store.artifact_path(asset_id, "final_usd")
            self.assertEqual(semantic.name, "red_ceramic_mug.usd")
            # A completed manifest-v3 bundle with the former fixed filename is
            # migrated on an idempotent finalize retry.
            legacy = semantic.with_name("asset.usd")
            semantic.replace(legacy)
            tools.store.set_artifact(asset_id, "final_usd", legacy)
            migrated = tools.finalize(asset_id, quality="agent_reviewed")
            self.assertTrue(migrated["reused"])
            self.assertEqual(tools.store.artifact_path(asset_id, "final_usd").name, "red_ceramic_mug.usd")
            report = tools.store.read_json(tools.store.artifact_path(asset_id, "final_report"))
            self.assertEqual(report["final_filename"], "red_ceramic_mug.usd")

    def test_finalize_rejects_missing_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tools, asset_id = self._create(Path(temp))
            with self.assertRaises(ValueError):
                tools.finalize(asset_id)

    def test_old_manifest_is_read_only_and_illegal_phase_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, asset_id = self._create(root)
            with self.assertRaises(ValueError):
                tools.run_sam3(asset_id, "a mug")
            manifest_path = tools.store.root(asset_id) / "manifest.json"
            manifest = tools.store.read_json(manifest_path)
            manifest["schema_version"] = 2
            tools.store.write_json(manifest_path, manifest)
            self.assertEqual(tools.status(asset_id)["schema_version"], 2)
            with self.assertRaises(ValueError):
                tools.record_brief(asset_id, RuleBasedPolicy().asset_brief(AssetRequest("mug")).to_dict())

    def test_canonical_brief_payload_is_registered_instead_of_false_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tools, asset_id = self._create(Path(temp))
            brief_payload = RuleBasedPolicy().asset_brief(AssetRequest("a mug", "cup")).to_dict()
            canonical = tools.store.root(asset_id) / "agent" / "asset_brief.json"
            tools.store.write_json(canonical, brief_payload)
            result = tools.record_brief(asset_id, brief_payload)
            self.assertEqual(result["phase"], "segmentation")
            self.assertEqual(tools.store.manifest(asset_id)["artifacts"]["asset_brief"], "agent/asset_brief.json")


if __name__ == "__main__":
    unittest.main()
