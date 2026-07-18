"""Rule-first physical-profile proposals."""
from __future__ import annotations

from typing import Any

from .models import AssetRequest


class RuleBasedPolicy:
    """Deterministic default policy; an LLM policy can implement this interface later."""

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
            "uses_conservative_fallback": not (is_container and is_ceramic),
            "rationale": (
                "Prompt/category indicates a ceramic open container; preserve its cavity with SDF collision."
                if is_container and is_ceramic
                else "Prompt/category is insufficient to infer a specialised profile; use traceable generic defaults and flag the assumption."
            ),
        }


class LLMPolicyAdapter:
    """Provider-neutral extension point. It is intentionally not enabled by default."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
