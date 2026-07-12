"""Unit tests for the rule-based prompt rewriter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.prompt_rewriter import known_keywords, rewrite_prompt  # noqa: E402


class RewritePromptTests(unittest.TestCase):
    def test_abstract_trolley_is_rewritten(self) -> None:
        out = rewrite_prompt("a platform trolley")
        self.assertEqual(out, "a flatbed cart with handle and wheels")

    def test_category_also_drives_rewrite(self) -> None:
        out = rewrite_prompt("thing", category="ore")
        self.assertEqual(out, "a pile of rough mineral rocks")

    def test_category_takes_precedence_over_empty_prompt(self) -> None:
        out = rewrite_prompt("", category="drill")
        self.assertEqual(out, "a hand-held drill with rotating bit")

    def test_concrete_prompt_is_returned_unchanged(self) -> None:
        concrete = "a flatbed cart with handle and wheels"
        self.assertEqual(rewrite_prompt(concrete), concrete)

    def test_unknown_keyword_falls_back(self) -> None:
        self.assertEqual(rewrite_prompt("a unicorn"), "a unicorn")

    def test_case_insensitive(self) -> None:
        self.assertEqual(rewrite_prompt("A TROLLEY"), "a flatbed cart with handle and wheels")

    def test_whole_word_match_avoids_substring_collisions(self) -> None:
        # "rocked" should not match "rock" via whole-word check
        self.assertEqual(rewrite_prompt("rocked chair"), "rocked chair")

    def test_priority_more_specific_keyword_wins(self) -> None:
        # "drill rig" should beat "drill" because it's listed first and longer
        out = rewrite_prompt("a drill rig")
        self.assertEqual(out, "a mining drill rig with mast and rotating bit")

    def test_empty_inputs_return_empty(self) -> None:
        self.assertEqual(rewrite_prompt(""), "")
        self.assertEqual(rewrite_prompt("", ""), "")

    def test_known_keywords_is_sorted(self) -> None:
        kw = known_keywords()
        self.assertEqual(kw, sorted(kw))
        self.assertIn("trolley", kw)
        self.assertIn("drill", kw)


if __name__ == "__main__":
    unittest.main()