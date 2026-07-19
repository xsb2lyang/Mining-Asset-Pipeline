#!/usr/bin/env python3
"""Author the Isaac Sim half of a renderable Marble Phase 1 scene.

Run with Isaac Sim's ``python.sh``.  The script deliberately creates separate
visual and collision prims: a material-preserving textured GLB for rendering,
and a geometry-only GLB for kinematic physics.  This is portable across Isaac
Sim 5.1 installations and avoids the legacy NuRec visual dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import traceback
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Marble visual/collider GLBs and assemble a renderable USD scene."
    )
    parser.add_argument("--visual-glb", type=Path, required=True)
    parser.add_argument("--collider-glb", type=Path, required=True)
    parser.add_argument("--visual-usd", type=Path, required=True)
    parser.add_argument("--collider-usd", type=Path, required=True)
    parser.add_argument("--out-usd", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument("--scene-scale", type=float, default=1.0)
    parser.add_argument("--converter-timeout", type=float, default=300.0)
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


async def _convert_glb_to_usd(
    glb: Path,
    output: Path,
    *,
    preserve_materials: bool,
    timeout: float,
) -> None:
    import omni.kit.asset_converter  # type: ignore

    def progress_callback(progress: int, total_steps: int) -> int:
        print(f"[AssetConverter] {glb.name}: {progress}/{total_steps}", flush=True)
        return progress

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    context = omni.kit.asset_converter.AssetConverterContext()
    context.ignore_materials = not preserve_materials
    context.ignore_animations = True
    context.ignore_cameras = True
    context.ignore_lights = True
    context.merge_all_meshes = not preserve_materials
    context.use_meter_as_world_unit = True
    # Marble GLBs contain texture images.  Embedding makes the visual USD
    # self-contained instead of relying on transient export directories.
    context.embed_textures = preserve_materials
    manager = omni.kit.asset_converter.get_instance()
    task = manager.create_converter_task(
        glb.resolve().as_uri(), output.resolve().as_uri(), progress_callback, context
    )
    try:
        success = await asyncio.wait_for(task.wait_until_finished(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"GLB -> USD conversion timed out after {timeout:.0f}s: {glb}") from exc
    if not success or not output.is_file():
        raise RuntimeError(f"GLB -> USD conversion failed: {glb} -> {output}")


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy a USD component plus any texture sidecars produced by the converter."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _has_renderable_mesh(prim) -> bool:
    from pxr import UsdGeom

    return any(child.IsA(UsdGeom.Mesh) for child in UsdGeom.Imageable(prim).GetPrim().GetStage().Traverse() if child.GetPath().HasPrefix(prim.GetPath()))


def _write_scene(
    *,
    out_usd: Path,
    packaged_visual_usd: Path,
    packaged_collider_usd: Path,
    scene_scale: float,
) -> None:
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    if out_usd.exists():
        out_usd.unlink()
    stage = Usd.Stage.CreateNew(str(out_usd))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    scale = Gf.Vec3d(float(scene_scale), float(scene_scale), float(scene_scale))

    visual = stage.DefinePrim("/World/Visual", "Xform")
    visual.GetReferences().AddReference(str(packaged_visual_usd))
    visual_xform = UsdGeom.Xformable(visual)
    visual_xform.ClearXformOpOrder()
    visual_xform.AddRotateXYZOp().Set(Gf.Vec3d(-90.0, 0.0, 0.0))
    visual_xform.AddScaleOp().Set(scale)
    UsdGeom.Imageable(visual).MakeVisible()

    collider = stage.DefinePrim("/World/Collider", "Xform")
    collider.GetReferences().AddReference(str(packaged_collider_usd))
    collider_xform = UsdGeom.Xformable(collider)
    collider_xform.ClearXformOpOrder()
    collider_xform.AddRotateXYZOp().Set(Gf.Vec3d(-90.0, 0.0, 0.0))
    collider_xform.AddScaleOp().Set(scale)
    UsdGeom.Imageable(collider).MakeInvisible()
    rigid = UsdPhysics.RigidBodyAPI.Apply(collider)
    rigid.CreateKinematicEnabledAttr().Set(True)
    UsdPhysics.CollisionAPI.Apply(collider)
    collision = UsdPhysics.MeshCollisionAPI.Apply(collider)
    collision.CreateApproximationAttr().Set("meshSimplification")
    stage.Save()


def main() -> int:
    args = parse_args()
    visual_glb = require_file(args.visual_glb, "Visual GLB")
    collider_glb = require_file(args.collider_glb, "Collider GLB")
    visual_usd = args.visual_usd.expanduser().resolve()
    collider_usd = args.collider_usd.expanduser().resolve()
    out_usd = args.out_usd.expanduser().resolve()
    validation_report = (
        args.validation_report.expanduser().resolve()
        if args.validation_report
        else out_usd.with_name("static_validation.json")
    )
    for path in (visual_usd.parent, collider_usd.parent, out_usd.parent, validation_report.parent):
        path.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    simulation_app = SimulationApp({"headless": True})
    exit_code = 0
    try:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            print(f"[phase1] converting visible textured mesh: {visual_glb}", flush=True)
            loop.run_until_complete(
                _convert_glb_to_usd(
                    visual_glb,
                    visual_usd,
                    preserve_materials=True,
                    timeout=args.converter_timeout,
                )
            )
            print(f"[phase1] converting physics collider: {collider_glb}", flush=True)
            loop.run_until_complete(
                _convert_glb_to_usd(
                    collider_glb,
                    collider_usd,
                    preserve_materials=False,
                    timeout=args.converter_timeout,
                )
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        # Package the complete visual component directory: Asset Converter may
        # emit texture sidecars even when texture embedding is requested.
        assets_dir = out_usd.parent / "assets"
        packaged_visual_dir = assets_dir / visual_usd.parent.name
        packaged_collider_dir = assets_dir / collider_usd.parent.name
        _copy_tree(visual_usd.parent, packaged_visual_dir)
        _copy_tree(collider_usd.parent, packaged_collider_dir)
        packaged_visual_usd = packaged_visual_dir / visual_usd.name
        packaged_collider_usd = packaged_collider_dir / collider_usd.name
        _write_scene(
            out_usd=out_usd,
            packaged_visual_usd=packaged_visual_usd,
            packaged_collider_usd=packaged_collider_usd,
            scene_scale=args.scene_scale,
        )

        from pxr import Usd, UsdGeom, UsdPhysics, UsdUtils

        stage = Usd.Stage.Open(str(out_usd))
        if stage is None:
            raise RuntimeError(f"Unable to reopen assembled USD: {out_usd}")
        root_layer = stage.GetRootLayer()
        replacements = {
            str(packaged_visual_usd): packaged_visual_usd.relative_to(out_usd.parent).as_posix(),
            str(packaged_collider_usd): packaged_collider_usd.relative_to(out_usd.parent).as_posix(),
        }
        UsdUtils.ModifyAssetPaths(root_layer, lambda path: replacements.get(path, path))
        root_layer.Save()
        stage = Usd.Stage.Open(str(out_usd))
        visual = stage.GetPrimAtPath("/World/Visual")
        collider = stage.GetPrimAtPath("/World/Collider")
        references: list[str] = []
        for prim in stage.Traverse():
            metadata = prim.GetMetadata("references")
            if metadata:
                references.extend(item.assetPath for item in metadata.GetAddedOrExplicitItems())
        absolute_paths = [path for path in references if os.path.isabs(path)]
        component_units = {
            "visual_usd": UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(str(packaged_visual_usd))),
            "collider_usd": UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(str(packaged_collider_usd))),
        }
        checks = {
            "meters_per_unit_is_meter": abs(UsdGeom.GetStageMetersPerUnit(stage) - 1.0) < 1e-9,
            "component_units_are_meters": all(abs(unit - 1.0) < 1e-9 for unit in component_units.values()),
            "default_prim_is_world": str(stage.GetDefaultPrim().GetPath()) == "/World",
            "visual_prim_exists": visual.IsValid(),
            "visual_is_visible": visual.IsValid() and UsdGeom.Imageable(visual).ComputeVisibility() == UsdGeom.Tokens.inherited,
            "visual_has_renderable_mesh": visual.IsValid() and _has_renderable_mesh(visual),
            "collider_prim_exists": collider.IsValid(),
            "collider_is_invisible": collider.IsValid() and UsdGeom.Imageable(collider).ComputeVisibility() == UsdGeom.Tokens.invisible,
            "collider_has_rigid_body": collider.IsValid() and collider.HasAPI(UsdPhysics.RigidBodyAPI),
            "collider_has_collision": collider.IsValid() and collider.HasAPI(UsdPhysics.CollisionAPI),
            "references_are_relative": not absolute_paths,
            "packaged_visual_exists": packaged_visual_usd.is_file(),
            "packaged_collider_exists": packaged_collider_usd.is_file(),
        }
        report = {
            "schema_version": 2,
            "passed": all(checks.values()),
            "stage": out_usd.name,
            "default_prim": str(stage.GetDefaultPrim().GetPath()),
            "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
            "component_meters_per_unit": component_units,
            "checks": checks,
            "references": references,
            "absolute_references": absolute_paths,
            "prim_count": sum(1 for _ in stage.Traverse()),
            "limitations": ["Static Phase 1 validation only; no dynamic simulation test was run."],
        }
        validation_report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not report["passed"]:
            raise RuntimeError(f"Static validation failed: {validation_report}")
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        simulation_app.close()
    if exit_code:
        return exit_code
    print(f"visual_usd={visual_usd}", flush=True)
    print(f"collider_usd={collider_usd}", flush=True)
    print(f"scene_usd={out_usd}", flush=True)
    print(f"validation_report={validation_report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
