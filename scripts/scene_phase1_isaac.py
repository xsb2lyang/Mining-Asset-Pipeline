#!/usr/bin/env python3
"""Run the Isaac Sim half of WorldComposer Real2Sim Phase 1.

This helper must be launched with Isaac Sim's ``python.sh``.  Gaussian PLY
conversion is intentionally handled in a separate environment so 3dgrut does
not have to be installed into Isaac Sim's Python runtime.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORLD_COMPOSER_SOURCE = REPO_ROOT / "third_party" / "WorldComposer" / "source" / "WorldComposer"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a scene GLB to USD and assemble it with a Gaussian USDZ."
    )
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--gaussian-usdz", type=Path, required=True)
    parser.add_argument("--mesh-usd", type=Path, required=True)
    parser.add_argument("--out-usd", type=Path, required=True)
    parser.add_argument(
        "--validation-report",
        type=Path,
        help="Static validation JSON (default: next to --out-usd)",
    )
    parser.add_argument("--scene-scale", type=float, default=1.0)
    parser.add_argument("--converter-timeout", type=float, default=300.0)
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def main() -> int:
    args = parse_args()
    glb = require_file(args.glb, "GLB")
    gaussian_usdz = require_file(args.gaussian_usdz, "Gaussian USDZ")
    mesh_usd = args.mesh_usd.expanduser().resolve()
    out_usd = args.out_usd.expanduser().resolve()
    validation_report = (
        args.validation_report.expanduser().resolve()
        if args.validation_report
        else out_usd.with_name("static_validation.json")
    )
    mesh_usd.parent.mkdir(parents=True, exist_ok=True)
    out_usd.parent.mkdir(parents=True, exist_ok=True)
    validation_report.parent.mkdir(parents=True, exist_ok=True)

    if not WORLD_COMPOSER_SOURCE.is_dir():
        raise FileNotFoundError(
            "WorldComposer submodule is unavailable; run "
            "`git submodule update --init --recursive`."
        )
    assembler_path = (
        WORLD_COMPOSER_SOURCE
        / "WorldComposer"
        / "real2sim"
        / "scene_assembler.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_worldcomposer_scene_assembler", assembler_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load WorldComposer assembler: {assembler_path}")
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)

    # SimulationApp must start before pxr/Omniverse modules are imported.
    from isaacsim import SimulationApp

    simulation_app = SimulationApp({"headless": True})
    exit_code = 0
    try:
        print(f"[phase1] converting GLB: {glb}", flush=True)
        assembler.convert_glb_to_usd(
            str(glb),
            str(mesh_usd),
            timeout_sec=args.converter_timeout,
            simulation_app=simulation_app,
        )

        # The final USD is a reference stage. Package both referenced files next
        # to it so the complete final/ directory can be moved to another host.
        assets_dir = out_usd.parent / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        packaged_mesh = assets_dir / mesh_usd.name
        packaged_gaussian = assets_dir / gaussian_usdz.name
        shutil.copy2(mesh_usd, packaged_mesh)
        shutil.copy2(gaussian_usdz, packaged_gaussian)

        print(f"[phase1] assembling scene: {out_usd}", flush=True)
        assembler.align_mesh_to_usd(
            str(out_usd),
            str(packaged_gaussian),
            str(packaged_mesh),
            scene_scale=args.scene_scale,
        )
        from pxr import Usd, UsdGeom, UsdPhysics, UsdUtils

        stage = Usd.Stage.Open(str(out_usd))
        if stage is None:
            raise RuntimeError(f"Unable to reopen assembled USD: {out_usd}")
        # Both packaged inputs are authored in meters.  The WorldComposer
        # helper creates a new root stage without linear-unit metadata, which
        # OpenUSD interprets as centimetres (0.01 m/unit).  Author metres on
        # the assembled root to preserve the source scene's physical scale.
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        stage.GetRootLayer().Save()
        root_layer = stage.GetRootLayer()
        replacements = {
            str(packaged_gaussian): packaged_gaussian.relative_to(out_usd.parent).as_posix(),
            str(packaged_mesh): packaged_mesh.relative_to(out_usd.parent).as_posix(),
        }

        def make_relative(asset_path: str) -> str:
            return replacements.get(asset_path, asset_path)

        UsdUtils.ModifyAssetPaths(root_layer, make_relative)
        root_layer.Save()

        stage = Usd.Stage.Open(str(out_usd))
        if stage is None:
            raise RuntimeError(f"Unable to reopen assembled USD: {out_usd}")
        external_paths: list[str] = []
        for prim in stage.Traverse():
            references = prim.GetMetadata("references")
            if references:
                external_paths.extend(
                    item.assetPath for item in references.GetAddedOrExplicitItems()
                )
        absolute_paths = [path for path in external_paths if os.path.isabs(path)]
        gauss_prim = stage.GetPrimAtPath("/World/gauss")
        mesh_prim = stage.GetPrimAtPath("/World/Xform")
        component_units = {
            "gaussian_usdz": UsdGeom.GetStageMetersPerUnit(
                Usd.Stage.Open(str(packaged_gaussian))
            ),
            "mesh_usd": UsdGeom.GetStageMetersPerUnit(
                Usd.Stage.Open(str(packaged_mesh))
            ),
        }
        checks = {
            "meters_per_unit_is_meter": abs(UsdGeom.GetStageMetersPerUnit(stage) - 1.0) < 1e-9,
            "component_units_are_meters": all(
                abs(units - 1.0) < 1e-9 for units in component_units.values()
            ),
            "default_prim_is_world": str(stage.GetDefaultPrim().GetPath()) == "/World",
            "gaussian_prim_exists": gauss_prim.IsValid(),
            "collider_prim_exists": mesh_prim.IsValid(),
            "collider_is_invisible": (
                mesh_prim.IsValid()
                and UsdGeom.Imageable(mesh_prim).ComputeVisibility()
                == UsdGeom.Tokens.invisible
            ),
            "collider_has_rigid_body": (
                mesh_prim.IsValid() and mesh_prim.HasAPI(UsdPhysics.RigidBodyAPI)
            ),
            "collider_has_collision": (
                mesh_prim.IsValid() and mesh_prim.HasAPI(UsdPhysics.CollisionAPI)
            ),
            "references_are_relative": not absolute_paths,
            "packaged_gaussian_exists": packaged_gaussian.is_file(),
            "packaged_mesh_exists": packaged_mesh.is_file(),
        }
        report = {
            "schema_version": 1,
            "passed": all(checks.values()),
            "stage": out_usd.name,
            "default_prim": str(stage.GetDefaultPrim().GetPath()),
            "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
            "component_meters_per_unit": component_units,
            "checks": checks,
            "references": external_paths,
            "absolute_references": absolute_paths,
            "prim_count": sum(1 for _ in stage.Traverse()),
            "limitations": [
                "Static Phase 1 validation only; no dynamic simulation test was run."
            ],
        }
        validation_report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if not report["passed"]:
            raise RuntimeError(f"Static validation failed: {validation_report}")
    except BaseException:  # Isaac shutdown can otherwise hide buffered errors.
        traceback.print_exc()
        exit_code = 1
    finally:
        simulation_app.close()

    if exit_code:
        return exit_code
    if not mesh_usd.is_file() or not out_usd.is_file():
        raise RuntimeError("WorldComposer Phase 1 did not create all expected USD files")

    print(f"mesh_usd={mesh_usd}", flush=True)
    print(f"scene_usd={out_usd}", flush=True)
    print(f"validation_report={validation_report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
