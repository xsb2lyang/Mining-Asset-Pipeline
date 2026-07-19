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
            "docs/scene_pipeline.md",
            "environments/local.env.example",
            "environments/scene_phase1_constraints.txt",
            "assets/samples/README.md",
            "assets/samples/batch_manifest.json",
            "assets/samples/scenes/mine_tunnel_orbit.mp4",
            "scripts/launch_isaac_sim.sh",
            "scripts/setup_scene_phase1_env.sh",
            "scripts/run_scene_phase1.py",
            "scripts/record_scene_preview.py",
            "scripts/generate_marble_world.py",
            "scripts/doctor.py",
            "scripts/asset_tool.py",
            "scripts/run_sam3.py",
            "scripts/run_sam3d.py",
            "src/mining_asset_pipeline/agent/workflow.py",
            ".agents/skills/generate-mining-asset/SKILL.md",
            ".agents/skills/generate-mining-scene/SKILL.md",
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
        scene_video = sample_root / "scenes" / "mine_tunnel_orbit.mp4"
        self.assertGreater(scene_video.stat().st_size, 1_000_000)
        self.assertIn("mine_tunnel_orbit.mp4", readme)
        self.assertIn("Apache License 2.0", readme)

    def test_project_metadata_declares_runtime_and_optional_dependencies(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dependencies = " ".join(metadata["dependencies"])
        self.assertIn("Pillow", dependencies)
        self.assertNotIn("ui", metadata["optional-dependencies"])
        self.assertIn("llm", metadata["optional-dependencies"])
        package_init = ROOT / "src" / "mining_asset_pipeline" / "__init__.py"
        spec = importlib.util.spec_from_file_location("package_version", package_init)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.__version__, metadata["version"])

    def test_removed_web_ui_is_not_part_of_the_public_repository(self) -> None:
        self.assertFalse((ROOT / "scripts" / "launch_asset_agent.py").exists())
        self.assertFalse((ROOT / "src" / "mining_asset_pipeline" / "agent" / "web.py").exists())

    def test_agent_skill_has_one_canonical_body_and_claude_discovery_link(self) -> None:
        canonical = ROOT / ".agents" / "skills" / "generate-mining-asset"
        claude = ROOT / ".claude" / "skills" / "generate-mining-asset"
        self.assertTrue(canonical.is_dir())
        self.assertTrue(claude.is_symlink())
        self.assertEqual(claude.resolve(), canonical.resolve())
        frontmatter = (canonical / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        self.assertIn("name: generate-mining-asset", frontmatter)
        self.assertIn("description:", frontmatter)
        for reference in ("tool-contract.md", "quality-policy.md", "role-prompts.md"):
            self.assertTrue((canonical / "references" / reference).is_file())

    def test_scene_skill_has_one_canonical_body_and_claude_discovery_link(self) -> None:
        canonical = ROOT / ".agents" / "skills" / "generate-mining-scene"
        claude = ROOT / ".claude" / "skills" / "generate-mining-scene"
        self.assertTrue(canonical.is_dir())
        self.assertTrue(claude.is_symlink())
        self.assertEqual(claude.resolve(), canonical.resolve())
        skill = (canonical / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1]
        self.assertIn("name: generate-mining-scene", frontmatter)
        self.assertIn("description:", frontmatter)
        for reference in ("workflow-contract.md", "quality-policy.md"):
            self.assertTrue((canonical / "references" / reference).is_file())
        for script in (
            "scripts/generate_marble_world.py",
            "scripts/run_scene_phase1.py",
            "scripts/record_scene_preview.py",
        ):
            self.assertIn(script, skill)
        self.assertIn("--visual-mode full", skill)
        self.assertIn("WORLDLABS_API_KEY", skill)
        self.assertNotIn("scripts/run_pipeline.py", skill)
        contract = (canonical / "references" / "workflow-contract.md").read_text(encoding="utf-8")
        policy = (canonical / "references" / "quality-policy.md").read_text(encoding="utf-8")
        for required_text in (
            ".mp4",
            ".mov",
            ".mkv",
            "--export-hq-mesh",
            "scene.ply",
            "pano.png",
            "static_validation.json",
            "--visual-mode full",
            "WORLDLABS_API_KEY",
        ):
            self.assertIn(required_text, contract)
        for required_text in ("phase1_verified", "degraded", "black", "blocked"):
            self.assertIn(required_text, policy)

    def test_public_docs_do_not_contain_maintainer_absolute_path(self) -> None:
        public_files = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
        for path in public_files:
            self.assertNotIn("/home/user/Xsb_WS", path.read_text(encoding="utf-8"), str(path))

    def test_relative_markdown_links_resolve(self) -> None:
        markdown_files = [
            ROOT / "README.md",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            ROOT / "SUPPORT.md",
            ROOT / "THIRD_PARTY_NOTICES.md",
            *(ROOT / "docs").rglob("*.md"),
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
