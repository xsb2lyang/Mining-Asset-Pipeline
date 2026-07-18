"""Rule-first semantic and physical-profile proposals."""
from __future__ import annotations

from typing import Any

from .models import AssetBrief, AssetRequest
from .prompt_rewriter import rewrite_prompt


class RuleBasedPolicy:
    """Deterministic fallback used when no host or embedded LLM is available."""

    MATERIAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("ceramic", ("ceramic", "porcelain", "mug", "cup", "陶瓷", "瓷")),
        ("steel", ("steel", "drill rod", "bolt", "钢", "钻杆", "锚杆")),
        ("iron", ("iron", "cast iron", "铁")),
        ("aluminum", ("aluminum", "aluminium", "铝")),
        ("copper", ("copper", "铜")),
        ("rubber", ("rubber", "tire", "tyre", "橡胶", "轮胎")),
        ("wood", ("wood", "wooden", "cardboard", "timber", "木", "纸板", "纸筒")),
        ("ore", ("ore", "rock", "stone", "coal", "矿石", "岩石", "煤")),
        ("plastic", ("plastic", "polymer", "塑料")),
    )

    def asset_brief(self, request: AssetRequest) -> AssetBrief:
        text = f"{request.prompt} {request.asset_category}".lower()
        container = any(word in text for word in ("cup", "mug", "bucket", "tube", "container", "vessel", "杯", "桶", "筒", "容器"))
        slender = any(word in text for word in ("rod", "bolt", "drill", "pipe", "tube", "cable", "杆", "管", "锚", "钻"))
        fixed = any(word in text for word in ("fixed", "wall", "infrastructure", "anchored", "固定", "墙", "基础设施"))
        material = "unknown"
        for profile, words in self.MATERIAL_KEYWORDS:
            if any(word in text for word in words):
                material = profile
                break
        normalized = rewrite_prompt(request.prompt, request.asset_category).strip() or request.prompt.strip()
        prompts = list(dict.fromkeys([normalized, request.prompt.strip()]))[:3]
        category = request.asset_category.strip() or ("open_container" if container else "slender_object" if slender else "object")
        assumptions: list[str] = []
        if not request.asset_category:
            assumptions.append(f"Category inferred as {category} from available semantics.")
        if material == "unknown":
            assumptions.append("Material could not be identified deterministically.")
        assumptions.append("Unless marked fixed, the asset is treated as one movable gravity-affected rigid body.")
        return AssetBrief(
            object_name=request.prompt.strip() or category,
            category=category,
            sam3_prompts=prompts,
            material=material,
            is_open_container=container,
            is_slender=slender,
            is_fast_or_small=slender,
            is_fixed=fixed,
            target_task=request.target_task,
            robot_constraints=request.robot_constraints,
            assumptions=assumptions,
        )

    def physics_proposal(self, request: AssetRequest, brief: AssetBrief | None = None) -> dict[str, Any]:
        brief = brief or self.asset_brief(request)
        material = brief.material if brief.material != "unknown" else None
        collision = "open_container" if brief.is_open_container else "slender_solid" if brief.is_slender else None
        specialized = material is not None and collision is not None
        return {
            "policy": "rule_based_v2",
            "material_profile": material,
            "collision_profile": collision,
            "uses_conservative_fallback": not specialized,
            "specialized": specialized,
            "enable_ccd": brief.is_fast_or_small or brief.is_slender,
            "disable_gravity": brief.is_fixed,
            "rationale": (
                f"Rule semantics selected {material or 'generic'} material and {collision or 'generic_solid'} collision."
                if specialized
                else "Semantics are insufficient for both specialised material and collision profiles; unattended fallback must not claim full review."
            ),
        }


class LLMPolicyAdapter:
    """Provider-neutral compatibility extension point."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
