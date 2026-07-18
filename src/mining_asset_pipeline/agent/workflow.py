"""Durable orchestration for Loop 1 visual generation and USD handoff."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from .inspection import inspect_glb, inspect_sam3, select_sam3_candidate
from .models import AssetRequest, AssetStatus
from .physics_agents import PhysicsAuthorAgent, PhysicsCriticAgent
from .policy import RuleBasedPolicy
from .runner import SubprocessToolRunner, ToolRunner, isaac_clean_environment
from .storage import AssetStore


class AssetWorkflow:
    def __init__(
        self,
        repo_root: Path,
        output_root: Path | None = None,
        runner: ToolRunner | None = None,
        policy: RuleBasedPolicy | None = None,
        critic_agent: PhysicsCriticAgent | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.store = AssetStore(output_root or self.repo_root / "outputs")
        self.runner = runner or SubprocessToolRunner()
        self.policy = policy or RuleBasedPolicy()
        self.sam3_env = os.environ.get("SAM3_ENV", "sam3")
        self.sam3d_env = os.environ.get("SAM3D_ENV", "sam3d-objects")
        self.physics_author = PhysicsAuthorAgent()
        self.physics_critic = critic_agent or PhysicsCriticAgent()
        self.physics_review_max_rounds = 3

    def create_asset(self, source_image: Path, request: AssetRequest) -> str:
        return self.store.create(source_image, request)

    def run_visual(self, asset_id: str) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        current = AssetStatus(manifest["status"])
        if current not in {AssetStatus.CREATED, AssetStatus.FAILED}:
            raise ValueError(f"Cannot run visual workflow while status is {current.value}")
        if current == AssetStatus.FAILED:
            self.store.transition(asset_id, AssetStatus.VISUAL_RUNNING, "Retrying failed visual workflow")
        else:
            self.store.transition(asset_id, AssetStatus.VISUAL_RUNNING, "Starting visual generation")
        root = self.store.root(asset_id)
        request = AssetRequest(**self.store.read_json(root / "request.json"))
        source = root / manifest["source_image"]
        sam3_dir = root / "visual" / "sam3"
        sam3_command = ["conda", "run", "-n", self.sam3_env, "python", "scripts/run_sam3.py", "--image", str(source), "--prompt", request.prompt, "--out-dir", str(sam3_dir)]
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
            self.store.fail(asset_id, f"SAM3 automatic checks failed: {', '.join(sam3_report['issues'])}")
            return self.store.manifest(asset_id)

        sam3d_dir = root / "visual" / "sam3d"
        seed_start = 42
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
        if glb_report["status"] != "pass":
            self.store.fail(asset_id, f"SAM3D automatic checks failed: {', '.join(glb_report['issues'])}")
            return self.store.manifest(asset_id)
        proposal = self.policy.physics_proposal(request)
        proposal["available_material_profiles"] = sorted(self._material_profiles())
        proposal["available_collision_profiles"] = sorted(self._collision_profiles())
        self.store.write_json(root / "physics" / "physics_proposal.json", proposal)
        self.store.set_artifact(asset_id, "physics_proposal", root / "physics" / "physics_proposal.json")
        self.store.transition(asset_id, AssetStatus.PHYSICS_REVIEW_RUNNING, "Visual checks passed; Physics Author/Critic review started")
        return self.store.manifest(asset_id)

    def run_physics_pipeline(self, asset_id: str) -> dict[str, Any]:
        """Run the bounded Author/Critic loop, then author USD only on acceptance."""
        if AssetStatus(self.store.manifest(asset_id)["status"]) != AssetStatus.PHYSICS_REVIEW_RUNNING:
            raise ValueError("Physics Author/Critic review is not currently running")
        materials = self._material_profiles()
        collisions = self._collision_profiles()
        root = self.store.root(asset_id)
        physics = root / "physics"
        request = AssetRequest(**self.store.read_json(root / "request.json"))
        proposal = self.store.read_json(physics / "physics_proposal.json")
        spec = self.physics_author.initial_spec(request, proposal, materials, collisions)
        for round_index in range(1, self.physics_review_max_rounds + 1):
            revision_path = physics / f"physics_spec_revision_{round_index:03d}.yaml"
            revision_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
            current_spec_path = physics / "physics_spec.yaml"
            current_spec_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
            self.store.set_artifact(asset_id, "physics_spec", current_spec_path)
            self.store.set_artifact(asset_id, f"physics_spec_revision_{round_index:03d}", revision_path)
            review = self.physics_critic.review(spec)
            review_payload = review.to_dict() | {
                "round": round_index,
                "spec_path": self.store.relative(asset_id, revision_path),
                "author_policy": self.physics_author.policy_name,
            }
            review_path = physics / f"physics_review_{round_index:03d}.json"
            self.store.write_json(review_path, review_payload)
            self.store.set_artifact(asset_id, f"physics_review_{round_index:03d}", review_path)
            if review.accepted:
                return self._run_usd_authoring(asset_id, spec)
            if round_index < self.physics_review_max_rounds:
                spec = self.physics_author.revise(spec, review.findings)
                manifest = self.store.manifest(asset_id)
                manifest["events"].append({
                    "at": manifest["updated_at"],
                    "status": AssetStatus.PHYSICS_REVIEW_RUNNING.value,
                    "message": f"Physics Author revised specification after Critic round {round_index}",
                })
                self.store.write_json(root / "manifest.json", manifest)
        self.store.transition(asset_id, AssetStatus.BLOCKED, "Physics Author/Critic did not converge within 3 rounds; USD authoring was not run")
        return self.store.manifest(asset_id)

    def _run_usd_authoring(self, asset_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        root = self.store.root(asset_id)
        glb = root / self.store.manifest(asset_id)["artifacts"]["glb"]
        physics = root / "physics"
        snapshot = {"schema_version": 1, "physics_spec": spec}
        snapshot_path = physics / "physics_config_snapshot.yaml"
        snapshot_path.write_text(yaml.safe_dump(snapshot, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.store.set_artifact(asset_id, "physics_config", snapshot_path)
        self.store.transition(asset_id, AssetStatus.USD_RUNNING, "Physics Critic accepted specification; running USD conversion and physics authoring")
        try:
            isaac_python = self._isaac_python()
        except (FileNotFoundError, RuntimeError) as exc:
            self.store.fail(asset_id, str(exc))
            raise
        visual_usd = physics / "visual.usd"
        self._run_or_fail(asset_id, "convert_to_usd", [str(isaac_python), "scripts/convert_to_usd.py", "--input", str(glb), "--output", str(visual_usd), "--single-mesh"], physics / "logs" / "convert.log", isaac=True)
        authored_usd = physics / "physics.usd"
        mass = spec["mass"]
        prepare_command = [
            str(isaac_python), "scripts/prepare_physics.py", "--input", str(visual_usd), "--output", str(authored_usd),
            "--collision", str(spec["collision"]["approximation"]),
        ]
        if mass["mode"] == "mass":
            prepare_command += ["--mass", str(mass["mass_kg"])]
        else:
            prepare_command += ["--density", str(mass["density_kg_m3"])]
        self._run_or_fail(asset_id, "prepare_physics", prepare_command, physics / "logs" / "prepare_physics.log", isaac=True)
        ready_usd = physics / "simulation_ready.usd"
        material_report = physics / "material_report.json"
        material = spec["material"]
        rigid_body = spec["rigid_body"]
        apply_command = [
            str(isaac_python), "scripts/apply_physics_material.py", "--input", str(authored_usd), "--output", str(ready_usd), "--ensure-material",
            "--static-friction", str(material["static_friction"]), "--dynamic-friction", str(material["dynamic_friction"]), "--restitution", str(material["restitution"]),
            "--friction-combine-mode", str(material["friction_combine_mode"]), "--restitution-combine-mode", str(material["restitution_combine_mode"]),
            "--rigid-body-enabled" if rigid_body["enabled"] else "--no-rigid-body-enabled",
            "--enable-ccd" if rigid_body["enable_ccd"] else "--no-enable-ccd",
            "--disable-gravity" if rigid_body["disable_gravity"] else "--no-disable-gravity",
            "--linear-damping", str(rigid_body["linear_damping"]), "--angular-damping", str(rigid_body["angular_damping"]),
            "--report", str(material_report),
        ]
        self._run_or_fail(asset_id, "apply_physics_material", apply_command, physics / "logs" / "apply_material.log", isaac=True)
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
        env = isaac_clean_environment() if isaac else None
        if hasattr(self.runner, "stream"):
            result = self.runner.stream(name, command, self.repo_root, log_path, env)
        else:
            result = self.runner.run(name, command, self.repo_root, log_path, env)
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
