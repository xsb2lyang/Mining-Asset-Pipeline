"""Static validation for a simulation-ready USD asset.

Dynamic tests (drop, settling, contact, and impact) will consume this report
before running PhysX scenarios. Keeping this stage static makes failures
actionable and avoids confusing missing-schema errors with simulation errors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from isaacsim import SimulationApp


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate basic USD physics schemas")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    app = SimulationApp({"headless": True})
    try:
        from pxr import Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.Open(str(args.input))
        if stage is None:
            raise RuntimeError(f"Unable to open USD stage: {args.input}")

        meshes = []
        colliders = []
        rigid_bodies = []
        masses = []
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                meshes.append(str(prim.GetPath()))
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    colliders.append(str(prim.GetPath()))
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rigid_bodies.append(str(prim.GetPath()))
            if prim.HasAPI(UsdPhysics.MassAPI):
                masses.append(str(prim.GetPath()))

        report = {
            "input": str(args.input),
            "mesh_count": len(meshes),
            "collider_count": len(colliders),
            "rigid_body_count": len(rigid_bodies),
            "mass_api_count": len(masses),
            "checks": {
                "has_mesh": bool(meshes),
                "all_meshes_have_collision": bool(meshes) and len(meshes) == len(colliders),
                "has_rigid_body": bool(rigid_bodies),
                "has_mass_api": bool(masses),
            },
            "rigid_bodies": rigid_bodies,
            "mass_apis": masses,
        }
        report["status"] = "ok" if all(report["checks"].values()) else "failed"
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "ok" else 2
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
