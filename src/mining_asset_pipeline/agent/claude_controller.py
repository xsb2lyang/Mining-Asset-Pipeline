"""Embedded Claude controller for the same whitelisted tools used by the Skill."""
from __future__ import annotations

import base64
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .models import AssetBrief, AssetPhase, AssetQuality, AssetRequest, AssetStatus
from .physics_agents import PhysicsAuthorAgent
from .policy import RuleBasedPolicy
from .tools import AgentTools


DEFAULT_MODEL = "claude-sonnet-5"


class CallBudgetExceeded(RuntimeError):
    pass


ASSET_BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["object_name", "category", "sam3_prompts", "material", "is_open_container", "is_slender", "is_fast_or_small", "is_fixed", "target_task", "robot_constraints", "assumptions"],
    "properties": {
        "object_name": {"type": "string"}, "category": {"type": "string"},
        "sam3_prompts": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
        "material": {"type": "string", "enum": ["ceramic", "steel", "iron", "aluminum", "copper", "rubber", "wood", "ore", "plastic", "unknown"]}, "is_open_container": {"type": "boolean"},
        "is_slender": {"type": "boolean"}, "is_fast_or_small": {"type": "boolean"},
        "is_fixed": {"type": "boolean"}, "target_task": {"type": "string"},
        "robot_constraints": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

VISUAL_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["action", "summary", "findings", "candidate_index", "prompt", "seed", "reason"],
    "properties": {
        "action": {"type": "string", "enum": ["accept", "select_mask", "rewrite_prompt", "rerun_sam3d", "block"]},
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["severity", "code", "message"], "properties": {"severity": {"type": "string", "enum": ["error", "warning"]}, "code": {"type": "string"}, "message": {"type": "string"}}}},
        "candidate_index": {"type": ["integer", "null"]}, "prompt": {"type": ["string", "null"]},
        "seed": {"type": ["integer", "null"]}, "reason": {"type": ["string", "null"]},
    },
}

PHYSICS_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["accepted", "summary", "findings"],
    "properties": {
        "accepted": {"type": "boolean"}, "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["severity", "code", "path", "message"], "properties": {"severity": {"type": "string", "enum": ["error", "warning"]}, "code": {"type": "string"}, "path": {"type": "string"}, "message": {"type": "string"}}}},
    },
}

PHYSICS_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "asset", "material", "mass", "collision", "rigid_body", "assumptions", "rationale"],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "asset": {
            "type": "object", "additionalProperties": False,
            "required": ["prompt", "category", "target_task", "robot_constraints"],
            "properties": {"prompt": {"type": "string"}, "category": {"type": "string"}, "target_task": {"type": "string"}, "robot_constraints": {"type": "string"}},
        },
        "material": {
            "type": "object", "additionalProperties": False,
            "required": ["profile", "density_kg_m3", "static_friction", "dynamic_friction", "restitution", "friction_combine_mode", "restitution_combine_mode"],
            "properties": {
                "profile": {"type": "string"}, "density_kg_m3": {"type": "number", "exclusiveMinimum": 0},
                "static_friction": {"type": "number", "minimum": 0}, "dynamic_friction": {"type": "number", "minimum": 0},
                "restitution": {"type": "number", "minimum": 0, "maximum": 1},
                "friction_combine_mode": {"type": "string", "enum": ["average", "min", "multiply", "max"]},
                "restitution_combine_mode": {"type": "string", "enum": ["average", "min", "multiply", "max"]},
            },
        },
        "mass": {
            "type": "object", "additionalProperties": False,
            "required": ["mode", "density_kg_m3", "mass_kg"],
            "properties": {"mode": {"type": "string", "enum": ["density", "mass"]}, "density_kg_m3": {"type": ["number", "null"]}, "mass_kg": {"type": ["number", "null"]}},
        },
        "collision": {
            "type": "object", "additionalProperties": False,
            "required": ["profile", "enabled", "approximation", "fallback_approximation", "production_strategy"],
            "properties": {"profile": {"type": "string"}, "enabled": {"type": "boolean"}, "approximation": {"type": "string", "enum": ["convexHull", "convexDecomposition", "sdf"]}, "fallback_approximation": {"type": ["string", "null"], "enum": ["convexHull", "convexDecomposition", "sdf", None]}, "production_strategy": {"type": "string"}},
        },
        "rigid_body": {
            "type": "object", "additionalProperties": False,
            "required": ["enabled", "enable_ccd", "disable_gravity", "linear_damping", "angular_damping"],
            "properties": {"enabled": {"type": "boolean"}, "enable_ccd": {"type": "boolean"}, "disable_gravity": {"type": "boolean"}, "linear_damping": {"type": "number", "minimum": 0, "maximum": 1}, "angular_damping": {"type": "number", "minimum": 0, "maximum": 1}},
        },
        "assumptions": {"type": "array", "items": {"type": "string"}}, "rationale": {"type": "string"},
    },
}


INPUT_SYSTEM = """You are the Input Analyst for a mining robotics asset pipeline. Inspect the RGB image and rough prompt. Produce a concise asset brief. SAM3 prompts must be concrete English noun phrases describing one visible object. Material must be exactly one of ceramic, steel, iron, aluminum, copper, rubber, wood, ore, plastic, or unknown; classify cardboard as wood and rock as ore. Do not invent hidden structure or measured material properties. Record uncertainty in assumptions."""

VISUAL_SYSTEM = """You are the Visual Critic. Compare the original RGB with the supplied SAM3 candidates or SAM3D four-view reconstruction. Reject missing parts, wrong subject, severe shape errors, sealed openings, and missing appearance. Choose only one controlled action. Never claim dynamic or physical validation."""

PHYSICS_AUTHOR_SYSTEM = """You are an isolated Physics Author for NVIDIA Isaac Sim 5.1. Use the asset brief and available profiles to produce one schema-version-1 physics spec. Open containers require sdf or convexDecomposition. Static friction >= dynamic friction; restitution and damping are in [0,1]. Movable bodies keep gravity. Enable CCD for thin/small/fast assets. Treat all friction values as priors, not measurements."""

PHYSICS_CRITIC_SYSTEM = """You are an isolated Physics Critic. Review only the persisted asset brief, structural report, and proposed physics spec. Find density/material mismatches, sealed container collision, invalid friction/restitution/damping, unjustified gravity disabling, and missing CCD for thin/small/fast assets. accepted may be true only with zero error findings. A deterministic critic will independently veto unsafe output."""


class ClaudeAssetController:
    """Bounded planner that can only dispatch methods on :class:`AgentTools`."""

    def __init__(self, tools: AgentTools, client: Any | None, model: str = DEFAULT_MODEL, max_calls: int = 8) -> None:
        if max_calls < 0:
            raise ValueError("max_calls cannot be negative")
        self.tools = tools
        self.client = client
        self.model = model
        self.max_calls = max_calls
        self.role_calls: Counter[str] = Counter()
        self.fallback_reasons: list[str] = []
        self._configured_client = client
        self._active_asset_id: str | None = None
        self._unresolved_visual_error = False
        self.policy = RuleBasedPolicy()
        self.author = PhysicsAuthorAgent()

    def run_new(self, image: Path, request: AssetRequest) -> dict[str, Any]:
        # The control plane remains embedded_claude_api even when one or more
        # roles fall back; degradation is captured separately in quality/reasons.
        created = self.tools.create(image, request, controller="embedded_claude_api", max_llm_calls=self.max_calls)
        return self.run(str(created["asset_id"]))

    def run(self, asset_id: str) -> dict[str, Any]:
        manifest = self.tools.store.manifest(asset_id)
        self.tools.store.require_v3(manifest)
        if self._active_asset_id != asset_id:
            self._active_asset_id = asset_id
            self.role_calls.clear()
            self.fallback_reasons.clear()
            self.client = self._configured_client
            self._unresolved_visual_error = False
        else:
            self.role_calls.clear()
            self._unresolved_visual_error = False
        self._restore_call_counts(asset_id)
        if manifest["status"] == AssetStatus.COMPLETE.value:
            return manifest
        if manifest["status"] == AssetStatus.BLOCKED.value:
            return manifest
        if manifest["status"] == AssetStatus.FAILED.value:
            self.tools.store.transition(asset_id, AssetStatus.RUNNING, "Resuming controlled Agent workflow")
        self._restore_fallback_reasons(asset_id)
        self._persist_fallback_reasons(asset_id)
        root = self.tools.store.root(asset_id)
        request = AssetRequest(**self.tools.store.read_json(root / "request.json"))
        brief = self._ensure_brief(asset_id, request)
        if self.tools.store.manifest(asset_id)["phase"] in {
            AssetPhase.SEGMENTATION.value, AssetPhase.INPUT_ANALYSIS.value,
            AssetPhase.RECONSTRUCTION.value, AssetPhase.VISUAL_REVIEW.value,
        }:
            if not self._run_visual(asset_id, brief):
                return self.tools.store.manifest(asset_id)
        if self.tools.store.manifest(asset_id)["phase"] in {AssetPhase.PHYSICS_AUTHORING.value, AssetPhase.PHYSICS_REVIEW.value}:
            if not self._run_physics(asset_id, request, brief):
                return self.tools.store.manifest(asset_id)
        phase = self.tools.store.manifest(asset_id)["phase"]
        if phase in {AssetPhase.USD_AUTHORING.value, AssetPhase.STATIC_VALIDATION.value}:
            if not self.tools.author_usd(asset_id)["ok"]:
                return self.tools.store.manifest(asset_id)
        if self.tools.store.manifest(asset_id)["phase"] == AssetPhase.STATIC_VALIDATION.value:
            degraded = bool(self.fallback_reasons) or not self._has_complete_semantic_review(asset_id)
            proposal = self.policy.physics_proposal(request, brief)
            if degraded and (proposal.get("uses_conservative_fallback") or not self._visual_structural_pass(asset_id)):
                self.tools.store.transition(asset_id, AssetStatus.BLOCKED, "Fallback was generic or visual integrity was not established; final asset withheld")
                return self.tools.store.manifest(asset_id)
            quality = AssetQuality.DEGRADED.value if degraded else AssetQuality.AGENT_REVIEWED.value
            reason = "; ".join(dict.fromkeys(self.fallback_reasons)) if degraded else None
            if degraded and not reason:
                reason = "Anthropic client unavailable; deterministic specialized policies were used."
            used_calls = int(self.tools.store.manifest(asset_id).get("budget", {}).get("llm_calls_used", 0))
            self.tools.finalize(asset_id, quality=quality, fallback_reason=reason, model=self.model if used_calls else None)
        return self.tools.store.manifest(asset_id)

    def _ensure_brief(self, asset_id: str, request: AssetRequest) -> AssetBrief:
        root = self.tools.store.root(asset_id)
        path = root / "agent" / "asset_brief.json"
        if self.tools.store.manifest(asset_id).get("artifacts", {}).get("asset_brief"):
            return AssetBrief.from_dict(self.tools.store.read_json(self.tools.store.artifact_path(asset_id, "asset_brief")))
        fallback = self.policy.asset_brief(request)
        if self.client is None:
            self._record_fallback(asset_id, "Anthropic client unavailable during input analysis")
            brief = fallback
        else:
            try:
                payload = self._call(
                    asset_id, "input_analyst", INPUT_SYSTEM, ASSET_BRIEF_SCHEMA,
                    [self._image_block(self.tools.store.source_path(asset_id)), {"type": "text", "text": json.dumps(request.to_dict(), ensure_ascii=False)}],
                )
                brief = AssetBrief.from_dict(payload)
            except Exception as exc:  # noqa: BLE001 - deterministic fallback is part of the contract.
                self._degrade(asset_id, exc, "input analysis")
                brief = fallback
        self.tools.record_brief(asset_id, brief.to_dict())
        return brief

    def _run_visual(self, asset_id: str, brief: AssetBrief) -> bool:
        root = self.tools.store.root(asset_id)
        source = self.tools.store.source_path(asset_id)
        current_phase = AssetPhase(self.tools.store.manifest(asset_id)["phase"])
        mask_accepted = current_phase in {AssetPhase.RECONSTRUCTION, AssetPhase.VISUAL_REVIEW}
        if not mask_accepted:
            for prompt in brief.sam3_prompts:
                result = self.tools.run_sam3(asset_id, prompt)
                if not result["ok"]:
                    continue
                if self.client is None or self.role_calls["visual_critic"] >= 3:
                    mask_accepted = True
                    break
                decision = self._visual_call(asset_id, "segmentation", source, self.tools._require_artifact(asset_id, "sam3_contact_sheet"), None)
                if decision["action"] == "select_mask" and decision.get("candidate_index") is not None:
                    selected = self.tools.select_mask(asset_id, int(decision["candidate_index"]))
                    mask_accepted = selected["ok"]
                    if mask_accepted:
                        break
                elif decision["action"] == "accept":
                    mask_accepted = True
                    break
                elif decision["action"] == "block":
                    self.tools.record_visual_review(asset_id, decision)
                    return False
                elif decision["action"] == "rewrite_prompt" and decision.get("prompt"):
                    if decision["prompt"] not in brief.sam3_prompts:
                        result = self.tools.run_sam3(asset_id, str(decision["prompt"]))
                        mask_accepted = result["ok"]
                        if mask_accepted:
                            break
        if not mask_accepted:
            self.tools.record_visual_review(asset_id, {"action": "block", "summary": "No acceptable SAM3 mask was found.", "reason": "segmentation attempts exhausted", "findings": []})
            return False
        pending_seeds = [42, 43, 44]
        attempted_reconstructions: set[tuple[str, int]] = set()
        while pending_seeds and len(attempted_reconstructions) < 3:
            seed = pending_seeds.pop(0)
            mask_hash = self.tools.store._sha256(self.tools._require_artifact(asset_id, "sam3_mask"))
            reconstruction_key = (mask_hash, seed)
            if reconstruction_key in attempted_reconstructions:
                continue
            attempted_reconstructions.add(reconstruction_key)
            result = self.tools.run_sam3d(asset_id, seed)
            if not result["ok"]:
                continue
            if self.client is None or self.role_calls["visual_critic"] >= 3:
                self._record_fallback(asset_id, "Semantic visual review unavailable; deterministic visual checks used")
                self.tools.record_visual_review(asset_id, {"action": "accept", "summary": "Deterministic mask and mesh integrity checks passed; semantic review unavailable.", "findings": [], "reviewer": "deterministic_fallback"})
                return True
            views = self.tools._require_artifact(asset_id, "sam3d_contact_sheet")
            mask = self.tools._require_artifact(asset_id, "sam3_contact_sheet")
            decision = self._visual_call(asset_id, "reconstruction", source, mask, views)
            if decision["action"] == "accept":
                self._unresolved_visual_error = False
                self.tools.record_visual_review(asset_id, decision | {"reviewer": "claude_visual_critic_v1"})
                return True
            if decision["action"] == "block":
                self.tools.record_visual_review(asset_id, decision)
                return False
            if decision["action"] == "select_mask" and decision.get("candidate_index") is not None:
                self.tools.record_visual_review(asset_id, decision)
                self.tools.select_mask(asset_id, int(decision["candidate_index"]))
                # A mask change creates a distinct reconstruction input, so try
                # the Critic-selected seed first and then the remaining seeds.
                requested = decision.get("seed") or seed
                pending_seeds = [requested, *[item for item in (42, 43, 44) if item != requested]]
            elif decision["action"] == "rewrite_prompt" and decision.get("prompt"):
                self.tools.record_visual_review(asset_id, decision)
                replacement = self.tools.run_sam3(asset_id, str(decision["prompt"]))
                if not replacement["ok"]:
                    continue
                requested = decision.get("seed") or seed
                pending_seeds = [requested, *[item for item in (42, 43, 44) if item != requested]]
            elif decision["action"] == "rerun_sam3d":
                requested = int(decision["seed"])
                self.tools.record_visual_review(asset_id, decision)
                if (mask_hash, requested) not in attempted_reconstructions:
                    pending_seeds = [requested, *[item for item in pending_seeds if item != requested]]
        self.tools.record_visual_review(asset_id, {"action": "block", "summary": "No acceptable SAM3D reconstruction was found.", "reason": "reconstruction attempts exhausted", "findings": []})
        return False

    def _visual_call(self, asset_id: str, stage: str, source: Path, mask: Path, views: Path | None) -> dict[str, Any]:
        blocks = [self._image_block(source), self._image_block(mask)]
        if views is not None:
            blocks.append(self._image_block(views))
        blocks.append({"type": "text", "text": f"Review stage: {stage}. Choose only an action valid for this stage."})
        try:
            payload = self._call(asset_id, "visual_critic", VISUAL_SYSTEM, VISUAL_DECISION_SCHEMA, blocks)
            allowed = {
                "segmentation": {"accept", "select_mask", "rewrite_prompt", "block"},
                "reconstruction": {"accept", "select_mask", "rewrite_prompt", "rerun_sam3d", "block"},
            }[stage]
            action = payload.get("action")
            has_errors = any(item.get("severity") == "error" for item in payload.get("findings", []))
            if action != "accept" or has_errors:
                self._unresolved_visual_error = True
            required_argument = {"select_mask": "candidate_index", "rewrite_prompt": "prompt", "rerun_sam3d": "seed"}.get(action)
            if action not in allowed:
                raise ValueError(f"visual action {action!r} is invalid during {stage}")
            if required_argument and payload.get(required_argument) is None:
                raise ValueError(f"visual action {action} requires {required_argument}")
            if action == "accept" and has_errors:
                raise ValueError("visual output cannot be accepted with error findings")
        except Exception as exc:  # noqa: BLE001
            self._degrade(asset_id, exc, f"visual critic ({stage})")
            if self._unresolved_visual_error:
                return {"action": "block", "summary": "A prior visual rejection remains unresolved and semantic review became unavailable.", "findings": [{"severity": "error", "code": "unresolved_visual_rejection", "message": "Do not downgrade an explicitly rejected visual result."}], "candidate_index": None, "prompt": None, "seed": None, "reason": "semantic review unavailable after rejection"}
            return {"action": "accept", "summary": "Semantic visual review unavailable; deterministic checks only.", "findings": [], "candidate_index": None, "prompt": None, "seed": None, "reason": None}
        return payload

    def _run_physics(self, asset_id: str, request: AssetRequest, brief: AssetBrief) -> bool:
        root = self.tools.store.root(asset_id)
        materials = self._profiles("materials")
        collisions = self._profiles("collision_profiles")
        proposal = self.policy.physics_proposal(request, brief)
        fallback_spec = self.author.initial_spec(request, proposal, materials, collisions)
        previous_findings: list[dict[str, str]] = []
        completed_rounds = int(self.tools.store.manifest(asset_id).get("attempts", {}).get("physics", 0))
        current_spec_path = root / "physics" / "physics_spec.yaml"
        current_review_relative = self.tools.store.manifest(asset_id).get("artifacts", {}).get("physics_review")
        if completed_rounds and current_review_relative:
            current_review = self.tools.store.read_json(self.tools.store.artifact_path(asset_id, "physics_review"))
            if current_review.get("accepted"):
                self.tools.store.set_phase(asset_id, AssetPhase.USD_AUTHORING, "Resumed accepted physics review")
                return True
            previous_findings = current_review.get("findings", [])
        elif completed_rounds and current_spec_path.is_file():
            pending_spec = yaml.safe_load(self.tools.store.artifact_path(asset_id, "physics_spec").read_text(encoding="utf-8"))
            semantic = self._physics_critic_call(asset_id, brief, pending_spec)
            result = self.tools.check_physics(asset_id, semantic)
            if result["ok"]:
                return True
            previous_findings = result["review"]["findings"]
        if completed_rounds >= 2:
            self.tools.store.transition(asset_id, AssetStatus.BLOCKED, "Physics Author/Critic did not converge within 2 rounds")
            return False
        for round_index in range(completed_rounds, 2):
            if self.client is None:
                spec = self.author.revise(fallback_spec, previous_findings) if round_index else fallback_spec
            else:
                try:
                    context = {
                        "asset_brief": brief.to_dict(), "available_material_profiles": materials,
                        "available_collision_profiles": collisions, "previous_findings": previous_findings,
                        "previous_spec": yaml.safe_load(self.tools.store.artifact_path(asset_id, "physics_spec").read_text(encoding="utf-8")) if self.tools.store.manifest(asset_id).get("artifacts", {}).get("physics_spec") else None,
                    }
                    spec = self._call(asset_id, "physics_author", PHYSICS_AUTHOR_SYSTEM, PHYSICS_SPEC_SCHEMA, [{"type": "text", "text": json.dumps(context, ensure_ascii=False)}])
                except Exception as exc:  # noqa: BLE001
                    self._degrade(asset_id, exc, "physics author")
                    spec = self.author.revise(fallback_spec, previous_findings) if round_index else fallback_spec
            self.tools.submit_physics(asset_id, spec)
            semantic = self._physics_critic_call(asset_id, brief, spec)
            result = self.tools.check_physics(asset_id, semantic)
            if result["ok"]:
                return True
            previous_findings = result["review"]["findings"]
        self.tools.store.transition(asset_id, AssetStatus.BLOCKED, "Physics Author/Critic did not converge within 2 rounds")
        return False

    def _physics_critic_call(self, asset_id: str, brief: AssetBrief, spec: dict[str, Any]) -> dict[str, Any] | None:
        if self.client is None:
            return None
        try:
            return self._call(asset_id, "physics_critic", PHYSICS_CRITIC_SYSTEM, PHYSICS_REVIEW_SCHEMA, [{"type": "text", "text": json.dumps({"asset_brief": brief.to_dict(), "geometry_report": self.tools.store.read_json(self.tools._require_artifact(asset_id, "geometry_report")), "physics_spec": spec}, ensure_ascii=False)}])
        except Exception as exc:  # noqa: BLE001
            self._degrade(asset_id, exc, "physics critic")
            return None

    def _call(self, asset_id: str, role: str, system: str, schema: dict[str, Any], content: list[dict[str, Any]]) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Anthropic client is unavailable")
        used = int(self.tools.store.manifest(asset_id).get("budget", {}).get("llm_calls_used", 0))
        manifest_limit = int(self.tools.store.manifest(asset_id).get("budget", {}).get("max_llm_calls", self.max_calls))
        effective_limit = min(self.max_calls, manifest_limit)
        if used >= effective_limit:
            raise CallBudgetExceeded(f"LLM call budget of {effective_limit} exhausted")
        role_limits = {"input_analyst": 1, "visual_critic": 3, "physics_author": 2, "physics_critic": 2}
        if self.role_calls[role] >= role_limits[role]:
            raise CallBudgetExceeded(f"{role} call budget exhausted")
        self.role_calls[role] += 1
        call_index = self.tools.store.increment(asset_id, "budget", "llm_calls_used")
        decision_dir = self.tools.store.root(asset_id) / "agent" / "decisions"
        path = decision_dir / f"{call_index:03d}_{role}.json"
        artifact_name = f"claude_call_{call_index:03d}_{role}"
        record: dict[str, Any] = {"role": role, "model": self.model, "call_index": call_index, "status": "started"}
        self.tools.store.write_json(path, record)
        self.tools.store.set_artifact(asset_id, artifact_name, path)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            payload = self._extract_payload(response)
        except Exception as exc:
            self.tools.store.write_json(path, record | {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
            self.tools.store.set_artifact(asset_id, artifact_name, path)
            raise
        record |= {"status": "ok", "payload": payload}
        self.tools.store.write_json(path, record)
        self.tools.store.set_artifact(asset_id, artifact_name, path)
        if role in {"physics_author", "physics_critic"}:
            role_dir = "author" if role == "physics_author" else "critic"
            role_path = self.tools.store.root(asset_id) / "physics" / role_dir / f"claude_{self.role_calls[role]:03d}.json"
            self.tools.store.write_json(role_path, record)
        self.tools.store.append_trace(asset_id, {"tool": "claude", "role": role, "model": self.model, "result": "ok"})
        return payload

    @staticmethod
    def _extract_payload(response: Any) -> dict[str, Any]:
        parsed = getattr(response, "parsed_output", None)
        if isinstance(parsed, dict):
            return parsed
        for block in getattr(response, "content", []):
            value = getattr(block, "input", None)
            if isinstance(value, dict):
                return value
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                payload = json.loads(text)
                if isinstance(payload, dict):
                    return payload
        raise ValueError("Claude response did not contain a JSON object")

    @staticmethod
    def _image_block(path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix)
        if media_type is None:
            raise ValueError(f"unsupported image type for Claude: {path}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}

    def _degrade(self, asset_id: str, exc: Exception, stage: str) -> None:
        reason = f"{stage} fallback: {type(exc).__name__}"
        self._record_fallback(asset_id, reason, stage=stage)
        # Disable subsequent remote calls after an API/SDK/parse failure. This
        # makes fallback reproducible and avoids spending budget on a broken path.
        if not isinstance(exc, CallBudgetExceeded):
            self.client = None

    def _record_fallback(self, asset_id: str, reason: str, *, stage: str = "controller") -> None:
        if reason not in self.fallback_reasons:
            self.fallback_reasons.append(reason)
        self._persist_fallback_reasons(asset_id)
        self.tools.store.append_trace(asset_id, {"tool": "claude", "stage": stage, "result": "fallback", "reason": reason})

    def _restore_fallback_reasons(self, asset_id: str) -> None:
        path = self.tools.store.root(asset_id) / "agent" / "fallbacks.json"
        if self.tools.store.manifest(asset_id).get("artifacts", {}).get("fallbacks"):
            payload = self.tools.store.read_json(self.tools.store.artifact_path(asset_id, "fallbacks"))
            for reason in payload.get("reasons", []):
                if isinstance(reason, str) and reason not in self.fallback_reasons:
                    self.fallback_reasons.append(reason)

    def _persist_fallback_reasons(self, asset_id: str) -> None:
        if not self.fallback_reasons:
            return
        path = self.tools.store.root(asset_id) / "agent" / "fallbacks.json"
        self.tools.store.write_json(path, {"reasons": list(dict.fromkeys(self.fallback_reasons))})
        self.tools.store.set_artifact(asset_id, "fallbacks", path)

    def _restore_call_counts(self, asset_id: str) -> None:
        decision_dir = self.tools.store.root(asset_id) / "agent" / "decisions"
        artifact_by_path = {
            relative: name for name, relative in self.tools.store.manifest(asset_id).get("artifacts", {}).items()
            if name.startswith("claude_call_")
        }
        for path in decision_dir.glob("*.json"):
            try:
                relative = self.tools.store.relative(asset_id, path)
                artifact_name = artifact_by_path.get(relative)
                verified = self.tools.store.artifact_path(asset_id, artifact_name) if artifact_name else path
                record = self.tools.store.read_json(verified)
                role = record.get("role")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if role in {"input_analyst", "visual_critic", "physics_author", "physics_critic"}:
                self.role_calls[role] += 1
                payload = record.get("payload", {})
                if role == "visual_critic" and isinstance(payload, dict) and payload.get("action") != "accept":
                    self._unresolved_visual_error = True

    def _profiles(self, directory: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for path in sorted((self.tools.repo_root / "configs" / directory).glob("*.yaml")):
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            result[str(value.get("name", path.stem))] = value
        return result

    def _visual_structural_pass(self, asset_id: str) -> bool:
        manifest = self.tools.store.manifest(asset_id)
        for name in ("sam3_report", "geometry_report"):
            relative = manifest.get("artifacts", {}).get(name)
            if not relative:
                return False
            report = self.tools.store.read_json(self.tools.store.artifact_path(asset_id, name))
            if report.get("status") != "pass":
                return False
            if name == "geometry_report" and "no_vertex_color_or_material" in report.get("warnings", []):
                return False
        return True

    def _has_complete_semantic_review(self, asset_id: str) -> bool:
        root = self.tools.store.root(asset_id)
        manifest = self.tools.store.manifest(asset_id)
        visual_relative = manifest.get("artifacts", {}).get("visual_review")
        physics_relative = manifest.get("artifacts", {}).get("physics_review")
        if not visual_relative or not physics_relative:
            return False
        visual = self.tools.store.read_json(self.tools.store.artifact_path(asset_id, "visual_review"))
        physics = self.tools.store.read_json(self.tools.store.artifact_path(asset_id, "physics_review"))
        input_ok = False
        artifact_by_path = {
            relative: name for name, relative in manifest.get("artifacts", {}).items()
            if name.startswith("claude_call_")
        }
        for path in (root / "agent" / "decisions").glob("*.json"):
            relative = self.tools.store.relative(asset_id, path)
            artifact_name = artifact_by_path.get(relative)
            verified = self.tools.store.artifact_path(asset_id, artifact_name) if artifact_name else path
            record = self.tools.store.read_json(verified)
            if record.get("role") == "input_analyst" and record.get("status") == "ok":
                input_ok = True
                break
        return input_ok and visual.get("reviewer") == "claude_visual_critic_v1" and physics.get("semantic_review") is not None
