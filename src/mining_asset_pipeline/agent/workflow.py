"""Durable orchestration for Loop 1 visual generation and USD handoff."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from .inspection import inspect_glb, inspect_sam3, select_sam3_candidate
from .models import AssetRequest, AssetStatus, ReviewDecision
from .policy import RuleBasedPolicy
from .runner import SubprocessToolRunner, ToolRunner, isaac_clean_environment
from .storage import AssetStore


class AssetWorkflow:
    def __init__(self, repo_root: Path, output_root: Path | None = None, runner: ToolRunner | None = None, policy: RuleBasedPolicy | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.store = AssetStore(output_root or self.repo_root / "outputs")
        self.runner = runner or SubprocessToolRunner()
        self.policy = policy or RuleBasedPolicy()
        self.sam3_env = os.environ.get("SAM3_ENV", "sam3")
        self.sam3d_env = os.environ.get("SAM3D_ENV", "sam3d-objects")

    def create_asset(self, source_image: Path, request: AssetRequest) -> str:
        return self.store.create(source_image, request)

    def run_visual(self, asset_id: str, revised_prompt: str = "", candidate_index: int | None = None) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        current = AssetStatus(manifest["status"])
        if current not in {AssetStatus.CREATED, AssetStatus.REVIEW_REQUIRED, AssetStatus.FAILED}:
            raise ValueError(f"Cannot run visual workflow while status is {current.value}")
        if current == AssetStatus.REVIEW_REQUIRED:
            self.store.archive_visual(asset_id)
        if current == AssetStatus.FAILED:
            self.store.transition(asset_id, AssetStatus.VISUAL_RUNNING, "Retrying failed visual workflow")
        else:
            self.store.transition(asset_id, AssetStatus.VISUAL_RUNNING, "Starting visual generation")
        root = self.store.root(asset_id)
        request = AssetRequest(**self.store.read_json(root / "request.json"))
        prompt = revised_prompt.strip() or request.prompt
        source = root / manifest["source_image"]
        sam3_dir = root / "visual" / "sam3"
        sam3_command = ["conda", "run", "-n", self.sam3_env, "python", "scripts/run_sam3.py", "--image", str(source), "--prompt", prompt, "--out-dir", str(sam3_dir)]
        if candidate_index is not None:
            sam3_command += ["--candidate-index", str(candidate_index)]
        self._run_or_fail(asset_id, "sam3", sam3_command, root / "visual" / "logs" / "sam3.log")
        sam3_report = inspect_sam3(sam3_dir / "mask.npz", sam3_dir / "meta.json")
        alternative = sam3_report.get("recommended_candidate_index")
        if alternative is not None:
            select_sam3_candidate(sam3_dir / "mask.npz", sam3_dir / "meta.json", source, int(alternative))
            sam3_report = inspect_sam3(sam3_dir / "mask.npz", sam3_dir / "meta.json")
            sam3_report["automatic_action"] = f"selected_candidate_{alternative}"
        self.store.write_json(root / "visual" / "sam3_report.json", sam3_report)
        self.store.set_artifact(asset_id, "sam3_report", root / "visual" / "sam3_report.json")
        if sam3_report["status"] != "pass":
            self.store.transition(asset_id, AssetStatus.REVIEW_REQUIRED, "SAM3 output needs human review")
            return self.store.manifest(asset_id)

        sam3d_dir = root / "visual" / "sam3d"
        previous_report = root / "history"
        seed_start = 42
        if previous_report.is_dir():
            previous_geometry = sorted(previous_report.glob("visual_*/geometry_report.json"))
            if previous_geometry:
                seed_start = int(self.store.read_json(previous_geometry[-1]).get("seed", 41)) + 1
        glb_report: dict[str, Any] | None = None
        for seed in range(seed_start, seed_start + 3):
            command = [
                "conda", "run", "-n", self.sam3d_env, "python", "scripts/run_sam3d.py",
                "--image", str(source), "--mask-npz", str(sam3_dir / "mask.npz"),
                "--out-dir", str(sam3d_dir), "--seed", str(seed),
            ]
            self._run_or_fail(asset_id, f"sam3d_seed_{seed}", command, root / "visual" / "logs" / f"sam3d_seed_{seed}.log")
            glb_report = inspect_glb(sam3d_dir / "mug.glb")
            glb_report["seed"] = seed
            if glb_report["status"] == "pass":
                break
        assert glb_report is not None
        self.store.write_json(root / "visual" / "geometry_report.json", glb_report)
        self.store.set_artifact(asset_id, "glb", sam3d_dir / "mug.glb")
        self.store.set_artifact(asset_id, "geometry_report", root / "visual" / "geometry_report.json")
        self.store.transition(asset_id, AssetStatus.REVIEW_REQUIRED, "Visual assets are ready for human review")
        return self.store.manifest(asset_id)

    def submit_review(self, asset_id: str, decision: ReviewDecision) -> dict[str, Any]:
        if AssetStatus(self.store.manifest(asset_id)["status"]) != AssetStatus.REVIEW_REQUIRED:
            raise ValueError("Visual review is not currently required")
        root = self.store.root(asset_id)
        payload = decision.to_dict() | {"action": self.policy.repair_action(decision).action, "explanation": self.policy.repair_action(decision).explanation}
        self.store.write_json(root / "visual" / "review.json", payload)
        self.store.set_artifact(asset_id, "review", root / "visual" / "review.json")
        if not decision.approved:
            action = self.policy.repair_action(decision)
            if action.action == "human_input_required":
                return self.store.manifest(asset_id)
            return self.run_visual(asset_id, decision.revised_prompt, decision.candidate_index)
        self.store.transition(asset_id, AssetStatus.VISUAL_APPROVED, "Human approved visual asset")
        request = AssetRequest(**self.store.read_json(root / "request.json"))
        proposal = self.policy.physics_proposal(request)
        proposal["available_material_profiles"] = sorted(self._material_profiles())
        proposal["available_collision_profiles"] = sorted(self._collision_profiles())
        self.store.write_json(root / "physics" / "physics_proposal.json", proposal)
        self.store.set_artifact(asset_id, "physics_proposal", root / "physics" / "physics_proposal.json")
        self.store.transition(asset_id, AssetStatus.PHYSICS_REVIEW_REQUIRED, "Physics proposal awaits human confirmation")
        return self.store.manifest(asset_id)

    def confirm_physics(self, asset_id: str, material_profile: str, collision_profile: str) -> dict[str, Any]:
        if AssetStatus(self.store.manifest(asset_id)["status"]) != AssetStatus.PHYSICS_REVIEW_REQUIRED:
            raise ValueError("Physics confirmation is not currently required")
        materials = self._material_profiles()
        collisions = self._collision_profiles()
        if material_profile not in materials or collision_profile not in collisions:
            raise ValueError("Unknown material or collision profile")
        root = self.store.root(asset_id)
        glb = root / self.store.manifest(asset_id)["artifacts"]["glb"]
        physics = root / "physics"
        snapshot = {
            "material_profile": material_profile,
            "collision_profile": collision_profile,
            "material": materials[material_profile],
            "collision": collisions[collision_profile],
        }
        (physics / "physics_config_snapshot.yaml").write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
        self.store.set_artifact(asset_id, "physics_config", physics / "physics_config_snapshot.yaml")
        self.store.transition(asset_id, AssetStatus.USD_RUNNING, "Running USD conversion and physics authoring")
        isaac_python = self._isaac_python()
        visual_usd = physics / "visual.usd"
        self._run_or_fail(asset_id, "convert_to_usd", [str(isaac_python), "scripts/convert_to_usd.py", "--input", str(glb), "--output", str(visual_usd), "--single-mesh"], physics / "logs" / "convert.log", isaac=True)
        authored_usd = physics / "physics.usd"
        density = materials[material_profile]["density_kg_m3"]
        approximation = collisions[collision_profile]["preferred_approximation"]
        self._run_or_fail(asset_id, "prepare_physics", [str(isaac_python), "scripts/prepare_physics.py", "--input", str(visual_usd), "--output", str(authored_usd), "--collision", approximation, "--density", str(density)], physics / "logs" / "prepare_physics.log", isaac=True)
        ready_usd = physics / "simulation_ready.usd"
        material_report = physics / "material_report.json"
        material = materials[material_profile]
        self._run_or_fail(asset_id, "apply_physics_material", [
            str(isaac_python), "scripts/apply_physics_material.py", "--input", str(authored_usd), "--output", str(ready_usd), "--ensure-material",
            "--static-friction", str(material["static_friction"]), "--dynamic-friction", str(material["dynamic_friction"]), "--restitution", str(material["restitution"]),
            "--friction-combine-mode", str(material.get("friction_combine_mode", "average")), "--restitution-combine-mode", str(material.get("restitution_combine_mode", "average")),
            "--report", str(material_report),
        ], physics / "logs" / "apply_material.log", isaac=True)
        inspect_report = physics / "inspection.json"
        self._run_or_fail(asset_id, "inspect_physics", [str(isaac_python), "scripts/inspect_physics.py", "--input", str(ready_usd), "--out", str(inspect_report)], physics / "logs" / "inspect.log", isaac=True)
        inspection = self.store.read_json(inspect_report)
        if inspection.get("status") != "ok":
            self.store.fail(asset_id, "Static USD physics inspection did not pass")
            return self.store.manifest(asset_id)
        final_usd = root / "final" / "asset.usd"
        shutil.copy2(ready_usd, final_usd)
        for key, path in {"visual_usd": visual_usd, "simulation_ready_usd": ready_usd, "inspection": inspect_report, "final_usd": final_usd}.items():
            self.store.set_artifact(asset_id, key, path)
        report_path = root / "final" / "asset_report.json"
        report = {"asset_id": asset_id, "status": "complete", "inspection": inspection, "physics_config": snapshot, "artifacts": self.store.manifest(asset_id)["artifacts"]}
        self.store.write_json(report_path, report)
        self.store.set_artifact(asset_id, "final_report", report_path)
        self.store.transition(asset_id, AssetStatus.COMPLETE, "Static USD inspection passed and final asset package was written")
        return self.store.manifest(asset_id)

    def summary(self, asset_id: str) -> dict[str, Any]:
        return self.store.manifest(asset_id)

    def _run_or_fail(self, asset_id: str, name: str, command: list[str], log_path: Path, isaac: bool = False) -> None:
        result = self.runner.run(name, command, self.repo_root, log_path, isaac_clean_environment() if isaac else None)
        self.store.set_artifact(asset_id, f"{name}_log", log_path)
        if result.returncode != 0:
            self.store.fail(asset_id, f"{name} failed; read {self.store.relative(asset_id, log_path)}")
            raise RuntimeError(f"{name} failed")

    def _profiles(self, directory: str) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for path in sorted((self.repo_root / "configs" / directory).glob("*.yaml")):
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            profiles[str(value.get("name", path.stem))] = value
        return profiles

    def _material_profiles(self) -> dict[str, dict[str, Any]]:
        return self._profiles("materials")

    def _collision_profiles(self) -> dict[str, dict[str, Any]]:
        return self._profiles("collision_profiles")

    def _isaac_python(self) -> Path:
        path = os.environ.get("ISAAC_SIM_PATH")
        if not path:
            raise RuntimeError("ISAAC_SIM_PATH must be set before USD authoring")
        executable = Path(path) / "python.sh"
        if not executable.is_file():
            raise FileNotFoundError(executable)
        return executable
