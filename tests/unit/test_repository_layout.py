"""Fast, dependency-free checks for the public repository contract."""

from __future__ import annotations

import py_compile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RepositoryLayoutTests(unittest.TestCase):
    def test_required_repository_files_exist(self) -> None:
        for relative_path in (
            ".gitignore",
            ".gitmodules",
            "README.md",
            "pyproject.toml",
            "docs/architecture.md",
            "docs/setup.md",
            "environments/local.env.example",
            "scripts/launch_isaac_sim.sh",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_usd_tools_are_syntax_valid(self) -> None:
        for source in sorted((ROOT / "src/mining_asset_pipeline/usd").glob("*.py")):
            py_compile.compile(str(source), doraise=True)

    def test_no_runtime_or_weights_are_tracked(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("/external/", "/checkpoints/", "/outputs/", "/Benchmark/simulator/"):
            self.assertIn(pattern, ignored)


if __name__ == "__main__":
    unittest.main()
