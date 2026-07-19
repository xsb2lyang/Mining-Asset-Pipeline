#!/usr/bin/env python3
"""Build a portable, renderable Marble Phase 1 scene package for Isaac Sim.

The visual mesh and the physics collider are authored as distinct USD layers:
the textured mesh is visible, while the collider is invisible and kinematic.
This deliberately avoids legacy NuRec payloads, which do not render reliably
in the repository's Isaac Sim 5.1 target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
CLEAR_FOR_ISAAC = (
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_SHLVL",
    "CONDA_PROMPT_MODIFIER",
    "PYTHONPATH",
    "PYTHONHOME",
    "LD_LIBRARY_PATH",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:64] or "scene"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _git_revision(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _run(command: Sequence[str], *, env: dict[str, str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}; see {log_path}"
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Marble textured mesh + collider GLB into a renderable Phase 1 USD scene."
    )
    parser.add_argument(
        "--visual-glb",
        type=Path,
        required=True,
        help="Marble high-quality textured mesh GLB (visible scene layer)",
    )
    parser.add_argument(
        "--collider-glb",
        type=Path,
        required=True,
        help="Marble collider mesh GLB (hidden kinematic collision layer)",
    )
    parser.add_argument(
        "--ply",
        type=Path,
        help="Optional Marble Gaussian-splat PLY retained as provenance only",
    )
    parser.add_argument("--scene-name", required=True, help="Semantic output name")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("SCENE_OUTPUT_DIR", ROOT / "scene_outputs")),
    )
    parser.add_argument(
        "--isaac-sim-path",
        type=Path,
        default=Path(os.environ["ISAAC_SIM_PATH"]) if os.environ.get("ISAAC_SIM_PATH") else None,
    )
    parser.add_argument("--scene-scale", type=float, default=1.0)
    parser.add_argument("--converter-timeout", type=float, default=300.0)
    parser.add_argument("--force", action="store_true", help="Replace an existing scene bundle")
    return parser.parse_args(argv)


def _require_input(path: Path, suffix: str, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} not found: {resolved}")
    if resolved.suffix.lower() != suffix:
        raise ValueError(f"{label} must be a {suffix} file: {resolved}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        visual_glb = _require_input(args.visual_glb, ".glb", "Visual GLB")
        collider_glb = _require_input(args.collider_glb, ".glb", "Collider GLB")
        ply = _require_input(args.ply, ".ply", "PLY") if args.ply else None
        if args.scene_scale <= 0:
            raise ValueError("--scene-scale must be greater than zero")
        if not args.isaac_sim_path:
            raise ValueError("Set ISAAC_SIM_PATH or pass --isaac-sim-path")
        isaac_python = args.isaac_sim_path.expanduser().resolve() / "python.sh"
        if not isaac_python.is_file():
            raise ValueError(f"Isaac Sim python.sh not found: {isaac_python}")
    except ValueError as exc:
        print(f"Invalid Phase 1 request: {exc}", file=sys.stderr)
        return 2

    scene_slug = _slug(args.scene_name)
    bundle = args.output_root.expanduser().resolve() / scene_slug
    if bundle.exists():
        if not args.force:
            print(f"Output already exists (use --force): {bundle}", file=sys.stderr)
            return 2
        shutil.rmtree(bundle)
    staged_input = bundle / "input"
    intermediate = bundle / "intermediate"
    final = bundle / "final"
    logs = bundle / "logs"
    for directory in (staged_input, intermediate, final, logs):
        directory.mkdir(parents=True, exist_ok=True)

    staged_visual_glb = staged_input / f"{scene_slug}_visual.glb"
    staged_collider_glb = staged_input / f"{scene_slug}_collider.glb"
    shutil.copy2(visual_glb, staged_visual_glb)
    shutil.copy2(collider_glb, staged_collider_glb)
    visual_usd = intermediate / "visual" / f"{scene_slug}_visual.usd"
    collider_usd = intermediate / "collider" / f"{scene_slug}_collider.usd"
    scene_usd = final / f"{scene_slug}.usd"
    validation_report = final / "static_validation.json"
    manifest_path = bundle / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pipeline": "worldcomposer_real2sim_phase1",
        "status": "running",
        "started_at": _utc_now(),
        "scene_name": args.scene_name,
        "scene_slug": scene_slug,
        "inputs": {
            "visual_glb": {
                "path": str(visual_glb), "sha256": _sha256(visual_glb), "bytes": visual_glb.stat().st_size
            },
            "collider_glb": {
                "path": str(collider_glb), "sha256": _sha256(collider_glb), "bytes": collider_glb.stat().st_size
            },
        },
        "parameters": {"scene_scale": args.scene_scale, "visual_format": "textured_mesh_glb"},
        "tools": {
            "isaac_sim_path": str(args.isaac_sim_path.expanduser().resolve()),
        },
        "artifacts": {},
        "limitations": ["Phase 1 static assembly only; no dynamic simulation test was run."],
    }
    if ply:
        manifest["inputs"]["ply"] = {
            "path": str(ply), "sha256": _sha256(ply), "bytes": ply.stat().st_size
        }
    _write_json(manifest_path, manifest)

    try:
        isaac_env = os.environ.copy()
        for name in CLEAR_FOR_ISAAC:
            isaac_env.pop(name, None)
        _run(
            [
                str(isaac_python),
                str(ROOT / "scripts" / "scene_phase1_isaac.py"),
                "--visual-glb",
                str(staged_visual_glb),
                "--collider-glb",
                str(staged_collider_glb),
                "--visual-usd",
                str(visual_usd),
                "--collider-usd",
                str(collider_usd),
                "--out-usd",
                str(scene_usd),
                "--validation-report",
                str(validation_report),
                "--scene-scale",
                str(args.scene_scale),
                "--converter-timeout",
                str(args.converter_timeout),
            ],
            env=isaac_env,
            log_path=logs / "isaac_assembly.log",
        )
        validation = json.loads(validation_report.read_text(encoding="utf-8"))
        if not validation.get("passed"):
            raise RuntimeError(f"Static validation did not pass: {validation_report}")
        manifest["status"] = "complete"
        manifest["finished_at"] = _utc_now()
        manifest["artifacts"] = {
            "staged_visual_glb": str(staged_visual_glb.relative_to(bundle)),
            "staged_collider_glb": str(staged_collider_glb.relative_to(bundle)),
            "visual_usd": str(visual_usd.relative_to(bundle)),
            "collider_usd": str(collider_usd.relative_to(bundle)),
            "scene_usd": str(scene_usd.relative_to(bundle)),
            "validation_report": str(validation_report.relative_to(bundle)),
        }
        _write_json(manifest_path, manifest)
    except Exception as exc:  # noqa: BLE001 - persist all external-tool failures.
        manifest["status"] = "failed"
        manifest["finished_at"] = _utc_now()
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        _write_json(manifest_path, manifest)
        print(str(exc), file=sys.stderr)
        return 1

    print(f"scene_id={scene_slug}")
    print(f"scene_usd={scene_usd}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
