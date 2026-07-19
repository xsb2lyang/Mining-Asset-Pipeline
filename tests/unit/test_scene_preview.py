"""Fast tests for scene preview path and camera-path helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import record_scene_preview as preview  # noqa: E402


class ScenePreviewTests(unittest.TestCase):
    def test_default_visual_mode_is_auto(self) -> None:
        args = preview._parse_args(["--scene", "scene.usd"])
        self.assertEqual(args.visual_mode, "auto")
        self.assertEqual(args.bounds_prim, "/World/Collider")
        self.assertFalse(args.show_ui)

    def test_flythrough_moves_along_longest_horizontal_axis(self) -> None:
        poses = list(preview._flythrough_poses((-2.0, -20.0, 0.0), (2.0, 20.0, 4.0), 3))
        self.assertLess(poses[0][0][1], poses[-1][0][1])
        self.assertEqual(poses[0][0][0], 0.0)
        self.assertGreater(poses[0][1][1], poses[0][0][1])

    def test_orbit_returns_requested_frame_count(self) -> None:
        poses = list(preview._orbit_poses((-2.0, -3.0, 0.0), (2.0, 3.0, 4.0), 7))
        self.assertEqual(len(poses), 7)
        self.assertNotEqual(poses[0][0], poses[3][0])


if __name__ == "__main__":
    unittest.main()
