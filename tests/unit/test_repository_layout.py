"""Fast, dependency-free checks for the public repository contract."""

from __future__ import annotations

import importlib.util
import json
import py_compile
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RepositoryLayoutTests(unittest.TestCase):
    def test_required_repository_files_exist(self) -> None:
        for relative_path in (
            ".gitignore",
            ".gitmodules",
            "README.md",
            "CHANGELOG.md",
            "CODE_OF_CONDUCT.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "THIRD_PARTY_NOTICES.md",
            "pyproject.toml",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/dependabot.yml",
            "docs/architecture.md",
            "docs/setup.md",
            "docs/release_checklist.md",
            "environments/local.env.example",
            "assets/samples/README.md",
            "assets/samples/batch_manifest.json",
            "scripts/launch_isaac_sim.sh",
            "scripts/doctor.py",
            "scripts/run_sam3.py",
            "scripts/run_sam3d.py",
            "scripts/launch_asset_agent.py",
            "src/mining_asset_pipeline/agent/workflow.py",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_usd_tools_are_syntax_valid(self) -> None:
        sources = list((ROOT / "src/mining_asset_pipeline/usd").glob("*.py"))
        sources.extend((ROOT / "src/mining_asset_pipeline/agent").glob("*.py"))
        sources.extend((ROOT / "scripts").glob("*.py"))
        for source in sorted(sources):
            py_compile.compile(str(source), doraise=True)

    def test_no_runtime_or_weights_are_tracked(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("/external/", "/checkpoints/", "/outputs/", "/Benchmark/simulator/"):
            self.assertIn(pattern, ignored)

    def test_public_samples_are_licensed_and_batch_manifest_is_valid(self) -> None:
        sample_root = ROOT / "assets" / "samples"
        readme = (sample_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("Apache License 2.0", readme)
        manifest = json.loads((sample_root / "batch_manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest), 2)
        for item in manifest:
            self.assertTrue((ROOT / item["image"]).is_file(), item["image"])
            self.assertTrue(item["prompt"].strip())

    def test_project_metadata_declares_runtime_and_optional_dependencies(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dependencies = " ".join(metadata["dependencies"])
        self.assertIn("Pillow", dependencies)
        self.assertIn("ui", metadata["optional-dependencies"])
        self.assertIn("llm", metadata["optional-dependencies"])
        package_init = ROOT / "src" / "mining_asset_pipeline" / "__init__.py"
        spec = importlib.util.spec_from_file_location("package_version", package_init)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.__version__, metadata["version"])

    def test_public_docs_do_not_contain_maintainer_absolute_path(self) -> None:
        public_files = [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]
        for path in public_files:
            self.assertNotIn("/home/user/Xsb_WS", path.read_text(encoding="utf-8"), str(path))

    def test_relative_markdown_links_resolve(self) -> None:
        markdown_files = [
            ROOT / "README.md",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            ROOT / "SUPPORT.md",
            ROOT / "THIRD_PARTY_NOTICES.md",
            *(ROOT / "docs").glob("*.md"),
            *(ROOT / "assets" / "samples").glob("*.md"),
        ]
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for source in markdown_files:
            for raw_target in link_pattern.findall(source.read_text(encoding="utf-8")):
                target = raw_target.strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith(("mailto:", "#")):
                    continue
                resolved = (source.parent / target).resolve()
                self.assertTrue(resolved.exists(), f"{source.relative_to(ROOT)} -> {raw_target}")


if __name__ == "__main__":
    unittest.main()
