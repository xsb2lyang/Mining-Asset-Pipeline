"""Public data models and schemas for the asset-generation agent."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AssetStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"

    # Source-compatible aliases for clients written against manifest v2.
    VISUAL_RUNNING = "running"
    PHYSICS_REVIEW_RUNNING = "running"
    USD_RUNNING = "running"


class AssetPhase(str, Enum):
    INPUT_ANALYSIS = "input_analysis"
    SEGMENTATION = "segmentation"
    RECONSTRUCTION = "reconstruction"
    VISUAL_REVIEW = "visual_review"
    PHYSICS_AUTHORING = "physics_authoring"
    PHYSICS_REVIEW = "physics_review"
    USD_AUTHORING = "usd_authoring"
    STATIC_VALIDATION = "static_validation"
    FINALIZATION = "finalization"


class AssetQuality(str, Enum):
    PENDING = "pending"
    AGENT_REVIEWED = "agent_reviewed"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class AssetRequest:
    prompt: str
    asset_category: str = ""
    target_task: str = ""
    robot_constraints: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AssetBrief:
    object_name: str
    category: str
    sam3_prompts: list[str]
    material: str = "unknown"
    is_open_container: bool = False
    is_slender: bool = False
    is_fast_or_small: bool = False
    is_fixed: bool = False
    target_task: str = ""
    robot_constraints: str = ""
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AssetBrief":
        if not isinstance(value, dict):
            raise ValueError("asset brief must be a JSON object")
        prompts = value.get("sam3_prompts")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
            raise ValueError("sam3_prompts must contain between 1 and 3 prompts")
        if not all(isinstance(item, str) and item.strip() for item in prompts):
            raise ValueError("every SAM3 prompt must be a non-empty string")
        for key in ("object_name", "category"):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError(f"{key} must be a non-empty string")
        bool_fields = ("is_open_container", "is_slender", "is_fast_or_small", "is_fixed")
        for key in bool_fields:
            if key in value and not isinstance(value[key], bool):
                raise ValueError(f"{key} must be boolean")
        assumptions = value.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
            raise ValueError("assumptions must be a list of strings")
        allowed_materials = {"ceramic", "steel", "iron", "aluminum", "copper", "rubber", "wood", "ore", "plastic", "unknown"}
        material = str(value.get("material", "unknown")).strip() or "unknown"
        if material not in allowed_materials:
            raise ValueError(f"material must be one of {sorted(allowed_materials)}")
        return cls(
            object_name=value["object_name"].strip(),
            category=value["category"].strip(),
            sam3_prompts=[item.strip() for item in prompts],
            material=material,
            is_open_container=bool(value.get("is_open_container", False)),
            is_slender=bool(value.get("is_slender", False)),
            is_fast_or_small=bool(value.get("is_fast_or_small", False)),
            is_fixed=bool(value.get("is_fixed", False)),
            target_task=str(value.get("target_task", "")),
            robot_constraints=str(value.get("robot_constraints", "")),
            assumptions=assumptions,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    command: list[str]
    log_path: str


VALID_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.CREATED: {AssetStatus.RUNNING, AssetStatus.BLOCKED, AssetStatus.FAILED},
    AssetStatus.RUNNING: {AssetStatus.RUNNING, AssetStatus.COMPLETE, AssetStatus.BLOCKED, AssetStatus.FAILED},
    AssetStatus.COMPLETE: set(),
    AssetStatus.FAILED: {AssetStatus.RUNNING},
    AssetStatus.BLOCKED: set(),
}
