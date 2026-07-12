"""Public data models for the asset-quality workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AssetStatus(str, Enum):
    CREATED = "created"
    VISUAL_RUNNING = "visual_running"
    REVIEW_REQUIRED = "review_required"
    VISUAL_APPROVED = "visual_approved"
    PHYSICS_REVIEW_REQUIRED = "physics_review_required"
    USD_RUNNING = "usd_running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class AssetRequest:
    prompt: str
    asset_category: str = ""
    target_task: str = ""
    robot_constraints: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    issue: str = ""
    feedback: str = ""
    revised_prompt: str = ""
    candidate_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    returncode: int
    command: list[str]
    log_path: str


VALID_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.CREATED: {AssetStatus.VISUAL_RUNNING, AssetStatus.FAILED},
    AssetStatus.VISUAL_RUNNING: {AssetStatus.REVIEW_REQUIRED, AssetStatus.FAILED},
    AssetStatus.REVIEW_REQUIRED: {AssetStatus.VISUAL_RUNNING, AssetStatus.VISUAL_APPROVED, AssetStatus.FAILED},
    AssetStatus.VISUAL_APPROVED: {AssetStatus.PHYSICS_REVIEW_REQUIRED, AssetStatus.FAILED},
    AssetStatus.PHYSICS_REVIEW_REQUIRED: {AssetStatus.USD_RUNNING, AssetStatus.REVIEW_REQUIRED, AssetStatus.FAILED},
    AssetStatus.USD_RUNNING: {AssetStatus.COMPLETE, AssetStatus.FAILED},
    AssetStatus.COMPLETE: set(),
    AssetStatus.FAILED: {AssetStatus.VISUAL_RUNNING},
}
