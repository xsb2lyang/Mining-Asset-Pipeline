"""Deterministic Physics Author/Critic roles for the Loop 1 physics handoff.

The classes intentionally do not call a model.  They expose small, provider-neutral
roles now, while keeping every decision reproducible and persisted per asset.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any

from .models import AssetRequest


ALLOWED_APPROXIMATIONS = {"convexHull", "convexDecomposition", "sdf"}
ALLOWED_COMBINE_MODES = {"average", "min", "multiply", "max"}
DENSITY_RANGES = {
    "ceramic": (2300.0, 2800.0), "steel": (7700.0, 7900.0), "iron": (7000.0, 7800.0),
    "aluminum": (2600.0, 2800.0), "copper": (8700.0, 9200.0), "rubber": (1000.0, 1200.0),
    "wood": (600.0, 900.0), "ore": (3000.0, 5500.0), "plastic": (900.0, 1500.0),
}


@dataclass(frozen=True)
class PhysicsReview:
    accepted: bool
    findings: list[dict[str, str]]
    summary: str
    policy: str = "deterministic_physics_critic_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": "physics_critic",
            "policy": self.policy,
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
            "mass": {"mode": "density", "density_kg_m3": float(material["density_kg_m3"]), "mass_kg": None},
            "collision": {
                "profile": collision_name,
                "enabled": True,
                "approximation": str(collision["preferred_approximation"]),
                "fallback_approximation": collision.get("fallback_approximation"),
                "production_strategy": collision.get("production_strategy", "single_collider"),
            },
            "rigid_body": {
                "enabled": True,
                "enable_ccd": bool(proposal.get("enable_ccd", True)),
                "disable_gravity": bool(proposal.get("disable_gravity", False)),
                "linear_damping": 0.0,
                "angular_damping": 0.0,
            },
            "assumptions": [
                "The mesh is a single movable rigid asset; articulated joints are outside Loop 1.",
                "Density and contact coefficients are repository engineering priors, not measured values for this asset.",
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
        if "material.density_range" in codes:
            profile = str(material.get("profile", ""))
            if profile in DENSITY_RANGES:
                low, high = DENSITY_RANGES[profile]
                material["density_kg_m3"] = (low + high) / 2.0
                if mass.get("mode") == "density":
                    mass["density_kg_m3"] = material["density_kg_m3"]
        if "mass.invalid" in codes:
            density = float(material.get("density_kg_m3", 1000.0))
            mass.clear()
            mass.update({"mode": "density", "density_kg_m3": max(density, 1.0), "mass_kg": None})
        if "mass.density_mismatch" in codes:
            mass.clear()
            mass.update({"mode": "density", "density_kg_m3": float(material.get("density_kg_m3", 1000.0)), "mass_kg": None})
        if "collision.invalid" in codes:
            collision["enabled"] = True
            collision["approximation"] = "convexDecomposition"
        if "rigid_body.invalid" in codes:
            rigid_body.update({"enabled": True, "enable_ccd": True, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0})
        if "rigid_body.damping_range" in codes:
            for field in ("linear_damping", "angular_damping"):
                rigid_body[field] = min(1.0, max(0.0, float(rigid_body.get(field, 0.0))))
        if "rigid_body.gravity_unjustified" in codes:
            rigid_body["disable_gravity"] = False
        if "rigid_body.ccd_recommended" in codes:
            rigid_body["enable_ccd"] = True
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

        def warning(code: str, path: str, message: str) -> None:
            findings.append({"severity": "warning", "code": code, "path": path, "message": message})

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
            static_value, dynamic_value = float(static), float(dynamic)
            if not math.isfinite(static_value) or not math.isfinite(dynamic_value) or static_value < 0 or dynamic_value < 0 or static_value < dynamic_value:
                error("material.friction_order", "material", "Friction must be non-negative and static friction must be >= dynamic friction.")
        except (TypeError, ValueError):
            error("material.friction_order", "material", "Both static and dynamic friction must be numeric.")
        try:
            restitution_value = float(restitution)
            if not math.isfinite(restitution_value) or not 0 <= restitution_value <= 1:
                error("material.restitution_range", "material.restitution", "Restitution must be in [0, 1].")
        except (TypeError, ValueError):
            error("material.restitution_range", "material.restitution", "Restitution must be numeric.")
        if material.get("friction_combine_mode") not in ALLOWED_COMBINE_MODES or material.get("restitution_combine_mode") not in ALLOWED_COMBINE_MODES:
            error("material.combine_mode", "material", "Combine modes must be one of average, min, multiply, max.")
        profile = str(material.get("profile", ""))
        if profile not in {*DENSITY_RANGES, "generic"}:
            error("material.unknown_profile", "material.profile", "Material profile must name a repository-controlled profile.")
        if profile in DENSITY_RANGES:
            try:
                density = float(material.get("density_kg_m3"))
                low, high = DENSITY_RANGES[profile]
                if not math.isfinite(density) or density < low * 0.7 or density > high * 1.3:
                    error("material.density_range", "material.density_kg_m3", f"Density is implausible for {profile}; expected approximately {low:g}-{high:g} kg/m^3.")
            except (TypeError, ValueError):
                error("material.density_range", "material.density_kg_m3", "Material density must be numeric.")

        mode = mass.get("mode")
        if mode == "density":
            value = mass.get("density_kg_m3")
        elif mode == "mass":
            value = mass.get("mass_kg")
        else:
            value = None
        try:
            numeric_value = float(value)
            if mode not in {"density", "mass"} or not math.isfinite(numeric_value) or numeric_value <= 0:
                error("mass.invalid", "mass", "Use exactly one positive density_kg_m3 or mass_kg.")
        except (TypeError, ValueError):
            error("mass.invalid", "mass", "Use exactly one positive density_kg_m3 or mass_kg.")

        approximation = collision.get("approximation")
        collision_profile = collision.get("profile")
        if collision_profile not in {"open_container", "generic_solid", "slender_solid"}:
            error("collision.unknown_profile", "collision.profile", "Collision profile must name a repository-controlled profile.")
        if collision.get("enabled") is not True or approximation not in ALLOWED_APPROXIMATIONS:
            error("collision.invalid", "collision", "Collision must be enabled and use convexHull, convexDecomposition, or sdf.")
        asset_text = f"{(asset or {}).get('prompt', '')} {(asset or {}).get('category', '')}".lower()
        container = collision_profile == "open_container" or any(word in asset_text for word in ("cup", "mug", "bucket", "container", "vessel", "tube", "杯", "桶", "容器", "筒"))
        if container and approximation == "convexHull":
            error("collision.container_sealed", "collision.approximation", "convexHull seals a container opening; use sdf or convexDecomposition.")
        if mode == "density":
            try:
                material_density = float(material.get("density_kg_m3"))
                mass_density = float(mass.get("density_kg_m3"))
                if not math.isfinite(material_density) or not math.isfinite(mass_density) or abs(material_density - mass_density) > max(1e-6, abs(material_density) * 1e-6):
                    error("mass.density_mismatch", "mass.density_kg_m3", "MassAPI density must match the selected material density.")
            except (TypeError, ValueError):
                error("mass.density_mismatch", "mass.density_kg_m3", "Material and mass density must be finite numeric values.")

        if isinstance(rigid_body, dict):
            for field in ("linear_damping", "angular_damping"):
                try:
                    damping_value = float(rigid_body.get(field))
                    if not math.isfinite(damping_value) or not 0 <= damping_value <= 1:
                        error("rigid_body.damping_range", f"rigid_body.{field}", f"{field} must be in [0, 1].")
                except (TypeError, ValueError):
                    error("rigid_body.damping_range", f"rigid_body.{field}", f"{field} must be numeric.")
            fixed = any(word in asset_text for word in ("fixed", "wall", "infrastructure", "固定", "墙"))
            slender = any(word in asset_text for word in ("thin", "small", "fast", "rod", "bolt", "pipe", "tube", "杆", "管"))
            if rigid_body.get("disable_gravity") is True and not fixed:
                error("rigid_body.gravity_unjustified", "rigid_body.disable_gravity", "Gravity may only be disabled for fixed or infrastructure assets.")
            if slender and rigid_body.get("enable_ccd") is not True:
                warning("rigid_body.ccd_recommended", "rigid_body.enable_ccd", "CCD is recommended for thin, small, or fast assets.")

        errors = [finding for finding in findings if finding["severity"] == "error"]
        if errors:
            return PhysicsReview(False, findings, f"Rejected with {len(errors)} deterministic error finding(s).")
        if findings:
            return PhysicsReview(True, findings, f"Accepted with {len(findings)} advisory warning(s).")
        return PhysicsReview(True, [], "Accepted: schema and physics invariants pass.")
