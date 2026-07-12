"""Tests for the standalone helpers extracted from web.py.

These avoid importing gradio by exercising pure functions that the Gradio UI
itself delegates to: the SVG progress renderer, the log tail reader, and the
asset bundle scanner.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.models import AssetRequest  # noqa: E402
from mining_asset_pipeline.agent.storage import AssetStore  # noqa: E402
from mining_asset_pipeline.agent.web import _render_progress_svg, _scan_assets, _tail_log  # noqa: E402
from mining_asset_pipeline.agent.workflow import AssetWorkflow  # noqa: E402


def _stub_workflow(output_root: Path) -> AssetWorkflow:
    return AssetWorkflow(repo_root=output_root, output_root=output_root / "outputs")


class ProgressSvgTests(unittest.TestCase):
    def _manifest(self, status: str, events: list[dict] | None = None) -> dict:
        return {"status": status, "events": events or [{"status": status, "message": ""}]}

    def test_in_progress_uses_green_for_active_step(self) -> None:
        svg = _render_progress_svg(self._manifest("visual_running"))
        self.assertIn("#16a34a", svg)
        # step 2 (visual_running) should be highlighted; step 3 onwards still grey
        self.assertIn("#e5e7eb", svg)
        self.assertNotIn("#dc2626", svg)

    def test_failed_step_uses_red(self) -> None:
        events = [
            {"status": "created", "message": ""},
            {"status": "visual_running", "message": ""},
            {"status": "failed", "message": "sam3 crashed"},
        ]
        svg = _render_progress_svg(self._manifest("failed", events))
        self.assertIn("#dc2626", svg)

    def test_complete_uses_only_green(self) -> None:
        svg = _render_progress_svg(self._manifest("complete"))
        self.assertIn("#16a34a", svg)
        self.assertNotIn("#dc2626", svg)
        self.assertNotIn("#e5e7eb", svg)

    def test_unknown_status_falls_back_to_first_step(self) -> None:
        svg = _render_progress_svg(self._manifest("totally_unknown"))
        self.assertIn("<svg", svg)
        self.assertIn("#16a34a", svg)


class ScanAssetsTests(unittest.TestCase):
    def test_skips_directories_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            outputs = temp_root / "outputs"
            outputs.mkdir()
            (outputs / "real_asset").mkdir()
            (outputs / "real_asset" / "manifest.json").write_text(
                json.dumps({"status": "complete", "created_at": "2026-07-12T00:00:00Z"}),
                encoding="utf-8",
            )
            (outputs / "real_asset" / "request.json").write_text(
                json.dumps({"prompt": "mug"}),
                encoding="utf-8",
            )
            (outputs / "e2e_red_mug").mkdir()  # no manifest.json — legacy scratch
            (outputs / "20260712-140612-cup-719647").mkdir()
            (outputs / "20260712-140612-cup-719647" / "manifest.json").write_text(
                json.dumps({"status": "review_required", "created_at": "2026-07-12T06:06:12Z"}),
                encoding="utf-8",
            )
            (outputs / "20260712-140612-cup-719647" / "request.json").write_text(
                json.dumps({"prompt": "cup"}),
                encoding="utf-8",
            )

            wf = _stub_workflow(temp_root)
            rows = _scan_assets(wf)

            asset_ids = [row[0] for row in rows]
            self.assertNotIn("e2e_red_mug", asset_ids)
            self.assertIn("real_asset", asset_ids)
            self.assertIn("20260712-140612-cup-719647", asset_ids)
            # prompt column is populated from request.json
            real_row = next(row for row in rows if row[0] == "real_asset")
            self.assertEqual(real_row[1], "complete")
            self.assertEqual(real_row[3], "mug")


class TailLogTests(unittest.TestCase):
    def test_returns_last_lines_of_most_recent_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            outputs = temp_root / "outputs"
            outputs.mkdir()
            image = temp_root / "input.png"
            from PIL import Image
            Image.new("RGB", (4, 4), "red").save(image)

            store = AssetStore(outputs)
            asset_id = store.create(image, AssetRequest(prompt="mug"))
            sam3_log = store.root(asset_id) / "visual" / "logs" / "sam3.log"
            sam3_log.parent.mkdir(parents=True, exist_ok=True)
            sam3_log.write_text("\n".join(f"line-{i}" for i in range(50)), encoding="utf-8")
            store.set_artifact(asset_id, "sam3_log", sam3_log)

            wf = _stub_workflow(temp_root)
            tail = _tail_log(wf, asset_id, n=10)
            self.assertEqual(len(tail.splitlines()), 10)
            self.assertEqual(tail.splitlines()[0], "line-40")
            self.assertEqual(tail.splitlines()[-1], "line-49")

    def test_returns_empty_when_no_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            outputs = temp_root / "outputs"
            outputs.mkdir()
            image = temp_root / "input.png"
            from PIL import Image
            Image.new("RGB", (4, 4), "red").save(image)

            store = AssetStore(outputs)
            asset_id = store.create(image, AssetRequest(prompt="mug"))

            wf = _stub_workflow(temp_root)
            self.assertEqual(_tail_log(wf, asset_id), "")


if __name__ == "__main__":
    unittest.main()