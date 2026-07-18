"""Mock-only tests for the optional Claude physics critic."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.llm_critic import LLMCriticAgent  # noqa: E402


def _valid_spec() -> dict:
    return {
        "schema_version": 1,
        "asset": {"prompt": "a ceramic mug", "category": "cup"},
        "material": {
            "profile": "ceramic",
            "density_kg_m3": 2500,
            "static_friction": 0.5,
            "dynamic_friction": 0.4,
            "restitution": 0.05,
            "friction_combine_mode": "average",
            "restitution_combine_mode": "average",
        },
        "mass": {"mode": "density", "density_kg_m3": 2500},
        "collision": {"profile": "open_container", "enabled": True, "approximation": "sdf"},
        "rigid_body": {"enabled": True, "enable_ccd": True, "disable_gravity": False, "linear_damping": 0.0, "angular_damping": 0.0},
    }


def _client_response(payload: dict) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value.content = [SimpleNamespace(text=json.dumps(payload))]
    return client


class LLMCriticAgentTests(unittest.TestCase):
    def test_happy_path_accepted(self) -> None:
        client = _client_response({"accepted": True, "findings": [], "summary": "Physics spec is safe."})
        review = LLMCriticAgent(client).review(_valid_spec())

        self.assertTrue(review.accepted)
        self.assertEqual(review.findings, [])
        self.assertEqual(review.policy, "claude_physics_critic_v1")
        self.assertEqual(review.to_dict()["policy"], "claude_physics_critic_v1")
        client.messages.create.assert_called_once()

    def test_rejection_with_findings(self) -> None:
        finding = {
            "severity": "error",
            "code": "density_out_of_range",
            "path": "material.density_kg_m3",
            "message": "The density is inconsistent with the selected material.",
        }
        client = _client_response({"accepted": False, "findings": [finding], "summary": "Density needs revision."})
        review = LLMCriticAgent(client).review(_valid_spec())

        self.assertFalse(review.accepted)
        self.assertEqual(review.findings, [finding])
        self.assertEqual(review.summary, "Density needs revision.")

    def test_fallback_on_network_error(self) -> None:
        client = MagicMock()
        client.messages.create.side_effect = ConnectionError("network unavailable")
        review = LLMCriticAgent(client).review(_valid_spec())

        self.assertTrue(review.accepted)
        self.assertIn("[fallback: ConnectionError]", review.summary)
        self.assertEqual(review.policy, "deterministic_physics_critic_v1")

    def test_fallback_on_api_status_error(self) -> None:
        class ApiStatusError(Exception):
            status = 400

        client = MagicMock()
        client.messages.create.side_effect = ApiStatusError("bad request")
        review = LLMCriticAgent(client).review(_valid_spec())

        self.assertTrue(review.accepted)
        self.assertIn("[fallback: ApiStatusError]", review.summary)

    def test_fallback_on_timeout(self) -> None:
        client = MagicMock()
        client.messages.create.side_effect = TimeoutError("request timed out")
        review = LLMCriticAgent(client).review(_valid_spec())

        self.assertTrue(review.accepted)
        self.assertIn("[fallback: TimeoutError]", review.summary)

    def test_parse_response_strips_markdown_fence(self) -> None:
        payload = LLMCriticAgent._parse_response(
            "```json\n{\"accepted\": true, \"summary\": \"OK\", \"findings\": []}\n```"
        )

        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["summary"], "OK")

    def test_parse_response_raises_on_garbage(self) -> None:
        with self.assertRaises(ValueError):
            LLMCriticAgent._parse_response("this is not JSON")


if __name__ == "__main__":
    unittest.main()
