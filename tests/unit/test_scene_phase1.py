"""Dependency-free tests for the WorldComposer Phase 1 entry point."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import types
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

    def test_marble_video_prompt_uses_official_video_shape(self) -> None:
        prompt = marble._world_prompt("video", "media-123", "  an underground mine tunnel  ")
        self.assertEqual(prompt["type"], "video")
        self.assertEqual(prompt["video_prompt"]["source"], "media_asset")
        self.assertEqual(prompt["video_prompt"]["media_asset_id"], "media-123")
        self.assertEqual(prompt["text_prompt"], "an underground mine tunnel")

    def test_marble_media_asset_id_accepts_documented_and_legacy_fields(self) -> None:
        self.assertEqual(marble._media_asset_id({"media_asset": {"id": "current"}}), "current")
        self.assertEqual(
            marble._media_asset_id({"media_asset": {"media_asset_id": "legacy"}}), "legacy"
        )

    def test_marble_rejects_unsupported_video_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "orbit.avi"
            source.write_bytes(b"video")
            args = marble._parse_args(["--video", str(source)])
            with self.assertRaisesRegex(ValueError, "Video must use one of"):
                marble._source_from_args(args)

    def test_marble_video_run_uploads_and_generates_with_video_prompt(self) -> None:
        class Response:
            def __init__(self, payload: dict | None = None, content: bytes = b"") -> None:
                self.payload = payload or {}
                self.content = content

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self.payload

            def iter_content(self, chunk_size: int):
                del chunk_size
                yield self.content

        class Session:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def post(self, url: str, **kwargs):
                self.posts.append((url, kwargs.get("json", {})))
                if url.endswith("media-assets:prepare_upload"):
                    return Response(
                        {
                            "media_asset": {"id": "media-123"},
                            "upload_info": {
                                "upload_url": "https://upload.example/video",
                                "required_headers": {"x-upload": "yes"},
                            },
                        }
                    )
                if url.endswith("worlds:generate"):
                    return Response(
                        {
                            "operation_id": "world-operation",
                            "done": True,
                            "response": {
                                "id": "world-123",
                                "assets": {"mesh": {"collider_mesh_url": "https://download/collider"}},
                            },
                        }
                    )
                if url.endswith(":export"):
                    return Response(
                        {
                            "operation_id": "export-operation",
                            "done": True,
                            "response": {"url": "https://download/scene"},
                        }
                    )
                raise AssertionError(url)

            def put(self, url: str, **kwargs):
                del url, kwargs
                return Response()

            def get(self, url: str, **kwargs):
                del url, kwargs
                return Response(content=b"artifact")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "orbit.mp4"
            video.write_bytes(b"video")
            session = Session()
            requests_module = types.SimpleNamespace(Session=lambda: session)
            with patch.dict(marble.os.environ, {"WORLDLABS_API_KEY": "test-key"}, clear=True), patch.dict(
                sys.modules, {"requests": requests_module}
            ), contextlib.redirect_stdout(io.StringIO()):
                result = marble.main(
                    [
                        "--video",
                        str(video),
                        "--prompt",
                        "mine tunnel",
                        "--output-root",
                        str(root / "outputs"),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(session.posts[0][1]["kind"], "video")
            world_prompt = session.posts[1][1]["world_prompt"]
            self.assertEqual(world_prompt["type"], "video")
            self.assertEqual(world_prompt["video_prompt"]["media_asset_id"], "media-123")
            self.assertTrue((root / "outputs" / "world-123" / "scene.ply").is_file())

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
