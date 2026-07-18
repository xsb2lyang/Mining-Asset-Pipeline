"""Public data models for the asset-quality workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class AssetStatus(str, Enum):
    CREATED = "created"
    VISUAL_RUNNING = "visual_running"
    PHYSICS_REVIEW_RUNNING = "physics_review_running"
    BLOCKED = "blocked"
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
class ToolResult:
    returncode: int
    command: list[str]
    log_path: str


VALID_TRANSITIONS: dict[AssetStatus, set[AssetStatus]] = {
    AssetStatus.CREATED: {AssetStatus.VISUAL_RUNNING, AssetStatus.FAILED},
    AssetStatus.VISUAL_RUNNING: {AssetStatus.PHYSICS_REVIEW_RUNNING, AssetStatus.FAILED},
    AssetStatus.PHYSICS_REVIEW_RUNNING: {AssetStatus.USD_RUNNING, AssetStatus.BLOCKED, AssetStatus.FAILED},
    AssetStatus.USD_RUNNING: {AssetStatus.COMPLETE, AssetStatus.FAILED},
    AssetStatus.COMPLETE: set(),
    AssetStatus.FAILED: {AssetStatus.VISUAL_RUNNING},
    AssetStatus.BLOCKED: set(),
}
