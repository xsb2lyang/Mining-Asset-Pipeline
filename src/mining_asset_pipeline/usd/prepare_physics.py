"""Add initial rigid-body, collision, and mass properties to a USD asset.

This is the deterministic preprocessing stage. It does not claim that a
mass inferred from RGB is physically correct; the caller must provide mass or
density from a mining-asset prior, measurement, or metadata registry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from isaacsim import SimulationApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add PhysX properties to a USD asset")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collision", choices=("convexHull", "convexDecomposition", "sdf"), default="convexDecomposition")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mass", type=float, help="Mass in kilograms")
    group.add_argument("--density", type=float, help="Density in kg/m^3")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    if args.output.resolve() == args.input.resolve():
        raise ValueError("--output must be different from --input")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    app = SimulationApp({"headless": True})
    try:
        from pxr import Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.Open(str(args.input))
        if stage is None:
            raise RuntimeError(f"Unable to open USD stage: {args.input}")

        root_prims = [prim for prim in stage.GetPseudoRoot().GetChildren() if prim.IsDefined()]
        if not root_prims:
            raise RuntimeError("The USD stage has no top-level prim")

        # Use the first imported top-level prim as the rigid-body root. A later
        # asset policy can replace this with an explicit root-prim convention.
        root = root_prims[0]
        UsdPhysics.RigidBodyAPI.Apply(root)
        mass_api = UsdPhysics.MassAPI.Apply(root)
        if args.mass is not None:
            mass_api.CreateMassAttr().Set(float(args.mass))
        else:
            mass_api.CreateDensityAttr().Set(float(args.density))

        mesh_count = 0
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh):
                continue
            mesh_count += 1
            UsdPhysics.CollisionAPI.Apply(prim)
            mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(prim)
            mesh_collision.CreateApproximationAttr().Set(args.collision)

        if mesh_count == 0:
            raise RuntimeError("No UsdGeom.Mesh prims found in the USD asset")

        stage.GetRootLayer().Export(str(args.output))
        print(json.dumps({
            "status": "ok",
            "input": str(args.input),
            "output": str(args.output),
            "rigid_body_root": str(root.GetPath()),
            "mesh_count": mesh_count,
            "collision": args.collision,
            "mass_kg": args.mass,
            "density_kg_m3": args.density,
        }))
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
