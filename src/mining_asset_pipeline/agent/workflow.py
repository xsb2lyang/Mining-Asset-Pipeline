"""Compatibility facade over the controlled AgentTools workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AssetPhase, AssetQuality, AssetRequest, AssetStatus
from .physics_agents import PhysicsAuthorAgent, PhysicsCriticAgent
from .policy import RuleBasedPolicy
from .runner import ToolRunner
from .tools import AgentTools


class AssetWorkflow:
    """Keep the previous two-call API while using manifest-v3 AgentTools."""

    def __init__(
        self,
        repo_root: Path,
        output_root: Path | None = None,
        runner: ToolRunner | None = None,
        policy: RuleBasedPolicy | None = None,
        critic_agent: PhysicsCriticAgent | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.policy = policy or RuleBasedPolicy()
        self.physics_author = PhysicsAuthorAgent()
        self.physics_critic = critic_agent or PhysicsCriticAgent()
        self.tools = AgentTools(self.repo_root, output_root, runner=runner)
        self.store = self.tools.store
        self.runner = self.tools.runner
        self.physics_review_max_rounds = 2

    @property
    def sam3_env(self) -> str:
        return self.tools.sam3_env

    @sam3_env.setter
    def sam3_env(self, value: str) -> None:
        self.tools.sam3_env = value

    @property
    def sam3d_env(self) -> str:
        return self.tools.sam3d_env

    @sam3d_env.setter
    def sam3d_env(self, value: str) -> None:
        self.tools.sam3d_env = value

    def create_asset(self, source_image: Path, request: AssetRequest) -> str:
        result = self.tools.create(source_image, request, controller="embedded_claude_api")
        return str(result["asset_id"])

    def run_visual(self, asset_id: str) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        if AssetStatus(manifest["status"]) not in {AssetStatus.CREATED, AssetStatus.FAILED, AssetStatus.RUNNING}:
            raise ValueError(f"Cannot run visual workflow while status is {manifest['status']}")
        request = AssetRequest(**self.store.read_json(self.store.root(asset_id) / "request.json"))
        brief = self.policy.asset_brief(request)
        self.tools.record_brief(asset_id, brief.to_dict())
        sam3_result: dict[str, Any] | None = None
        for prompt in brief.sam3_prompts:
            sam3_result = self.tools.run_sam3(asset_id, prompt)
            report = sam3_result["report"]
            recommended = report.get("recommended_candidate_index")
            if recommended is not None:
                sam3_result = self.tools.select_mask(asset_id, int(recommended))
            if sam3_result["ok"]:
                break
        if not sam3_result or not sam3_result["ok"]:
            self.store.fail(asset_id, "SAM3 automatic checks failed: " + ", ".join((sam3_result or {}).get("report", {}).get("issues", [])))
            return self.store.manifest(asset_id)
        geometry: dict[str, Any] | None = None
        for seed in (42, 43, 44):
            geometry = self.tools.run_sam3d(asset_id, seed)
            if geometry["ok"]:
                break
        if not geometry or not geometry["ok"]:
            self.store.fail(asset_id, "SAM3D automatic checks failed: " + ", ".join((geometry or {}).get("report", {}).get("issues", [])))
            return self.store.manifest(asset_id)
        self.tools.record_visual_review(asset_id, {
            "action": "accept",
            "summary": "Deterministic mesh and mask integrity checks passed; semantic image review was not available.",
            "findings": [],
            "reviewer": "deterministic_fallback",
        })
        proposal = self.policy.physics_proposal(request, brief)
        proposal["available_material_profiles"] = sorted(self._material_profiles())
        proposal["available_collision_profiles"] = sorted(self._collision_profiles())
        proposal_path = self.store.root(asset_id) / "physics" / "physics_proposal.json"
        self.store.write_json(proposal_path, proposal)
        self.store.set_artifact(asset_id, "physics_proposal", proposal_path)
        return self.store.manifest(asset_id)

    def run_physics_pipeline(self, asset_id: str) -> dict[str, Any]:
        manifest = self.store.manifest(asset_id)
        if manifest.get("phase") not in {AssetPhase.PHYSICS_AUTHORING.value, AssetPhase.PHYSICS_REVIEW.value}:
            raise ValueError("Physics Author/Critic review is not currently running")
        root = self.store.root(asset_id)
        request = AssetRequest(**self.store.read_json(root / "request.json"))
        proposal = self.store.read_json(root / "physics" / "physics_proposal.json")
        spec = self.physics_author.initial_spec(request, proposal, self._material_profiles(), self._collision_profiles())
        for round_index in range(1, self.physics_review_max_rounds + 1):
            self.tools.submit_physics(asset_id, spec)
            semantic = self.physics_critic.review(spec)
            result = self.tools.check_physics(asset_id, semantic.to_dict())
            if result["ok"]:
                authored = self.tools.author_usd(asset_id)
                if not authored["ok"]:
                    return self.store.manifest(asset_id)
                quality = AssetQuality.AGENT_REVIEWED.value if semantic.policy.startswith("claude") else AssetQuality.DEGRADED.value
                fallback = None if quality == AssetQuality.AGENT_REVIEWED.value else "Semantic LLM review unavailable; deterministic specialized rules were used."
                if quality == AssetQuality.DEGRADED.value and proposal.get("uses_conservative_fallback"):
                    self.store.transition(asset_id, AssetStatus.BLOCKED, "Generic physics fallback cannot be delivered unattended")
                    return self.store.manifest(asset_id)
                self.tools.finalize(asset_id, quality=quality, fallback_reason=fallback)
                return self.store.manifest(asset_id)
            if round_index < self.physics_review_max_rounds:
                spec = self.physics_author.revise(spec, result["review"]["findings"])
        self.store.transition(asset_id, AssetStatus.BLOCKED, "Physics Author/Critic did not converge within 2 rounds")
        return self.store.manifest(asset_id)

    def summary(self, asset_id: str) -> dict[str, Any]:
        return self.store.manifest(asset_id)

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
