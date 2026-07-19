#!/usr/bin/env python3
"""Author the Isaac Sim half of a renderable Marble Phase 1 scene.

Run with Isaac Sim's ``python.sh``.  The script deliberately creates separate
visual and collision prims: a material-preserving textured GLB for rendering,
or a standard colored-point fallback from Marble's PLY, and a geometry-only
GLB for kinematic physics. This is portable across Isaac Sim 5.1 installations
and avoids the legacy NuRec visual dependency.
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
    visual_group = parser.add_mutually_exclusive_group(required=True)
    visual_group.add_argument("--visual-glb", type=Path)
    visual_group.add_argument("--ply", type=Path, help="Marble Gaussian-splat PLY fallback")
    visual_group.add_argument("--pano", type=Path, help="Marble panorama PNG textured-collider fallback")
    parser.add_argument("--collider-glb", type=Path, required=True)
    parser.add_argument("--visual-usd", type=Path, required=True)
    parser.add_argument("--collider-usd", type=Path, required=True)
    parser.add_argument("--out-usd", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument("--scene-scale", type=float, default=1.0)
    parser.add_argument("--converter-timeout", type=float, default=300.0)
    parser.add_argument(
        "--max-point-count",
        type=int,
        default=500_000,
        help="Maximum sampled points for a standard USD point-cloud fallback (default: 500000)",
    )
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


def _has_renderable_geometry(prim) -> bool:
    from pxr import UsdGeom

    return any(
        child.IsA(UsdGeom.Mesh) or child.IsA(UsdGeom.Points)
        for child in prim.GetStage().Traverse()
        if child.GetPath().HasPrefix(prim.GetPath())
    )


def _read_binary_gaussian_ply(ply: Path, max_point_count: int):
    """Read Marble's binary Gaussian PLY and return sampled positions/colors.

    Marble PLY stores the DC spherical-harmonic coefficient, not direct RGB.
    The conversion below is the standard 3D Gaussian Splatting DC decode:
    ``rgb = 0.5 + C0 * f_dc``.  Standard ``UsdGeom.Points`` has no anisotropic
    Gaussian parameters, so this is explicitly a colored, lower-fidelity
    fallback rather than an attempt to reproduce the splat renderer.
    """
    import numpy as np

    if max_point_count <= 0:
        raise ValueError("--max-point-count must be positive")
    header = bytearray()
    with ply.open("rb") as stream:
        while True:
            line = stream.readline()
            if not line:
                raise ValueError(f"PLY header is incomplete: {ply}")
            header.extend(line)
            if line == b"end_header\n":
                break
    lines = header.decode("ascii", "replace").splitlines()
    if "format binary_little_endian 1.0" not in lines:
        raise ValueError(f"Only binary_little_endian PLY is supported: {ply}")
    vertex_line = next((line for line in lines if line.startswith("element vertex ")), None)
    if vertex_line is None:
        raise ValueError(f"PLY contains no vertex element: {ply}")
    vertex_count = int(vertex_line.rsplit(" ", 1)[1])
    required = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2")
    names = [line.split(" ")[-1] for line in lines if line.startswith("property float ")]
    missing = sorted(set(required).difference(names))
    if missing:
        raise ValueError(f"PLY lacks Marble Gaussian attributes: {', '.join(missing)}")
    dtype = np.dtype([(name, "<f4") for name in names])
    values = np.fromfile(ply, dtype=dtype, count=vertex_count, offset=len(header))
    if len(values) != vertex_count:
        raise ValueError(f"PLY is truncated: expected {vertex_count} vertices, read {len(values)}")
    indices = np.linspace(0, vertex_count - 1, min(vertex_count, max_point_count), dtype=np.int64)
    values = values[indices]
    points = np.column_stack((values["x"], values["y"], values["z"])).astype(np.float32)
    dc = np.column_stack((values["f_dc_0"], values["f_dc_1"], values["f_dc_2"])).astype(np.float32)
    colors = np.clip(0.5 + 0.28209479177387814 * dc, 0.0, 1.0)
    opacity = 1.0 / (1.0 + np.exp(-np.clip(values["opacity"], -20.0, 20.0)))
    radii = 2.0 * np.exp(np.clip(np.max(
        np.column_stack((values["scale_0"], values["scale_1"], values["scale_2"])), axis=1
    ), -12.0, 0.0))
    widths = np.clip(radii, 0.002, 0.15).astype(np.float32)
    return points, colors.astype(np.float32), opacity.astype(np.float32), widths


def _convert_gaussian_ply_to_points_usd(ply: Path, output: Path, max_point_count: int) -> int:
    """Write a portable colored-point USD visual fallback from a Marble PLY."""
    from pxr import Usd, UsdGeom, Vt

    points, colors, opacity, widths = _read_binary_gaussian_ply(ply, max_point_count)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    stage = Usd.Stage.CreateNew(str(output))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/PointCloud")
    stage.SetDefaultPrim(root.GetPrim())
    cloud = UsdGeom.Points.Define(stage, "/PointCloud/Points")
    cloud.CreatePointsAttr().Set(Vt.Vec3fArray.FromNumpy(points))
    cloud.CreateWidthsAttr().Set(Vt.FloatArray.FromNumpy(widths))
    cloud.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex).Set(Vt.Vec3fArray.FromNumpy(colors))
    cloud.CreateDisplayOpacityPrimvar(UsdGeom.Tokens.vertex).Set(Vt.FloatArray.FromNumpy(opacity))
    stage.Save()
    return len(points)


def _convert_collider_to_pano_visual_usd(
    collider_glb: Path, output: Path, pano: Path, timeout: float
) -> None:
    """Create a colored visual fallback by spherical-projecting Marble's pano.

    This is intentionally marked degraded: one panorama cannot provide the
    full view-dependent texture fidelity of Marble's exported HQ mesh. It is,
    however, a conventional textured USD mesh that Isaac Sim 5.1 renders.
    """
    from pxr import Sdf, Usd, UsdGeom, UsdShade, Vt
    import numpy as np

    asyncio.get_event_loop().run_until_complete(
        _convert_glb_to_usd(collider_glb, output, preserve_materials=False, timeout=timeout)
    )
    shutil.copy2(pano, output.parent / pano.name)
    stage = Usd.Stage.Open(str(output))
    if stage is None:
        raise RuntimeError(f"Unable to reopen converted visual fallback: {output}")
    root = stage.GetDefaultPrim()
    if not root.IsValid():
        raise RuntimeError(f"Converted visual fallback has no default prim: {output}")
    looks_path = root.GetPath().AppendPath("Looks/PanoramaFallback")
    material = UsdShade.Material.Define(stage, looks_path)
    shader = UsdShade.Shader.Define(stage, looks_path.AppendPath("PreviewSurface"))
    shader.CreateIdAttr("UsdPreviewSurface")
    texture = UsdShade.Shader.Define(stage, looks_path.AppendPath("PanoTexture"))
    texture.CreateIdAttr("UsdUVTexture")
    texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(pano.name))
    reader = UsdShade.Shader.Define(stage, looks_path.AppendPath("StReader"))
    reader.CreateIdAttr("UsdPrimvarReader_float2")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
    # A single Marble pano is already exposure-baked. Use it as emission so a
    # bright Isaac dome light does not wash the fallback into an almost-white
    # diffuse surface.
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set((0.0, 0.0, 0.0))
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        texture.ConnectableAPI(), "rgb"
    )
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    bound = 0
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points = np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float32)
        if len(points) == 0:
            continue
        centered = points - points.mean(axis=0, keepdims=True)
        radius = np.linalg.norm(centered, axis=1)
        radius = np.maximum(radius, 1e-6)
        # Equirectangular pano mapping. The source GLB and PLY share Marble's
        # local frame, so this preserves broad color/layout cues.
        u = 0.5 + np.arctan2(centered[:, 0], centered[:, 2]) / (2.0 * np.pi)
        v = 0.5 - np.arcsin(np.clip(centered[:, 1] / radius, -1.0, 1.0)) / np.pi
        st = np.column_stack((u, v)).astype(np.float32)
        UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
        ).Set(
            Vt.Vec2fArray.FromNumpy(st)
        )
        UsdShade.MaterialBindingAPI(mesh).Bind(material)
        bound += 1
    if not bound:
        raise RuntimeError("Converted collider contains no mesh for panorama fallback")
    stage.GetRootLayer().Save()


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
    visual_glb = require_file(args.visual_glb, "Visual GLB") if args.visual_glb else None
    ply = require_file(args.ply, "Marble PLY") if args.ply else None
    pano = require_file(args.pano, "Marble panorama") if args.pano else None
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
            if visual_glb:
                print(f"[phase1] converting visible textured mesh: {visual_glb}", flush=True)
                loop.run_until_complete(
                    _convert_glb_to_usd(
                        visual_glb,
                        visual_usd,
                        preserve_materials=True,
                        timeout=args.converter_timeout,
                    )
                )
                visual_representation = "textured_mesh"
                visual_point_count = None
            elif pano:
                print(f"[phase1] projecting Marble pano onto collider fallback: {pano}", flush=True)
                _convert_collider_to_pano_visual_usd(
                    collider_glb, visual_usd, pano, args.converter_timeout
                )
                visual_representation = "pano_textured_collider_fallback"
                visual_point_count = None
            else:
                assert ply is not None
                print(f"[phase1] converting Marble PLY to colored USD points: {ply}", flush=True)
                visual_point_count = _convert_gaussian_ply_to_points_usd(
                    ply, visual_usd, args.max_point_count
                )
                visual_representation = "colored_point_cloud_fallback"
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
            "visual_has_renderable_geometry": visual.IsValid() and _has_renderable_geometry(visual),
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
            "visual_representation": visual_representation,
            "visual_point_count": visual_point_count,
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
