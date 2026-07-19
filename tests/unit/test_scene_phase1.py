"""Dependency-free tests for the WorldComposer Phase 1 entry point."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_scene_phase1 as phase1  # noqa: E402
import generate_marble_world as marble  # noqa: E402


class ScenePhase1Tests(unittest.TestCase):
    def test_marble_client_requires_environment_key(self) -> None:
        with patch.dict(marble.os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(marble.main(["--image", "unused.jpg"]), 2)

    def test_slug_normalizes_a_semantic_scene_name(self) -> None:
        self.assertEqual(phase1._slug("Subterranean Tunnel / Phase 1"), "subterranean_tunnel_phase_1")

    def test_require_input_rejects_wrong_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.txt"
            path.write_text("data", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be a .ply"):
                phase1._require_input(path, ".ply", "PLY")

    def test_main_builds_nurec_and_portable_scene_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ply = root / "scene source.ply"
            glb = root / "collider source.glb"
            isaac = root / "isaac"
            output = root / "outputs"
            ply.write_bytes(b"ply")
            glb.write_bytes(b"glb")
            isaac.mkdir()
            (isaac / "python.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            commands: list[list[str]] = []

            def fake_run(command, *, env, log_path):
                command = list(command)
                commands.append(command)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("ok\n", encoding="utf-8")
                if "threedgrut.export.scripts.transcode" in command:
                    Path(command[command.index("-o") + 1]).write_bytes(b"usdz")
                    return
                mesh = Path(command[command.index("--mesh-usd") + 1])
                scene = Path(command[command.index("--out-usd") + 1])
                report = Path(command[command.index("--validation-report") + 1])
                mesh.write_bytes(b"mesh")
                scene.write_bytes(b"scene")
                report.write_text(
                    json.dumps(
                        {
                            "passed": True,
                            "checks": {"meters_per_unit_is_meter": True},
                        }
                    ),
                    encoding="utf-8",
                )

            with patch.object(phase1.shutil, "which", return_value="/usr/bin/conda"), patch.object(
                phase1, "_run", side_effect=fake_run
            ), contextlib.redirect_stdout(io.StringIO()):
                result = phase1.main(
                    [
                        "--ply", str(ply),
                        "--glb", str(glb),
                        "--scene-name", "Test Tunnel",
                        "--output-root", str(output),
                        "--isaac-sim-path", str(isaac),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertIn("--format", commands[0])
            self.assertEqual(commands[0][commands[0].index("--format") + 1], "nurec")
            staged_glb = commands[1][commands[1].index("--glb") + 1]
            self.assertEqual(Path(staged_glb).name, "test_tunnel_collider.glb")
            manifest = json.loads((output / "test_tunnel" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["artifacts"]["scene_usd"], "final/test_tunnel.usd")

    def test_existing_bundle_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ply = root / "scene.ply"
            glb = root / "scene.glb"
            isaac = root / "isaac"
            output = root / "outputs" / "same_scene"
            ply.write_bytes(b"ply")
            glb.write_bytes(b"glb")
            isaac.mkdir()
            (isaac / "python.sh").write_text("", encoding="utf-8")
            output.mkdir(parents=True)
            with patch.object(phase1.shutil, "which", return_value="conda"), contextlib.redirect_stderr(io.StringIO()):
                result = phase1.main(
                    [
                        "--ply", str(ply),
                        "--glb", str(glb),
                        "--scene-name", "same scene",
                        "--output-root", str(root / "outputs"),
                        "--isaac-sim-path", str(isaac),
                    ]
                )
            self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
