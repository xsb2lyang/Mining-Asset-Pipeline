"""Deterministic Physics Author/Critic roles for the Loop 1 physics handoff.

The classes intentionally do not call a model.  They expose small, provider-neutral
roles now, while keeping every decision reproducible and persisted per asset.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .models import AssetRequest


ALLOWED_APPROXIMATIONS = {"convexHull", "convexDecomposition", "sdf"}
ALLOWED_COMBINE_MODES = {"average", "min", "multiply", "max"}


@dataclass(frozen=True)
class PhysicsReview:
    accepted: bool
    findings: list[dict[str, str]]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "physics_critic",
            "policy": "deterministic_physics_critic_v1",
            "accepted": self.accepted,
            "summary": self.summary,
            "findings": self.findings,
        }


class PhysicsAuthorAgent:
    """Creates and revises a concrete, tool-ready physics specification."""

    policy_name = "deterministic_physics_author_v1"

    def initial_spec(
        self,
        request: AssetRequest,
        proposal: dict[str, Any],
        materials: dict[str, dict[str, Any]],
        collisions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        material_name = proposal.get("material_profile") or "generic"
        collision_name = proposal.get("collision_profile") or "generic_solid"
        if material_name not in materials:
            material_name = "generic"
        if collision_name not in collisions:
            collision_name = "generic_solid"
        material = deepcopy(materials[material_name])
        collision = deepcopy(collisions[collision_name])
        used_fallback = material_name == "generic" or collision_name == "generic_solid"
        return {
            "schema_version": 1,
            "author": {"role": "physics_author", "policy": self.policy_name},
            "asset": {
                "prompt": request.prompt,
                "category": request.asset_category or "unspecified",
                "target_task": request.target_task,
                "robot_constraints": request.robot_constraints,
            },
            "material": {
                "profile": material_name,
                "density_kg_m3": float(material["density_kg_m3"]),
                "static_friction": float(material["static_friction"]),
                "dynamic_friction": float(material["dynamic_friction"]),
                "restitution": float(material["restitution"]),
                "friction_combine_mode": str(material.get("friction_combine_mode", "average")),
                "restitution_combine_mode": str(material.get("restitution_combine_mode", "average")),
            },
            "mass": {"mode": "density", "density_kg_m3": float(material["density_kg_m3"])},
            "collision": {
                "profile": collision_name,
                "enabled": True,
                "approximation": str(collision["preferred_approximation"]),
                "fallback_approximation": collision.get("fallback_approximation"),
                "production_strategy": collision.get("production_strategy", "single_collider"),
            },
            "rigid_body": {
                "enabled": True,
                "enable_ccd": True,
                "disable_gravity": False,
                "linear_damping": 0.0,
                "angular_damping": 0.0,
            },
            "assumptions": [
                "The mesh is a single movable rigid asset; articulated joints are outside Loop 1.",
                *( ["Used generic material/collision fallbacks because prompt semantics were insufficient."] if used_fallback else [] ),
            ],
            "rationale": proposal.get("rationale", "Rule-based profile selection."),
        }

    def revise(self, spec: dict[str, Any], findings: list[dict[str, str]]) -> dict[str, Any]:
        """Apply only mechanical fixes requested by the Critic; never invent geometry."""
        revised = deepcopy(spec)
        material = revised.setdefault("material", {})
        collision = revised.setdefault("collision", {})
        mass = revised.setdefault("mass", {})
        rigid_body = revised.setdefault("rigid_body", {})
        codes = {finding.get("code") for finding in findings}
        if "collision.container_sealed" in codes:
            collision["approximation"] = "sdf"
        if "material.friction_order" in codes:
            material["static_friction"] = max(float(material.get("static_friction", 0.5)), float(material.get("dynamic_friction", 0.4)))
        if "material.restitution_range" in codes:
            material["restitution"] = min(1.0, max(0.0, float(material.get("restitution", 0.05))))
        if "material.combine_mode" in codes:
            material["friction_combine_mode"] = "average"
            material["restitution_combine_mode"] = "average"
        if "mass.invalid" in codes:
            density = float(material.get("density_kg_m3", 1000.0))
            mass.clear()
            mass.update({"mode": "density", "density_kg_m3": max(density, 1.0)})
        if "collision.invalid" in codes:
            collision["enabled"] = True
            collision["approximation"] = "convexDecomposition"
        if "rigid_body.invalid" in codes:
            rigid_body.update({"enabled": True, "enable_ccd": True, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0})
        revised.setdefault("revision_notes", []).append(
            "Author applied deterministic revisions for: " + ", ".join(sorted(code for code in codes if code))
        )
        return revised


class PhysicsCriticAgent:
    """Checks schema invariants and safety-critical collision constraints."""

    policy_name = "deterministic_physics_critic_v1"

    def review(self, spec: dict[str, Any]) -> PhysicsReview:
        findings: list[dict[str, str]] = []

        def error(code: str, path: str, message: str) -> None:
            findings.append({"severity": "error", "code": code, "path": path, "message": message})

        material = spec.get("material")
        collision = spec.get("collision")
        mass = spec.get("mass")
        rigid_body = spec.get("rigid_body")
        if spec.get("schema_version") != 1:
            error("schema.version", "schema_version", "schema_version must be 1.")
        asset = spec.get("asset")
        if not isinstance(asset, dict) or not isinstance(asset.get("prompt"), str) or not asset["prompt"].strip():
            error("asset.prompt", "asset.prompt", "The source prompt is required for provenance.")
        if not isinstance(material, dict):
            error("material.invalid", "material", "Material settings are required.")
            material = {}
        if not isinstance(collision, dict):
            error("collision.invalid", "collision", "Collision settings are required.")
            collision = {}
        if not isinstance(mass, dict):
            error("mass.invalid", "mass", "Mass or density settings are required.")
            mass = {}
        if not isinstance(rigid_body, dict) or not isinstance(rigid_body.get("enabled"), bool):
            error("rigid_body.invalid", "rigid_body", "Rigid-body settings must explicitly enable or disable the body.")
            rigid_body = {}

        static = material.get("static_friction")
        dynamic = material.get("dynamic_friction")
        restitution = material.get("restitution")
        try:
            if float(static) < 0 or float(dynamic) < 0 or float(static) < float(dynamic):
                error("material.friction_order", "material", "Friction must be non-negative and static friction must be >= dynamic friction.")
        except (TypeError, ValueError):
            error("material.friction_order", "material", "Both static and dynamic friction must be numeric.")
        try:
            if not 0 <= float(restitution) <= 1:
                error("material.restitution_range", "material.restitution", "Restitution must be in [0, 1].")
        except (TypeError, ValueError):
            error("material.restitution_range", "material.restitution", "Restitution must be numeric.")
        if material.get("friction_combine_mode") not in ALLOWED_COMBINE_MODES or material.get("restitution_combine_mode") not in ALLOWED_COMBINE_MODES:
            error("material.combine_mode", "material", "Combine modes must be one of average, min, multiply, max.")

        mode = mass.get("mode")
        if mode == "density":
            value = mass.get("density_kg_m3")
        elif mode == "mass":
            value = mass.get("mass_kg")
        else:
            value = None
        try:
            if mode not in {"density", "mass"} or float(value) <= 0:
                error("mass.invalid", "mass", "Use exactly one positive density_kg_m3 or mass_kg.")
        except (TypeError, ValueError):
            error("mass.invalid", "mass", "Use exactly one positive density_kg_m3 or mass_kg.")

        approximation = collision.get("approximation")
        if collision.get("enabled") is not True or approximation not in ALLOWED_APPROXIMATIONS:
            error("collision.invalid", "collision", "Collision must be enabled and use convexHull, convexDecomposition, or sdf.")
        container = collision.get("profile") == "open_container"
        if container and approximation == "convexHull":
            error("collision.container_sealed", "collision.approximation", "convexHull seals a container opening; use sdf or convexDecomposition.")

        if findings:
            return PhysicsReview(False, findings, f"Rejected with {len(findings)} deterministic finding(s).")
        return PhysicsReview(True, [], "Accepted: schema and physics invariants pass.")
