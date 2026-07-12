"""Rule-first diagnostics and physical-profile proposals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import AssetRequest, ReviewDecision


REVIEW_ISSUES = (
    "segmentation_incorrect",
    "missing_part",
    "shape_incorrect",
    "key_structure_incorrect",
    "appearance_incorrect",
    "other",
)


@dataclass(frozen=True)
class RepairAction:
    action: str
    explanation: str


class RuleBasedPolicy:
    """Deterministic default policy; an LLM policy can implement this interface later."""

    def repair_action(self, decision: ReviewDecision) -> RepairAction:
        if decision.issue == "segmentation_incorrect":
            return RepairAction("rerun_sam3", "Use the revised prompt or selected mask candidate.")
        if decision.issue in {"missing_part", "shape_incorrect", "key_structure_incorrect", "appearance_incorrect"}:
            return RepairAction("rerun_sam3d", "Regenerate the mesh with the next deterministic SAM3D seed.")
        return RepairAction("human_input_required", "The current workflow cannot safely repair this feedback automatically.")

    def physics_proposal(self, request: AssetRequest) -> dict[str, Any]:
        text = f"{request.prompt} {request.asset_category}".lower()
        container_words = ("cup", "mug", "bucket", "container", "vessel", "杯", "桶", "容器")
        ceramic_words = ("ceramic", "porcelain", "mug", "cup", "陶瓷", "马克杯")
        is_container = any(word in text for word in container_words)
        is_ceramic = any(word in text for word in ceramic_words)
        return {
            "policy": "rule_based_v1",
            "material_profile": "ceramic" if is_ceramic else None,
            "collision_profile": "open_container" if is_container else None,
            "requires_human_selection": not (is_container and is_ceramic),
            "rationale": (
                "Prompt/category indicates a ceramic open container; preserve its cavity with SDF collision."
                if is_container and is_ceramic
                else "Prompt/category is insufficient to safely infer both material and collision profiles."
            ),
        }


class LLMPolicyAdapter:
    """Provider-neutral extension point. It is intentionally not enabled by default."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
