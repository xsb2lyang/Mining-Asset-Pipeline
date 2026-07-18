"""Whitelisted, durable tools shared by repository Skills and API controllers."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .inspection import create_sam3_contact_sheet, inspect_glb, inspect_sam3, select_sam3_candidate
from .models import AssetBrief, AssetPhase, AssetQuality, AssetRequest, AssetStatus
from .physics_agents import PhysicsCriticAgent
from .runner import SubprocessToolRunner, ToolRunner, isaac_clean_environment
from .storage import AssetStore, asset_filename_stem


ALLOWED_VISUAL_ACTIONS = {"accept", "select_mask", "rewrite_prompt", "rerun_sam3d", "block"}


class AgentTools:
    """Narrow capability layer: no arbitrary command or output path is accepted."""

    def __init__(
        self,
        repo_root: Path,
        output_root: Path | None = None,
        runner: ToolRunner | None = None,
        critic: PhysicsCriticAgent | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.store = AssetStore(output_root or self.repo_root / "outputs")
        self.runner = runner or SubprocessToolRunner()
        self.critic = critic or PhysicsCriticAgent()
        local = self._local_environment()
        self.sam3_env = os.environ.get("SAM3_ENV") or local.get("SAM3_ENV", "sam3")
        self.sam3d_env = os.environ.get("SAM3D_ENV") or local.get("SAM3D_ENV", "sam3d-objects")
        self.sam3_dir = Path(os.environ.get("SAM3_DIR") or local.get("SAM3_DIR", self.repo_root / "third_party" / "sam3")).expanduser().resolve()
        self.sam3_checkpoint = Path(os.environ.get("SAM3_CHECKPOINT_DIR") or local.get("SAM3_CHECKPOINT_DIR", self.repo_root / "checkpoints" / "sam3")).expanduser().resolve() / "sam3.pt"
        self.sam3d_dir = Path(os.environ.get("SAM3D_DIR") or local.get("SAM3D_DIR", self.repo_root / "third_party" / "sam-3d-objects")).expanduser().resolve()
        self.sam3d_checkpoint = Path(os.environ.get("SAM3D_CHECKPOINT_DIR") or local.get("SAM3D_CHECKPOINT_DIR", self.sam3d_dir / "checkpoints" / "hf")).expanduser().resolve() / "pipeline.yaml"
        isaac = os.environ.get("ISAAC_SIM_PATH") or local.get("ISAAC_SIM_PATH")
        self.isaac_sim_path = Path(isaac).expanduser().resolve() if isaac else None

    def create(
        self,
        image: Path,
        request: AssetRequest,
        *,
        controller: str = "external_skill",
        max_llm_calls: int = 0,
    ) -> dict[str, Any]:
        asset_id = self.store.create(image, request, controller=controller, max_llm_calls=max_llm_calls)
        self.store.append_trace(asset_id, {"tool": "create", "result": "ok", "controller": controller})
        return self.status(asset_id)

    def status(self, asset_id: str) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        root = self.store.root(asset_id)
        artifacts = {
            name: {"path": relative, "exists": self.store.resolve_relative(asset_id, relative).is_file()}
            for name, relative in manifest.get("artifacts", {}).items()
        }
        return {
            "asset_id": asset_id,
            "schema_version": manifest.get("schema_version"),
            "status": manifest.get("status"),
            "phase": manifest.get("phase"),
            "quality": manifest.get("quality"),
            "controller": manifest.get("controller"),
            "budget": manifest.get("budget", {}),
            "attempts": manifest.get("attempts", {}),
            "artifacts": artifacts,
            "error": manifest.get("error"),
        }

    def record_brief(self, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        brief = AssetBrief.from_dict(payload)
        root = self.store.root(asset_id)
        path = root / "agent" / "asset_brief.json"
        registered = self.store.manifest(asset_id).get("artifacts", {}).get("asset_brief")
        if path.is_file():
            existing = AssetBrief.from_dict(self.store.read_json(path))
            if existing == brief and registered:
                return self._tool_result(asset_id, "record-brief", True, {"reused": True})
            self._require_phase(asset_id, {AssetPhase.INPUT_ANALYSIS})
        else:
            self._require_phase(asset_id, {AssetPhase.INPUT_ANALYSIS})
        self.store.write_json(path, brief.to_dict())
        self.store.set_artifact(asset_id, "asset_brief", path)
        self.store.set_phase(asset_id, AssetPhase.SEGMENTATION, "Asset brief recorded; ready for SAM3")
        self.store.append_trace(asset_id, {"tool": "record-brief", "result": "ok", "prompts": brief.sam3_prompts})
        return self.status(asset_id)

    def run_sam3(self, asset_id: str, prompt: str) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("SAM3 prompt cannot be empty")
        root = self.store.root(asset_id)
        manifest = self.store.manifest(asset_id)
        self.store.require_v3(manifest)
        self._require_artifact(asset_id, "asset_brief")
        selected_attempt = self._selected(asset_id).get("sam3_attempt")
        for attempt_dir in sorted((root / "visual" / "sam3_attempts").glob("attempt_*")):
            request_path = attempt_dir / "request.json"
            report_path = attempt_dir / "report.json"
            if request_path.is_file() and report_path.is_file():
                if self.store.read_json(request_path).get("prompt") == prompt:
                    report = self.store.read_json(report_path)
                    relative_attempt = self.store.relative(asset_id, attempt_dir)
                    if selected_attempt == relative_attempt and report.get("status") == "pass":
                        self._require_artifact(asset_id, "sam3_mask")
                        self._require_artifact(asset_id, "sam3_report")
                        return self._tool_result(asset_id, "run-sam3", True, {"reused": True, "attempt": attempt_dir.name, "report": report})
                    self._require_phase(asset_id, {AssetPhase.SEGMENTATION})
                    self._select_sam3_attempt(asset_id, attempt_dir, report["selected_index"])
                    return self._tool_result(asset_id, "run-sam3", report.get("status") == "pass", {"reused": True, "attempt": attempt_dir.name, "report": report})
        self._require_phase(asset_id, {AssetPhase.SEGMENTATION})
        attempt = self.store.increment(asset_id, "attempts", "sam3")
        if attempt > 3:
            self._block(asset_id, "SAM3 prompt attempt budget exhausted")
            raise RuntimeError("SAM3 allows at most 3 prompt attempts")
        self.store.set_phase(asset_id, AssetPhase.SEGMENTATION, f"Running SAM3 attempt {attempt}")
        attempt_dir = root / "visual" / "sam3_attempts" / f"attempt_{attempt:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self.store.write_json(attempt_dir / "request.json", {"prompt": prompt})
        source = self.store.source_path(asset_id)
        command = [
            "conda", "run", "-n", self.sam3_env, "python", "scripts/run_sam3.py",
            "--image", str(source), "--prompt", prompt, "--out-dir", str(attempt_dir),
            "--sam3-dir", str(self.sam3_dir), "--checkpoint", str(self.sam3_checkpoint),
        ]
        self._run(asset_id, "sam3", command, attempt_dir / "sam3.log")
        report = inspect_sam3(attempt_dir / "mask.npz", attempt_dir / "meta.json")
        contact = create_sam3_contact_sheet(attempt_dir / "mask.npz", source, attempt_dir / "candidates.png")
        self.store.write_json(attempt_dir / "report.json", report)
        self._select_sam3_attempt(asset_id, attempt_dir, int(report["selected_index"]))
        self.store.set_artifact(asset_id, "sam3_contact_sheet", contact)
        return self._tool_result(asset_id, "run-sam3", report["status"] == "pass", {"report": report, "attempt": attempt_dir.name})

    def select_mask(self, asset_id: str, candidate_index: int) -> dict[str, Any]:
        root = self.store.root(asset_id)
        selected = self._selected(asset_id)
        if selected.get("mask_candidate_index") == candidate_index:
            report = self.store.read_json(self._require_artifact(asset_id, "sam3_report"))
            if report.get("status") == "pass":
                self._require_artifact(asset_id, "sam3_mask")
                return self._tool_result(asset_id, "select-mask", True, {"report": report, "reused": True})
        self._require_phase(asset_id, {AssetPhase.SEGMENTATION})
        relative = selected.get("sam3_attempt")
        if not relative:
            raise ValueError("run-sam3 must succeed before select-mask")
        attempt_dir = self.store.resolve_relative(asset_id, relative)
        source = self.store.source_path(asset_id)
        select_sam3_candidate(attempt_dir / "mask.npz", attempt_dir / "meta.json", source, candidate_index)
        report = inspect_sam3(attempt_dir / "mask.npz", attempt_dir / "meta.json")
        contact = create_sam3_contact_sheet(attempt_dir / "mask.npz", source, attempt_dir / "candidates.png")
        self.store.write_json(attempt_dir / "report.json", report)
        self._select_sam3_attempt(asset_id, attempt_dir, candidate_index)
        self.store.set_artifact(asset_id, "sam3_contact_sheet", contact)
        return self._tool_result(asset_id, "select-mask", report["status"] == "pass", {"report": report})

    def run_sam3d(self, asset_id: str, seed: int) -> dict[str, Any]:
        if seed not in {42, 43, 44}:
            raise ValueError("SAM3D seed must be one of 42, 43, 44")
        root = self.store.root(asset_id)
        selected = self._selected(asset_id)
        sam3_relative = selected.get("sam3_attempt")
        if not sam3_relative:
            raise ValueError("select a SAM3 mask before running SAM3D")
        sam3_dir = self.store.resolve_relative(asset_id, sam3_relative)
        mask_path = sam3_dir / "mask.npz"
        mask_sha256 = self.store._sha256(mask_path)
        for attempt_dir in sorted((root / "visual" / "sam3d_attempts").glob("attempt_*")):
            request_path = attempt_dir / "request.json"
            report_path = attempt_dir / "report.json"
            if request_path.is_file() and report_path.is_file():
                prior_request = self.store.read_json(request_path)
            else:
                continue
            if prior_request.get("seed") == seed and prior_request.get("mask_sha256") == mask_sha256:
                report = self.store.read_json(report_path)
                if selected.get("sam3d_attempt") == self.store.relative(asset_id, attempt_dir) and report.get("status") == "pass":
                    self._require_artifact(asset_id, "glb")
                    self._require_artifact(asset_id, "geometry_report")
                    return self._tool_result(asset_id, "run-sam3d", True, {"reused": True, "attempt": attempt_dir.name, "report": report})
                self._require_phase(asset_id, {AssetPhase.SEGMENTATION, AssetPhase.RECONSTRUCTION, AssetPhase.VISUAL_REVIEW})
                self._select_sam3d_attempt(asset_id, attempt_dir, seed)
                return self._tool_result(asset_id, "run-sam3d", report.get("status") == "pass", {"reused": True, "attempt": attempt_dir.name, "report": report})
        self._require_phase(asset_id, {AssetPhase.SEGMENTATION, AssetPhase.RECONSTRUCTION, AssetPhase.VISUAL_REVIEW})
        attempt = self.store.increment(asset_id, "attempts", "sam3d")
        if attempt > 3:
            self._block(asset_id, "SAM3D seed attempt budget exhausted")
            raise RuntimeError("SAM3D allows at most 3 seed attempts")
        self.store.set_phase(asset_id, AssetPhase.RECONSTRUCTION, f"Running SAM3D seed {seed}")
        attempt_dir = root / "visual" / "sam3d_attempts" / f"attempt_{attempt:03d}_seed_{seed}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self.store.write_json(attempt_dir / "request.json", {"seed": seed, "sam3_attempt": sam3_relative, "mask_candidate_index": selected.get("mask_candidate_index"), "mask_sha256": mask_sha256})
        source = self.store.source_path(asset_id)
        command = [
            "conda", "run", "-n", self.sam3d_env, "python", "scripts/run_sam3d.py",
            "--image", str(source), "--mask-npz", str(sam3_dir / "mask.npz"),
            "--out-dir", str(attempt_dir), "--seed", str(seed),
            "--sam3d-dir", str(self.sam3d_dir), "--checkpoint", str(self.sam3d_checkpoint),
        ]
        self._run(asset_id, f"sam3d_seed_{seed}", command, attempt_dir / "sam3d.log")
        glb = attempt_dir / "mug.glb"
        report = inspect_glb(glb)
        report["seed"] = seed
        preview = attempt_dir / "views.png"
        if not preview.is_file():
            legacy_preview = attempt_dir / "preview.png"
            if legacy_preview.is_file():
                shutil.copy2(legacy_preview, preview)
            else:
                report.setdefault("issues", []).append("missing_four_view_preview")
                report["status"] = "needs_review"
        self.store.write_json(attempt_dir / "report.json", report)
        self._select_sam3d_attempt(asset_id, attempt_dir, seed)
        if preview.is_file():
            self.store.set_artifact(asset_id, "sam3d_contact_sheet", preview)
        return self._tool_result(asset_id, "run-sam3d", report["status"] == "pass", {"report": report, "attempt": attempt_dir.name})

    def record_visual_review(self, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if action not in ALLOWED_VISUAL_ACTIONS:
            raise ValueError(f"visual action must be one of {sorted(ALLOWED_VISUAL_ACTIONS)}")
        if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
            raise ValueError("visual review summary is required")
        findings = payload.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("visual findings must be a list")
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("severity") not in {"error", "warning"}:
                raise ValueError("visual findings require error/warning severity")
            if not all(isinstance(finding.get(key), str) and finding[key] for key in ("code", "message")):
                raise ValueError("visual findings require code and message")
        if action == "accept" and any(item.get("severity") == "error" for item in findings):
            raise ValueError("visual output cannot be accepted with error findings")
        required_argument = {"select_mask": "candidate_index", "rewrite_prompt": "prompt", "rerun_sam3d": "seed"}.get(action)
        if required_argument and payload.get(required_argument) is None:
            raise ValueError(f"visual action {action} requires {required_argument}")
        if action == "select_mask" and not isinstance(payload.get("candidate_index"), int):
            raise ValueError("select_mask candidate_index must be an integer")
        if action == "rewrite_prompt" and (not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip()):
            raise ValueError("rewrite_prompt requires a non-empty prompt")
        if action == "rerun_sam3d" and payload.get("seed") not in {42, 43, 44}:
            raise ValueError("rerun_sam3d seed must be one of 42, 43, 44")
        root = self.store.root(asset_id)
        path = root / "visual" / "visual_review.json"
        record = {"accepted": action == "accept", **payload}
        registered = self.store.manifest(asset_id).get("artifacts", {}).get("visual_review")
        if registered and path.is_file() and self.store.read_json(path) == record:
            self._require_artifact(asset_id, "visual_review")
            return self._tool_result(asset_id, "record-visual-review", True, {"reused": True})
        phase = AssetPhase(self.store.manifest(asset_id)["phase"])
        if action == "block":
            if phase not in {AssetPhase.SEGMENTATION, AssetPhase.RECONSTRUCTION, AssetPhase.VISUAL_REVIEW}:
                raise ValueError("block is only valid during visual phases")
        else:
            self._require_phase(asset_id, {AssetPhase.VISUAL_REVIEW})
        if action == "accept":
            for name in ("sam3_report", "geometry_report"):
                report = self.store.read_json(self._require_artifact(asset_id, name))
                if report.get("status") != "pass":
                    raise ValueError(f"cannot accept visual output while {name} is not pass")
        self.store.write_json(path, record)
        self.store.set_artifact(asset_id, "visual_review", path)
        self.store.append_trace(asset_id, {"tool": "record-visual-review", "result": "ok", "decision": record})
        if action == "accept":
            self.store.set_phase(asset_id, AssetPhase.PHYSICS_AUTHORING, "Semantic visual review accepted")
        elif action == "block":
            self._block(asset_id, str(payload.get("reason") or payload["summary"]))
        elif action == "select_mask":
            self.store.set_phase(asset_id, AssetPhase.SEGMENTATION, "Visual critic requested another mask candidate")
        elif action == "rewrite_prompt":
            self.store.set_phase(asset_id, AssetPhase.SEGMENTATION, "Visual critic requested a rewritten SAM3 prompt")
        else:
            self.store.set_phase(asset_id, AssetPhase.RECONSTRUCTION, "Visual critic requested another SAM3D seed")
        return self.status(asset_id)

    def submit_physics(self, asset_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, dict) or spec.get("schema_version") != 1:
            raise ValueError("physics specification schema_version must be 1")
        for key in ("asset", "material", "mass", "collision", "rigid_body"):
            if not isinstance(spec.get(key), dict):
                raise ValueError(f"physics specification requires object field {key}")
        current = self.store.root(asset_id) / "physics" / "physics_spec.yaml"
        registered = self.store.manifest(asset_id).get("artifacts", {}).get("physics_spec")
        if registered and current.is_file() and yaml.safe_load(current.read_text(encoding="utf-8")) == spec:
            self._require_artifact(asset_id, "physics_spec")
            round_index = int(self.store.manifest(asset_id).get("attempts", {}).get("physics", 0))
            return self._tool_result(asset_id, "submit-physics", True, {"round": round_index, "reused": True})
        self._require_phase(asset_id, {AssetPhase.PHYSICS_AUTHORING, AssetPhase.PHYSICS_REVIEW})
        visual = self.store.read_json(self._require_artifact(asset_id, "visual_review"))
        if not visual.get("accepted"):
            raise ValueError("visual review must be accepted before physics authoring")
        root = self.store.root(asset_id)
        round_index = self.store.increment(asset_id, "attempts", "physics")
        if round_index > 2:
            self._block(asset_id, "Physics Author/Critic round budget exhausted")
            raise RuntimeError("physics authoring allows at most 2 rounds")
        revision = root / "physics" / "author" / f"physics_spec_{round_index:03d}.yaml"
        self._write_yaml(revision, spec)
        current = root / "physics" / "physics_spec.yaml"
        self._write_yaml(current, spec)
        self.store.set_artifact(asset_id, "physics_spec", current)
        self.store.set_artifact(asset_id, f"physics_spec_{round_index:03d}", revision)
        self.store.set_phase(asset_id, AssetPhase.PHYSICS_REVIEW, f"Physics Author submitted round {round_index}")
        return self._tool_result(asset_id, "submit-physics", True, {"round": round_index})

    def check_physics(self, asset_id: str, semantic_review: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        existing_relative = manifest.get("artifacts", {}).get("physics_review")
        if existing_relative:
            existing = self.store.read_json(self._require_artifact(asset_id, "physics_review"))
            if existing.get("accepted") and existing.get("semantic_review") == semantic_review:
                self._require_artifact(asset_id, "physics_spec")
                return self._tool_result(asset_id, "check-physics", True, {"review": existing, "reused": True})
        self._require_phase(asset_id, {AssetPhase.PHYSICS_REVIEW})
        root = self.store.root(asset_id)
        spec_path = self._require_artifact(asset_id, "physics_spec")
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        snapshot = root / "physics" / "physics_config_snapshot.yaml"
        self._write_yaml(snapshot, {"schema_version": 1, "physics_spec": spec})
        self.store.set_artifact(asset_id, "physics_config", snapshot)
        deterministic = PhysicsCriticAgent().review(spec)
        semantic_errors: list[dict[str, Any]] = []
        if semantic_review is not None:
            if not isinstance(semantic_review.get("accepted"), bool):
                raise ValueError("semantic critic accepted must be boolean")
            if not isinstance(semantic_review.get("summary"), str) or not semantic_review["summary"].strip():
                raise ValueError("semantic critic summary must be a non-empty string")
            findings = semantic_review.get("findings", [])
            if not isinstance(findings, list):
                raise ValueError("semantic critic findings must be a list")
            for finding in findings:
                if not isinstance(finding, dict) or finding.get("severity") not in {"error", "warning"}:
                    raise ValueError("semantic critic findings require error/warning severity")
                if not all(isinstance(finding.get(key), str) and finding[key] for key in ("code", "path", "message")):
                    raise ValueError("semantic critic findings require code, path, and message")
            semantic_errors = [item for item in findings if isinstance(item, dict) and item.get("severity") == "error"]
        accepted = deterministic.accepted and not semantic_errors and (semantic_review is None or semantic_review["accepted"])
        review_payload = {
            "role": "physics_critic",
            "policy": "semantic_plus_deterministic_v1" if semantic_review is not None else deterministic.policy,
            "accepted": accepted,
            "summary": "Accepted by semantic and deterministic critics." if accepted else "Rejected by physics critic.",
            "semantic_review": semantic_review,
            "deterministic_review": deterministic.to_dict(),
            "findings": [*(semantic_review or {}).get("findings", []), *deterministic.findings],
        }
        round_index = int(self.store.manifest(asset_id)["attempts"]["physics"])
        path = root / "physics" / "critic" / f"physics_review_{round_index:03d}.json"
        self.store.write_json(path, review_payload)
        # Compatibility artifact used by the previous workflow and handoff docs.
        compatibility = root / "physics" / f"physics_review_{round_index:03d}.json"
        self.store.write_json(compatibility, review_payload | {"round": round_index})
        self.store.set_artifact(asset_id, "physics_review", path)
        self.store.set_artifact(asset_id, f"physics_review_{round_index:03d}", compatibility)
        if accepted:
            self.store.set_phase(asset_id, AssetPhase.USD_AUTHORING, "Physics specification accepted")
        return self._tool_result(asset_id, "check-physics", accepted, {"review": review_payload})

    def author_usd(self, asset_id: str) -> dict[str, Any]:
        root = self.store.root(asset_id)
        manifest = self.store.manifest(asset_id)
        if manifest.get("status") == AssetStatus.COMPLETE.value or manifest.get("phase") == AssetPhase.FINALIZATION.value:
            inspection = self._require_artifact(asset_id, "inspection")
            self._require_artifact(asset_id, "simulation_ready_usd")
            if self.store.read_json(inspection).get("status") == "ok":
                return self._tool_result(asset_id, "author-usd", True, {"reused": True})
        if manifest.get("phase") == AssetPhase.STATIC_VALIDATION.value:
            try:
                inspection = self._require_artifact(asset_id, "inspection")
                self._require_artifact(asset_id, "simulation_ready_usd")
                if self.store.read_json(inspection).get("status") == "ok":
                    return self._tool_result(asset_id, "author-usd", True, {"reused": True})
            except (FileNotFoundError, ValueError):
                pass
            self.store.set_phase(asset_id, AssetPhase.USD_AUTHORING, "Static artifacts were missing or changed; re-running USD authoring")
        self._require_phase(asset_id, {AssetPhase.USD_AUTHORING})
        review_path = self._require_artifact(asset_id, "physics_review")
        if not self.store.read_json(review_path).get("accepted"):
            raise ValueError("physics review must pass before USD authoring")
        spec_path = self._require_artifact(asset_id, "physics_spec")
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        glb = self._require_artifact(asset_id, "glb")
        self.store.set_phase(asset_id, AssetPhase.USD_AUTHORING, "Running USD conversion and physics authoring")
        isaac_python = self._isaac_python()
        physics = root / "physics"
        visual_usd = physics / "visual.usd"
        self._run(asset_id, "convert_to_usd", [str(isaac_python), "scripts/convert_to_usd.py", "--input", str(glb), "--output", str(visual_usd), "--single-mesh"], physics / "logs" / "convert.log", isaac=True)
        authored_usd = physics / "physics.usd"
        mass = spec["mass"]
        command = [str(isaac_python), "scripts/prepare_physics.py", "--input", str(visual_usd), "--output", str(authored_usd), "--collision", str(spec["collision"]["approximation"])]
        command += ["--mass", str(mass["mass_kg"])] if mass["mode"] == "mass" else ["--density", str(mass["density_kg_m3"])]
        self._run(asset_id, "prepare_physics", command, physics / "logs" / "prepare_physics.log", isaac=True)
        ready_usd = physics / "simulation_ready.usd"
        material_report = physics / "material_report.json"
        material = spec["material"]
        body = spec["rigid_body"]
        command = [
            str(isaac_python), "scripts/apply_physics_material.py", "--input", str(authored_usd), "--output", str(ready_usd), "--ensure-material",
            "--static-friction", str(material["static_friction"]), "--dynamic-friction", str(material["dynamic_friction"]), "--restitution", str(material["restitution"]),
            "--friction-combine-mode", str(material["friction_combine_mode"]), "--restitution-combine-mode", str(material["restitution_combine_mode"]),
            "--rigid-body-enabled" if body["enabled"] else "--no-rigid-body-enabled", "--enable-ccd" if body["enable_ccd"] else "--no-enable-ccd",
            "--disable-gravity" if body["disable_gravity"] else "--no-disable-gravity", "--linear-damping", str(body["linear_damping"]),
            "--angular-damping", str(body["angular_damping"]), "--report", str(material_report),
        ]
        self._run(asset_id, "apply_physics_material", command, physics / "logs" / "apply_material.log", isaac=True)
        self.store.set_phase(asset_id, AssetPhase.STATIC_VALIDATION, "Running static USD inspection")
        inspection = physics / "inspection.json"
        expected = physics / "expected_physics.json"
        self.store.write_json(expected, {key: spec[key] for key in ("material", "mass", "collision", "rigid_body")})
        inspection_result = self._run(asset_id, "inspect_physics", [str(isaac_python), "scripts/inspect_physics.py", "--input", str(ready_usd), "--out", str(inspection), "--expected", str(expected)], physics / "logs" / "inspect.log", isaac=True, allow_failure=True)
        if inspection.is_file():
            inspection_payload = self.store.read_json(inspection)
            inspection_payload["input"] = self.store.relative(asset_id, ready_usd)
            self.store.write_json(inspection, inspection_payload)
        for name, path in {"visual_usd": visual_usd, "physics_usd": authored_usd, "simulation_ready_usd": ready_usd, "material_report": material_report, "expected_physics": expected, "inspection": inspection}.items():
            self.store.set_artifact(asset_id, name, path)
        passed = inspection_result == 0 and inspection.is_file() and self.store.read_json(inspection).get("status") == "ok"
        if not passed:
            self.store.fail(asset_id, "Static USD physics inspection did not pass")
        return self._tool_result(asset_id, "author-usd", passed, {"inspection": self.store.read_json(inspection)})

    def finalize(
        self,
        asset_id: str,
        *,
        quality: str = AssetQuality.AGENT_REVIEWED.value,
        fallback_reason: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        selected_quality = AssetQuality(quality)
        if selected_quality == AssetQuality.PENDING:
            raise ValueError("final quality cannot be pending")
        root = self.store.root(asset_id)
        manifest = self.store.manifest(asset_id)
        if manifest.get("status") == AssetStatus.COMPLETE.value:
            final_usd = self._ensure_named_final_asset(asset_id)
            return self._tool_result(asset_id, "finalize", True, {"reused": True, "final_usd": self.store.relative(asset_id, final_usd)})
        self._require_phase(asset_id, {AssetPhase.STATIC_VALIDATION, AssetPhase.FINALIZATION})
        visual_review = self.store.read_json(self._require_artifact(asset_id, "visual_review"))
        physics_review = self.store.read_json(self._require_artifact(asset_id, "physics_review"))
        inspection = self.store.read_json(self._require_artifact(asset_id, "inspection"))
        if not visual_review.get("accepted") or not physics_review.get("accepted") or inspection.get("status") != "ok":
            raise ValueError("visual, physics, and static reviews must pass before finalize")
        if selected_quality == AssetQuality.DEGRADED and not fallback_reason:
            raise ValueError("degraded assets require a fallback reason")
        if selected_quality == AssetQuality.AGENT_REVIEWED and physics_review.get("semantic_review") is None:
            raise ValueError("agent_reviewed quality requires a semantic Physics Critic review")
        spec_for_quality = yaml.safe_load(self._require_artifact(asset_id, "physics_spec").read_text(encoding="utf-8"))
        material_profiles = self._profiles("materials")
        collision_profiles = self._profiles("collision_profiles")
        material_name = spec_for_quality.get("material", {}).get("profile")
        collision_name = spec_for_quality.get("collision", {}).get("profile")
        if material_name not in material_profiles or collision_name not in collision_profiles:
            raise ValueError("physics profiles must name repository-controlled material and collision profiles")
        if selected_quality == AssetQuality.DEGRADED:
            if material_name == "generic" or collision_name == "generic_solid":
                raise ValueError("generic material or collision profiles cannot be delivered as degraded")
            material = spec_for_quality["material"]
            baseline = material_profiles[material_name]
            baseline_density = float(baseline["density_kg_m3"])
            if abs(float(material["density_kg_m3"]) - baseline_density) > baseline_density * 0.3:
                raise ValueError("degraded material density must remain within 30 percent of its repository profile")
            collision = spec_for_quality["collision"]
            collision_baseline = collision_profiles[collision_name]
            allowed_approximations = {collision_baseline.get("preferred_approximation"), collision_baseline.get("fallback_approximation")}
            if collision.get("approximation") not in allowed_approximations:
                raise ValueError("degraded collision approximation must come from its repository profile")
        ready = self._require_artifact(asset_id, "simulation_ready_usd")
        self.store.set_phase(asset_id, AssetPhase.FINALIZATION, "Writing final static asset package")
        brief = self.store.read_json(self._require_artifact(asset_id, "asset_brief"))
        final_stem = asset_filename_stem(str(brief["object_name"]), str(brief.get("category", "generated_asset")))
        final_usd = root / "final" / f"{final_stem}.usd"
        shutil.copy2(ready, final_usd)
        self.store.set_artifact(asset_id, "final_usd", final_usd)
        manifest = self.store.manifest(asset_id)
        trace_path = root / "agent" / "trace.jsonl"
        repair_trace = []
        if trace_path.is_file():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                try:
                    repair_trace.append(json.loads(line))
                except json.JSONDecodeError:
                    repair_trace.append({"error": "unparseable_trace_line"})
        report = {
            "schema_version": 1,
            "asset_id": asset_id,
            "status": "complete",
            "quality": selected_quality.value,
            "controller": manifest["controller"],
            "original_prompt": self.store.read_json(root / "request.json")["prompt"],
            "asset_brief": brief,
            "normalized_prompt": brief["sam3_prompts"][0],
            "final_filename": final_usd.name,
            "selection": self._selected(asset_id),
            "repair_trace": repair_trace,
            "visual_review": visual_review,
            "physics_spec": yaml.safe_load(self._require_artifact(asset_id, "physics_spec").read_text(encoding="utf-8")),
            "physics_review": physics_review,
            "model": model,
            "llm_calls": manifest.get("budget", {}).get("llm_calls_used", 0),
            "fallback_reason": fallback_reason,
            "inspection": inspection,
            "artifacts": manifest["artifacts"],
            "validation_boundary": "Static physics checks passed; Loop 2 dynamic, containment, drop, grasp, and robot-task tests have not run.",
        }
        report_path = root / "final" / "asset_report.json"
        self.store.write_json(report_path, report)
        self.store.set_artifact(asset_id, "final_report", report_path)
        self.store.transition(asset_id, AssetStatus.COMPLETE, "Final static asset package written", phase=AssetPhase.FINALIZATION, quality=selected_quality)
        return self._tool_result(asset_id, "finalize", True, {"final_usd": str(final_usd), "quality": selected_quality.value})

    def _ensure_named_final_asset(self, asset_id: str) -> Path:
        """Idempotently migrate legacy ``final/asset.usd`` bundles."""
        current = self._require_artifact(asset_id, "final_usd")
        report_path = self._require_artifact(asset_id, "final_report")
        brief = self.store.read_json(self._require_artifact(asset_id, "asset_brief"))
        stem = asset_filename_stem(str(brief["object_name"]), str(brief.get("category", "generated_asset")))
        expected = self.store.root(asset_id) / "final" / f"{stem}.usd"
        if current != expected:
            if expected.exists():
                raise FileExistsError(f"semantic final asset path already exists: {expected}")
            current.replace(expected)
            self.store.set_artifact(asset_id, "final_usd", expected)
            report = self.store.read_json(report_path)
            report["final_filename"] = expected.name
            report["artifacts"] = self.store.manifest(asset_id)["artifacts"]
            self.store.write_json(report_path, report)
            self.store.set_artifact(asset_id, "final_report", report_path)
        return expected

    def _select_sam3_attempt(self, asset_id: str, attempt_dir: Path, index: int) -> None:
        selected = self._selected(asset_id)
        selected.update({"sam3_attempt": self.store.relative(asset_id, attempt_dir), "mask_candidate_index": index})
        path = self.store.root(asset_id) / "visual" / "selected.json"
        self.store.write_json(path, selected)
        self.store.set_artifact(asset_id, "selected", path)
        self.store.set_artifact(asset_id, "sam3_mask", attempt_dir / "mask.npz")
        self.store.set_artifact(asset_id, "sam3_report", attempt_dir / "report.json")

    def _select_sam3d_attempt(self, asset_id: str, attempt_dir: Path, seed: int) -> None:
        selected = self._selected(asset_id)
        selected.update({"sam3d_attempt": self.store.relative(asset_id, attempt_dir), "seed": seed})
        path = self.store.root(asset_id) / "visual" / "selected.json"
        self.store.write_json(path, selected)
        self.store.set_artifact(asset_id, "selected", path)
        self.store.set_artifact(asset_id, "glb", attempt_dir / "mug.glb")
        self.store.set_artifact(asset_id, "geometry_report", attempt_dir / "report.json")
        self.store.set_phase(asset_id, AssetPhase.VISUAL_REVIEW, "SAM3D reconstruction ready for semantic review")

    def _selected(self, asset_id: str) -> dict[str, Any]:
        path = self.store.root(asset_id) / "visual" / "selected.json"
        registered = self.store.manifest(asset_id).get("artifacts", {}).get("selected")
        if registered:
            return self.store.read_json(self.store.artifact_path(asset_id, "selected"))
        return self.store.read_json(path) if path.is_file() else {}

    def _require_artifact(self, asset_id: str, name: str) -> Path:
        return self.store.artifact_path(asset_id, name)

    def _require_phase(self, asset_id: str, allowed: set[AssetPhase]) -> None:
        manifest = self.store.manifest(asset_id)
        self.store.require_v3(manifest)
        current = AssetPhase(manifest["phase"])
        if AssetStatus(manifest["status"]) not in {AssetStatus.CREATED, AssetStatus.RUNNING}:
            raise ValueError(f"action is not valid while status is {manifest['status']}")
        if current not in allowed:
            names = ", ".join(sorted(item.value for item in allowed))
            raise ValueError(f"action is not valid in phase {current.value}; expected one of: {names}")

    def _profiles(self, directory: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for path in sorted((self.repo_root / "configs" / directory).glob("*.yaml")):
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            result[str(value.get("name", path.stem))] = value
        return result

    def _run(self, asset_id: str, name: str, command: list[str], log: Path, isaac: bool = False, allow_failure: bool = False) -> int:
        env = isaac_clean_environment() if isaac else None
        result = self.runner.stream(name, command, self.repo_root, log, env) if hasattr(self.runner, "stream") else self.runner.run(name, command, self.repo_root, log, env)
        self.store.set_artifact(asset_id, f"{name}_log", log)
        if result.returncode != 0:
            self.store.append_trace(asset_id, {"tool": name, "result": "error", "returncode": result.returncode})
            if allow_failure:
                return result.returncode
            self.store.fail(asset_id, f"{name} failed; read {self.store.relative(asset_id, log)}")
            raise RuntimeError(f"{name} failed; read {self.store.relative(asset_id, log)}")
        return result.returncode

    def _isaac_python(self) -> Path:
        configured = os.environ.get("ISAAC_SIM_PATH")
        path = Path(configured).expanduser().resolve() if configured else self.isaac_sim_path
        if path is None:
            raise RuntimeError("ISAAC_SIM_PATH must be set before USD authoring")
        executable = path / "python.sh"
        if not executable.is_file():
            raise FileNotFoundError(executable)
        return executable

    def _local_environment(self) -> dict[str, str]:
        """Read simple local path settings without executing shell code."""
        path = self.repo_root / "environments" / "local.env"
        if not path.is_file():
            return {}
        values: dict[str, str] = {}
        pattern = re.compile(r"^export\s+([A-Z][A-Z0-9_]*)=(.*)$")
        allowed = {"SAM3_ENV", "SAM3D_ENV", "SAM3_DIR", "SAM3D_DIR", "SAM3_CHECKPOINT_DIR", "SAM3D_CHECKPOINT_DIR", "ISAAC_SIM_PATH"}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(raw_line.strip())
            if not match:
                continue
            name, raw_value = match.groups()
            if name not in allowed:
                continue
            value = raw_value.strip().strip("\"'")
            value = value.replace("${REPO_ROOT}", str(self.repo_root)).replace("$REPO_ROOT", str(self.repo_root))
            values[name] = os.path.expanduser(os.path.expandvars(value))
        return values

    def _block(self, asset_id: str, reason: str) -> None:
        self.store.transition(asset_id, AssetStatus.BLOCKED, reason)
        manifest = self.store.manifest(asset_id)
        manifest["error"] = reason
        self.store.write_json(self.store.root(asset_id) / "manifest.json", manifest)

    def _tool_result(self, asset_id: str, tool: str, ok: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.store.append_trace(asset_id, {"tool": tool, "result": "ok" if ok else "needs_review", "details": details or {}})
        return {"ok": ok, **self.status(asset_id), **(details or {})}

    @staticmethod
    def _write_yaml(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")
        temporary.replace(path)
