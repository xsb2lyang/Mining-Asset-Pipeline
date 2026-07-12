"""Claude-backed physics critic with a deterministic safety fallback.

This module deliberately does not import the optional ``anthropic`` package.
Callers inject a ready client, which keeps the base pipeline dependency-free and
lets CI exercise all failure paths with mocks.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from .physics_agents import PhysicsCriticAgent, PhysicsReview


class _ClientLike(Protocol):
    messages: Any


SYSTEM_PROMPT = """You are a physics critic for assets that will be simulated in NVIDIA Isaac Sim 5.1.

You receive one JSON physics spec with material, mass, collision, rigid_body,
and asset fields. Check these physics invariants and Isaac Sim safety rules:
1. Material density should match these kg/m^3 ranges: steel 7700-7900, iron
7000-7800, rubber 1000-1200, ceramic 2300-2800, wood 600-900, water 1000,
aluminum 2600-2800, copper 8900, ore 3000-5500. Flag values more than about
30 percent outside the closest applicable range.
2. Open containers (mug, cup, bucket, vessel) must use sdf or
convexDecomposition; convexHull seals their opening.
3. Restitution must be in [0, 1], and static friction must be >= dynamic friction.
4. Linear and angular rigid-body damping must be in [0, 1]. Flag values > 1.
5. Recommend CCD for thin, small, or fast objects.
6. disable_gravity=true requires justification for fixed/infrastructure assets.

Output JSON ONLY, with no preamble or Markdown fence:
{
  "accepted": true,
  "summary": "one-line summary",
  "findings": [
    {"severity": "error" | "warning", "code": "snake_case_code",
     "path": "dotted.path", "message": "human-readable"}
  ]
}
Set accepted=true only when there are zero error findings. Warnings are advisory.
"""


class LLMCriticAgent:
    """Use Claude for semantic review, falling back to rules on any LLM failure."""

    policy_name = "claude_physics_critic_v1"

    def __init__(
        self,
        client: _ClientLike,
        model: str = "claude-sonnet-5-20250514",
        fallback: PhysicsCriticAgent | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.fallback = fallback or PhysicsCriticAgent()

    def review(self, spec: dict[str, Any]) -> PhysicsReview:
        try:
            payload = self._parse_response(self._call_llm(spec))
            return self._review_from_payload(payload)
        except Exception as exc:  # noqa: BLE001 - every LLM failure must preserve pipeline availability.
            fallback_review = self.fallback.review(spec)
            return PhysicsReview(
                accepted=fallback_review.accepted,
                findings=fallback_review.findings,
                summary=f"{fallback_review.summary} [fallback: {type(exc).__name__}]",
                policy=fallback_review.policy,
            )

    def _call_llm(self, spec: dict[str, Any]) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(spec, ensure_ascii=False)}],
        )
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response: Any) -> str:
        for block in getattr(response, "content", []):
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                return text
        raise ValueError("LLM response has no text content")

    @staticmethod
    def _parse_response(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) < 2 or not lines[-1].strip().startswith("```"):
                raise ValueError("LLM Markdown fence is not closed")
            language = lines[0].strip()[3:].strip().lower()
            if language not in {"", "json"}:
                raise ValueError(f"Unsupported fenced response language: {language}")
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("LLM response is not a JSON object")
        return payload

    def _review_from_payload(self, payload: dict[str, Any]) -> PhysicsReview:
        accepted = payload.get("accepted")
        findings = payload.get("findings", [])
        summary = payload.get("summary")
        if not isinstance(accepted, bool):
            raise ValueError("LLM response field 'accepted' must be a boolean")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("LLM response field 'summary' must be a non-empty string")
        if not isinstance(findings, list) or not all(isinstance(finding, dict) for finding in findings):
            raise ValueError("LLM response field 'findings' must be a list of objects")
        normalised_findings: list[dict[str, str]] = []
        for finding in findings:
            severity = finding.get("severity")
            code = finding.get("code")
            path = finding.get("path")
            message = finding.get("message")
            if severity not in {"error", "warning"} or not all(isinstance(value, str) and value for value in (code, path, message)):
                raise ValueError("Every LLM finding needs severity, code, path, and message")
            normalised_findings.append({"severity": severity, "code": code, "path": path, "message": message})
        if accepted and any(finding["severity"] == "error" for finding in normalised_findings):
            raise ValueError("LLM accepted a response that includes error findings")
        return PhysicsReview(
            accepted=accepted,
            findings=normalised_findings,
            summary=summary,
            policy=self.policy_name,
        )
