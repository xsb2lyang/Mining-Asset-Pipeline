#!/usr/bin/env python3
"""Build a portable, renderable Marble Phase 1 scene package for Isaac Sim.

The visual scene and its kinematic physics collider are authored as distinct
USD layers.  Marble PLY files are converted through a fixed-SH NuRec
compatibility adapter so the Isaac Sim 5.1 renderer does not receive the empty
higher-order SH tensor emitted by the generic current 3dgrut transcoder.
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
        help="Marble high-quality textured mesh GLB (preferred visible scene layer)",
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
        help=(
            "Marble Gaussian-splat PLY. When --visual-glb is unavailable, this is converted to a "
            "fixed-SH NuRec compatibility visual; otherwise retained as provenance."
        ),
    )
    parser.add_argument(
        "--pano",
        type=Path,
        help="Optional Marble panorama PNG for the textured-collider visual fallback",
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
    parser.add_argument(
        "--threedgrut-env",
        default=os.environ.get("THREEDGRUT_ENV", "worldcomposer-r2s"),
        help="Conda environment for the isolated Marble PLY -> NuRec compatibility transcoder",
    )
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
        visual_glb = _require_input(args.visual_glb, ".glb", "Visual GLB") if args.visual_glb else None
        collider_glb = _require_input(args.collider_glb, ".glb", "Collider GLB")
        ply = _require_input(args.ply, ".ply", "PLY") if args.ply else None
        pano = _require_input(args.pano, ".png", "Panorama") if args.pano else None
        if visual_glb is None and ply is None and pano is None:
            raise ValueError("Provide --visual-glb, --pano, or --ply for the visible scene layer")
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

    staged_visual_glb = staged_input / f"{scene_slug}_visual.glb" if visual_glb else None
    staged_ply = staged_input / f"{scene_slug}.ply" if ply else None
    staged_collider_glb = staged_input / f"{scene_slug}_collider.glb"
    if visual_glb and staged_visual_glb:
        shutil.copy2(visual_glb, staged_visual_glb)
    if ply and staged_ply:
        shutil.copy2(ply, staged_ply)
    shutil.copy2(collider_glb, staged_collider_glb)
    visual_usd = intermediate / "visual" / f"{scene_slug}_visual.usd"
    collider_usd = intermediate / "collider" / f"{scene_slug}_collider.usd"
    scene_usd = final / f"{scene_slug}.usd"
    validation_report = final / "static_validation.json"
    nurec_usdz = intermediate / "visual" / f"{scene_slug}.usdz"
    manifest_path = bundle / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pipeline": "worldcomposer_real2sim_phase1",
        "status": "running",
        "started_at": _utc_now(),
        "scene_name": args.scene_name,
        "scene_slug": scene_slug,
        "inputs": {
            "collider_glb": {
                "path": str(collider_glb), "sha256": _sha256(collider_glb), "bytes": collider_glb.stat().st_size
            },
        },
        "parameters": {
            "scene_scale": args.scene_scale,
            "visual_format": (
                "textured_mesh_glb"
                if visual_glb
                else "nurec_fixed_sh_compatibility"
                if ply
                else "pano_textured_collider_fallback"
                if pano
                else "colored_point_cloud_fallback"
            ),
        },
        "tools": {
            "isaac_sim_path": str(args.isaac_sim_path.expanduser().resolve()),
        },
        "artifacts": {},
        "limitations": ["Phase 1 static assembly only; no dynamic simulation test was run."],
    }
    if visual_glb:
        manifest["inputs"]["visual_glb"] = {
            "path": str(visual_glb), "sha256": _sha256(visual_glb), "bytes": visual_glb.stat().st_size
        }
    if ply:
        manifest["inputs"]["ply"] = {
            "path": str(ply), "sha256": _sha256(ply), "bytes": ply.stat().st_size
        }
    if pano:
        manifest["inputs"]["pano"] = {
            "path": str(pano), "sha256": _sha256(pano), "bytes": pano.stat().st_size
        }
    _write_json(manifest_path, manifest)

    try:
        isaac_env = os.environ.copy()
        for name in CLEAR_FOR_ISAAC:
            isaac_env.pop(name, None)
        if ply and not visual_glb:
            if not shutil.which("conda"):
                raise RuntimeError("conda is required for PLY -> NuRec conversion; run scripts/setup_scene_phase1_env.sh")
            nurec_command = [
                "conda", "run", "-n", args.threedgrut_env,
                "python", str(ROOT / "scripts" / "transcode_marble_ply_to_nurec.py"),
                "--ply", str(staged_ply), "--output", str(nurec_usdz),
            ]
            nurec_env = os.environ.copy()
            nurec_env["PYTHONPATH"] = str(ROOT / "third_party" / "3dgrut")
            _run(nurec_command, env=nurec_env, log_path=logs / "nurec_transcode.log")
            if not nurec_usdz.is_file():
                raise RuntimeError(f"NuRec compatibility transcoder did not create: {nurec_usdz}")

        command = [
            str(isaac_python),
            str(ROOT / "scripts" / "scene_phase1_isaac.py"),
            "--collider-glb", str(staged_collider_glb),
            "--visual-usd", str(visual_usd),
            "--collider-usd", str(collider_usd),
            "--out-usd", str(scene_usd),
            "--validation-report", str(validation_report),
            "--scene-scale", str(args.scene_scale),
            "--converter-timeout", str(args.converter_timeout),
        ]
        if staged_visual_glb:
            command.extend(["--visual-glb", str(staged_visual_glb)])
        elif ply:
            command.extend(["--nurec-usdz", str(nurec_usdz)])
        elif pano:
            command.extend(["--pano", str(pano)])
        else:
            assert ply is not None
            command.extend(["--ply", str(ply)])
        _run(command, env=isaac_env, log_path=logs / "isaac_assembly.log")
        validation = json.loads(validation_report.read_text(encoding="utf-8"))
        if not validation.get("passed"):
            raise RuntimeError(f"Static validation did not pass: {validation_report}")
        manifest["status"] = "complete"
        manifest["finished_at"] = _utc_now()
        manifest["artifacts"] = {
            "staged_collider_glb": str(staged_collider_glb.relative_to(bundle)),
            "visual_usd": str(visual_usd.relative_to(bundle)),
            "collider_usd": str(collider_usd.relative_to(bundle)),
            "scene_usd": str(scene_usd.relative_to(bundle)),
            "validation_report": str(validation_report.relative_to(bundle)),
        }
        if staged_visual_glb:
            manifest["artifacts"]["staged_visual_glb"] = str(staged_visual_glb.relative_to(bundle))
        elif ply:
            manifest["artifacts"]["staged_ply"] = str(staged_ply.relative_to(bundle))
            manifest["artifacts"]["nurec_usdz"] = str(nurec_usdz.relative_to(bundle))
        else:
            manifest["quality"] = "degraded"
            manifest["limitations"].append(
                "Visual layer is a fallback, not Marble's high-quality textured mesh export."
            )
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
