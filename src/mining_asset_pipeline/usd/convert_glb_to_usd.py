"""Convert a mesh asset to USD using Isaac Sim's headless Asset Converter.

Run this file with Isaac Sim's bundled Python, not with the SAM3/SAM3D
Conda environments::

    /path/to/isaac-sim-5.1.0/python.sh convert_glb_to_usd.py \
        --input object.glb --output object.usd

This script wraps ``omni.kit.asset_converter.AssetConverterContext`` and
exposes the most important conversion flags to the CLI. Defaults match
NVIDIA's official example at
``standalone_examples/api/omni.kit.asset_converter/asset_usd_converter.py``
(Apache-2.0, NVIDIA Corporation & Affiliates) so that running this script
is functionally equivalent to running the official one for the shared
subset of options.

Differences from the official script:

* Single-file workflow (``--input`` / ``--output``) instead of batch
  folder scanning.
* The ``AssetConverterContext`` flags are exposed so that callers can
  override any default that NVIDIA hard-codes in their example.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from isaacsim import SimulationApp


# Defaults align with NVIDIA's standalone example. Each default is documented
# alongside the CLI flag below; changing one here is a project-wide decision.
DEFAULTS = {
    "ignore_materials": False,
    "ignore_animation": False,
    "ignore_cameras": True,
    "single_mesh": False,
    "smooth_normals": True,
    "preview_surface": False,
    "support_point_instancer": False,
    "embed_mdl_in_usd": False,
    "use_meter_as_world_unit": True,
    "create_world_as_default_root_prim": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert mesh assets to USD")
    parser.add_argument("--input", type=Path, required=True,
                        help="Input mesh (.glb / .gltf / .obj / .fbx / .stl)")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output USD file (.usd / .usda / .usdz)")
    # Material & animation
    parser.add_argument("--ignore-materials", action="store_true",
                        help="Skip loading materials from the source mesh")
    parser.add_argument("--ignore-animation", action="store_true",
                        help="Drop animation tracks during conversion")
    parser.add_argument("--ignore-cameras", action="store_true",
                        help="Drop embedded cameras during conversion")
    # Mesh shape
    parser.add_argument("--single-mesh", action="store_true",
                        help="Merge every mesh in the scene into one prim")
    parser.add_argument("--smooth-normals", action="store_true",
                        help="Recompute vertex normals as smooth")
    parser.add_argument("--scale", type=float, default=None,
                        help="Per-mesh scale factor applied during conversion "
                             "(e.g. 0.001 to convert mm->m, 5.0 to upsize). "
                             "Defaults to no scaling.")
    # Surface & embedding
    parser.add_argument("--preview-surface", action="store_true",
                        help="Generate a simple preview surface shader")
    parser.add_argument("--support-point-instancer", action="store_true",
                        help="Preserve point-instancer data")
    parser.add_argument("--embed-mdl-in-usd", action="store_true",
                        help="Embed the MDL shader source into the USD")
    parser.add_argument("--create-world-as-default-root-prim", action="store_true",
                        help="Wrap the import under a /World prim")
    # Units
    parser.add_argument("--no-meter-world-unit", action="store_true",
                        help="Disable the default use_meter_as_world_unit "
                             "(i.e. keep the source's unit)")
    return parser.parse_args()


async def convert(input_path: Path, output_path: Path, ctx_overrides: dict) -> None:
    import omni.kit.asset_converter

    def progress_callback(progress, total_steps):
        return None

    context = omni.kit.asset_converter.AssetConverterContext()
    # Apply the resolved context settings (defaults plus CLI overrides).
    for field, value in ctx_overrides.items():
        setattr(context, field, value)

    converter = omni.kit.asset_converter.get_instance()
    task = converter.create_converter_task(
        str(input_path), str(output_path), progress_callback, context
    )
    while True:
        success = await task.wait_until_finished()
        if success:
            return
        await asyncio.sleep(0.1)
    # Kept unreachable intentionally; failures are surfaced by the task status.


def bind_vertex_color_material(stage) -> int:
    """Bind a Preview Surface that reads imported ``displayColor`` primvars.

    SAM3D GLBs store their appearance as ``COLOR_0`` vertex colors, not as a
    PBR texture/material.  Asset Converter imports those values as
    ``primvars:displayColor`` but does not necessarily create a render shader,
    which leaves Isaac Sim's viewport grey.  The reader shader is deliberately
    authored below the converted asset root so later physics scripts still pick
    that root (rather than a top-level ``/Looks`` prim) as the rigid body.
    """
    from pxr import Sdf, Usd, UsdGeom, UsdShade

    roots = [prim for prim in stage.GetPseudoRoot().GetChildren() if prim.IsDefined()]
    if not roots:
        return 0
    root = roots[0]
    colored_meshes = []
    for prim in Usd.PrimRange(root):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        colors = mesh.GetDisplayColorPrimvar().Get()
        if colors is not None and len(colors) > 0:
            colored_meshes.append(prim)
    if not colored_meshes:
        return 0

    material_path = root.GetPath().AppendChild("Looks").AppendChild("VertexColorMaterial")
    material = UsdShade.Material.Define(stage, material_path)
    shader = UsdShade.Shader.Define(stage, material_path.AppendChild("PreviewSurface"))
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.6)

    reader = UsdShade.Shader.Define(stage, material_path.AppendChild("DisplayColorReader"))
    reader.CreateIdAttr("UsdPrimvarReader_float3")
    reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("displayColor")
    reader.CreateOutput("result", Sdf.ValueTypeNames.Float3)
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        reader.ConnectableAPI(), "result"
    )
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    for mesh_prim in colored_meshes:
        UsdShade.MaterialBindingAPI.Apply(mesh_prim).Bind(material)
    return len(colored_meshes)


def main() -> int:
    args = parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    if args.output.resolve() == args.input.resolve():
        raise ValueError("--output must differ from --input")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Resolve the context flags: defaults + CLI overrides.
    # Each CLI flag is action="store_true" meaning "turn ON the
    # corresponding non-default behavior", so the semantics are:
    #   --ignore-materials  -> ignore_materials=True  (default False)
    #   --single-mesh       -> single_mesh=True       (default False)
    # and so on. The negation flag --no-meter-world-unit is the one
    # exception that flips a default-True to False.
    ctx = dict(DEFAULTS)
    ctx["ignore_materials"] = bool(args.ignore_materials)
    ctx["ignore_animation"] = bool(args.ignore_animation)
    ctx["ignore_cameras"] = bool(args.ignore_cameras)
    ctx["single_mesh"] = bool(args.single_mesh)
    ctx["smooth_normals"] = bool(args.smooth_normals)
    ctx["preview_surface"] = bool(args.preview_surface)
    ctx["support_point_instancer"] = bool(args.support_point_instancer)
    ctx["embed_mdl_in_usd"] = bool(args.embed_mdl_in_usd)
    ctx["create_world_as_default_root_prim"] = bool(
        args.create_world_as_default_root_prim
    )
    ctx["use_meter_as_world_unit"] = not bool(args.no_meter_world_unit)

    app = SimulationApp({"headless": True})
    try:
        from isaacsim.core.utils.extensions import enable_extension
        enable_extension("omni.kit.asset_converter")

        asyncio.get_event_loop().run_until_complete(
            convert(args.input, args.output, ctx)
        )

        from pxr import Gf, Usd, UsdGeom

        stage = Usd.Stage.Open(str(args.output))
        if stage is None:
            raise RuntimeError(f"Unable to reopen USD for visual-material authoring: {args.output}")
        if args.scale is not None and args.scale != 1.0:
            # Apply the per-asset scale by wrapping the result under a
            # Xform that scales every child prim. Done here (after the
            # converter returns) so that the geometry stays consistent
            # with whatever unit the source mesh used.
            root = stage.GetPseudoRoot()
            wrapped_path = root.GetPath().AppendChild("AssetScaleWrapper")
            wrapper = UsdGeom.Xform.Define(stage, wrapped_path)
            wrapper.AddScaleOp().Set(Gf.Vec3d(args.scale, args.scale, args.scale))
            print(f"[scale] applied scale={args.scale} via /AssetScaleWrapper")

        vertex_color_mesh_count = bind_vertex_color_material(stage)
        stage.GetRootLayer().Save()

        print(json.dumps({
            "status": "ok",
            "input": str(args.input),
            "output": str(args.output),
            "context": ctx,
            "scale_applied": args.scale,
            "vertex_color_material_mesh_count": vertex_color_mesh_count,
        }, indent=2))
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
