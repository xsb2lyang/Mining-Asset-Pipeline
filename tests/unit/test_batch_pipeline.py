"""Unit tests for scripts/batch_pipeline.py without running GPU workloads."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_pipeline  # noqa: E402


def _items(count: int) -> list[dict[str, object]]:
    return [
        {
            "image": f"/dataset/item_{index}.jpg",
            "prompt": f"asset {index}",
            "asset_category": "trolley",
            "rewrite_prompt": index == 1,
        }
        for index in range(1, count + 1)
    ]


def _completed(index: int, code: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    stdout = ""
    if code == 0:
        stdout = f"asset_id=asset-{index}\nfinal_usd=/outputs/asset-{index}/final/asset.usd\n"
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


class BatchPipelineTests(unittest.TestCase):
    def _write_manifest(self, root: Path, items: list[dict[str, object]]) -> Path:
        path = root / "batch.json"
        path.write_text(json.dumps(items), encoding="utf-8")
        return path

    def test_happy_path_writes_summary_and_forwards_cli_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(root, _items(3))
            summary_path = root / "summary.json"
            output_root = root / "outputs"
            isaac = root / "isaac"

            with patch.object(batch_pipeline.subprocess, "run", side_effect=[_completed(1), _completed(2), _completed(3)]) as run:
                with patch.dict(os.environ, {"CONDA_PREFIX": "should-not-leak", "PYTHONPATH": "should-not-leak"}, clear=False):
                    code = batch_pipeline.main([
                        "--manifest", str(manifest), "--output-root", str(output_root),
                        "--isaac-sim-path", str(isaac), "--summary", str(summary_path),
                    ])

            self.assertEqual(code, 0)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["processed"], 3)
            self.assertEqual(summary["complete"], 3)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["results"][0]["asset_id"], "asset-1")
            self.assertEqual(summary["results"][2]["final_usd"], "/outputs/asset-3/final/asset.usd")
            self.assertEqual(run.call_count, 3)
            command = run.call_args_list[0].args[0]
            self.assertIn("--rewrite-prompt", run.call_args_list[0].args[0])
            self.assertIn("--isaac-sim-path", command)
            self.assertIn(str(isaac), command)
            env = run.call_args_list[0].kwargs["env"]
            self.assertNotIn("CONDA_PREFIX", env)
            self.assertNotIn("PYTHONPATH", env)
            self.assertEqual(env["ISAAC_SIM_PATH"], str(isaac))

    def test_continue_on_error_processes_all_but_default_stops_at_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self._write_manifest(root, _items(5))

            continue_summary = root / "continue.json"
            responses = [_completed(1), _completed(2), _completed(3, 1, "sam3 failed"), _completed(4), _completed(5, 1, "sam3 failed")]
            with patch.object(batch_pipeline.subprocess, "run", side_effect=responses) as run:
                code = batch_pipeline.main([
                    "--manifest", str(manifest), "--output-root", str(root / "outputs"),
                    "--summary", str(continue_summary), "--continue-on-error",
                ])
            continued = json.loads(continue_summary.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(run.call_count, 5)
            self.assertEqual(continued["processed"], 5)
            self.assertEqual(continued["complete"], 3)
            self.assertEqual(continued["failed"], 2)

            stop_summary = root / "stop.json"
            with patch.object(batch_pipeline.subprocess, "run", side_effect=[_completed(1), _completed(2), _completed(3, 1, "sam3 failed")]) as run:
                code = batch_pipeline.main([
                    "--manifest", str(manifest), "--output-root", str(root / "outputs"), "--summary", str(stop_summary),
                ])
            stopped = json.loads(stop_summary.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(stopped["total"], 5)
            self.assertEqual(stopped["processed"], 3)
            self.assertEqual(stopped["complete"], 2)
            self.assertEqual(stopped["failed"], 1)

    def test_invalid_manifest_returns_exit_code_two_without_running_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "invalid.json"
            manifest.write_text("not json", encoding="utf-8")
            stderr = io.StringIO()
            with patch.object(batch_pipeline.subprocess, "run") as run:
                with contextlib.redirect_stderr(stderr):
                    code = batch_pipeline.main(["--manifest", str(manifest), "--output-root", str(root / "outputs")])
            self.assertEqual(code, 2)
            self.assertIn("Invalid batch manifest", stderr.getvalue())
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
