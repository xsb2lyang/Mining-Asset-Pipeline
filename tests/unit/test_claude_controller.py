"""Mock-only tests for the embedded structured-output controller."""
from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from tests.unit.test_agent_tools import CountingRunner

from mining_asset_pipeline.agent.claude_controller import ClaudeAssetController
from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus
from mining_asset_pipeline.agent.tools import AgentTools


ROOT = Path(__file__).resolve().parents[2]


def response(payload):
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


def brief():
    return {"object_name": "red mug", "category": "cup", "sam3_prompts": ["a red ceramic mug with handle"], "material": "ceramic", "is_open_container": True, "is_slender": False, "is_fast_or_small": False, "is_fixed": False, "target_task": "", "robot_constraints": "", "assumptions": ["single rigid body"]}


def visual():
    return {"action": "accept", "summary": "matches", "findings": [], "candidate_index": None, "prompt": None, "seed": None, "reason": None}


def spec():
    return {
        "schema_version": 1,
        "asset": {"prompt": "a red ceramic mug", "category": "cup", "target_task": "", "robot_constraints": ""},
        "material": {"profile": "ceramic", "density_kg_m3": 2500, "static_friction": 0.5, "dynamic_friction": 0.4, "restitution": 0.05, "friction_combine_mode": "average", "restitution_combine_mode": "max"},
        "mass": {"mode": "density", "density_kg_m3": 2500, "mass_kg": None},
        "collision": {"profile": "open_container", "enabled": True, "approximation": "sdf", "fallback_approximation": "convexDecomposition", "production_strategy": "compound_colliders"},
        "rigid_body": {"enabled": True, "enable_ccd": False, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0},
        "assumptions": ["friction is a prior"], "rationale": "ceramic open container",
    }


class NoAppearanceRunner(CountingRunner):
    def stream(self, name, command, cwd, log_path, env=None):
        result = super().stream(name, command, cwd, log_path, env)
        if name.startswith("sam3d_seed_"):
            out = Path(command[command.index("--out-dir") + 1])
            document = {"asset": {"version": "2.0"}, "accessors": [{"count": 3}, {"count": 3}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
            payload = json.dumps(document, separators=(",", ":")).encode()
            payload += b" " * ((4 - len(payload) % 4) % 4)
            (out / "mug.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(payload)) + struct.pack("<I4s", len(payload), b"JSON") + payload)
        return result


class ClaudeControllerTests(unittest.TestCase):
    def _setup(self, temp_root: Path):
        image = temp_root / "mug.png"
        Image.new("RGB", (20, 20), "red").save(image)
        isaac = temp_root / "isaac"
        isaac.mkdir()
        (isaac / "python.sh").write_text("#!/bin/sh\n")
        runner = CountingRunner()
        tools = AgentTools(ROOT, temp_root / "outputs", runner=runner)
        return image, isaac, runner, tools

    def test_structured_claude_path_uses_images_and_finishes_agent_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            client.messages.create.side_effect = [response(brief()), response(visual()), response(visual()), response(spec()), response({"accepted": True, "summary": "safe", "findings": []})]
            controller = ClaudeAssetController(tools, client, max_calls=8)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = controller.run_new(image, AssetRequest("红色杯子", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(manifest["quality"], "agent_reviewed")
            self.assertEqual(client.messages.create.call_count, 5)
            visual_call = client.messages.create.call_args_list[1].kwargs
            self.assertIn("output_config", visual_call)
            blocks = visual_call["messages"][0]["content"]
            self.assertGreaterEqual(sum(block.get("type") == "image" for block in blocks), 2)

    def test_no_client_specialized_profile_delivers_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            controller = ClaudeAssetController(tools, None)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = controller.run_new(image, AssetRequest("a red ceramic mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(manifest["quality"], "degraded")

    def test_no_client_generic_profile_blocks_final_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            controller = ClaudeAssetController(tools, None)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = controller.run_new(image, AssetRequest("an unknown thing"))
            self.assertEqual(manifest["status"], AssetStatus.BLOCKED.value)
            self.assertEqual(list((tools.store.root(manifest["asset_id"]) / "final").glob("*.usd")), [])

    def test_resume_skips_completed_gpu_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, isaac, runner, tools = self._setup(root)
            created = tools.create(image, AssetRequest("a red ceramic mug", "cup"), controller="embedded_claude_api")
            asset_id = created["asset_id"]
            tools.record_brief(asset_id, brief())
            tools.run_sam3(asset_id, brief()["sam3_prompts"][0])
            tools.run_sam3d(asset_id, 42)
            tools.record_visual_review(asset_id, {"action": "accept", "summary": "matches", "findings": []})
            sam3_calls = runner.calls["sam3"]
            sam3d_calls = runner.calls["sam3d_seed_42"]
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, None).run(asset_id)
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(runner.calls["sam3"], sam3_calls)
            self.assertEqual(runner.calls["sam3d_seed_42"], sam3d_calls)

    def test_api_timeout_uses_specialized_degraded_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            client.messages.create.side_effect = TimeoutError("network timeout")
            controller = ClaudeAssetController(tools, client)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = controller.run_new(image, AssetRequest("a red ceramic mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(manifest["quality"], "degraded")
            report = tools.store.read_json(tools.store.root(manifest["asset_id"]) / "final" / "asset_report.json")
            self.assertIn("TimeoutError", report["fallback_reason"])

    def test_invalid_structured_input_response_uses_audited_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(text="not JSON")])
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, client).run_new(image, AssetRequest("a red ceramic mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(manifest["quality"], "degraded")
            report = tools.store.read_json(tools.store.root(manifest["asset_id"]) / "final" / "asset_report.json")
            self.assertIn("JSONDecodeError", report["fallback_reason"])

    def test_explicit_visual_block_cannot_be_bypassed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            blocked = {"action": "block", "summary": "wrong subject", "findings": [{"severity": "error", "code": "wrong_subject", "message": "mask selects background"}], "candidate_index": None, "prompt": None, "seed": None, "reason": "new input required"}
            client.messages.create.side_effect = [response(brief()), response(blocked)]
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, client).run_new(image, AssetRequest("red mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.BLOCKED.value)
            self.assertFalse((tools.store.root(manifest["asset_id"]) / "physics" / "visual.usd").exists())
            resumed = ClaudeAssetController(tools, None).run(manifest["asset_id"])
            self.assertEqual(resumed["status"], AssetStatus.BLOCKED.value)
            self.assertEqual(list((tools.store.root(manifest["asset_id"]) / "final").glob("*.usd")), [])

    def test_visual_repair_then_api_failure_blocks_instead_of_degrading(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            rerun = {"action": "rerun_sam3d", "summary": "wrong shape", "findings": [{"severity": "error", "code": "wrong_shape", "message": "handle is missing"}], "candidate_index": None, "prompt": None, "seed": 43, "reason": None}
            client.messages.create.side_effect = [response(brief()), response(visual()), response(rerun), TimeoutError("network lost")]
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, client).run_new(image, AssetRequest("red mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.BLOCKED.value)
            self.assertEqual(list((tools.store.root(manifest["asset_id"]) / "final").glob("*.usd")), [])

    def test_visual_rerun_executes_requested_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, runner, tools = self._setup(Path(temp))
            client = MagicMock()
            rerun = {"action": "rerun_sam3d", "summary": "try another reconstruction", "findings": [{"severity": "error", "code": "wrong_shape", "message": "shape is incomplete"}], "candidate_index": None, "prompt": None, "seed": 43, "reason": None}
            client.messages.create.side_effect = [
                response(brief()), response(visual()), response(rerun), response(visual()),
                response(spec()), response({"accepted": True, "summary": "safe", "findings": []}),
            ]
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, client).run_new(image, AssetRequest("red mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.COMPLETE.value)
            self.assertEqual(runner.calls["sam3d_seed_42"], 1)
            self.assertEqual(runner.calls["sam3d_seed_43"], 1)
            self.assertEqual(runner.calls["sam3d_seed_44"], 0)

    def test_manifest_budget_cannot_be_increased_by_controller_resume_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image, isaac, _runner, tools = self._setup(Path(temp))
            client = MagicMock()
            client.messages.create.side_effect = [response(brief())]
            controller = ClaudeAssetController(tools, client, max_calls=1)
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = controller.run_new(image, AssetRequest("red ceramic mug", "cup"))
            self.assertEqual(client.messages.create.call_count, 1)
            self.assertEqual(manifest["budget"]["max_llm_calls"], 1)
            self.assertEqual(manifest["budget"]["llm_calls_used"], 1)

    def test_no_appearance_cannot_be_delivered_by_degraded_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "mug.png"
            Image.new("RGB", (20, 20), "red").save(image)
            isaac = root / "isaac"
            isaac.mkdir()
            (isaac / "python.sh").write_text("#!/bin/sh\n")
            tools = AgentTools(ROOT, root / "outputs", runner=NoAppearanceRunner())
            with patch.dict(os.environ, {"ISAAC_SIM_PATH": str(isaac)}):
                manifest = ClaudeAssetController(tools, None).run_new(image, AssetRequest("a red ceramic mug", "cup"))
            self.assertEqual(manifest["status"], AssetStatus.BLOCKED.value)
            self.assertEqual(list((tools.store.root(manifest["asset_id"]) / "final").glob("*.usd")), [])


if __name__ == "__main__":
    unittest.main()
