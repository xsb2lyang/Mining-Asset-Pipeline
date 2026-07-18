"""Static USD schema inspector (Kit-bootstrapped).

Bootstraps via ``isaacsim.SimulationApp`` so that ``pxr``/UsdPhysics schema
plugins are registered, then writes a JSON report to ``--out``. Writing the
report to disk avoids relying on stdout, which Kit can intercept in headless
mode.

Usage::

    /path/to/isaac-sim-5.1.0/python.sh scripts/inspect_physics.py \\
        --input mug_physics.usd \\
        --out   mug_physics_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp
    app = SimulationApp({"headless": True})
    try:
        from pxr import Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.Open(str(args.input))
        if stage is None:
            raise RuntimeError(f"Unable to open USD stage: {args.input}")

        meshes, colliders, rigid_bodies, masses = [], [], [], []
        collision_approx = {}

        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                meshes.append(str(prim.GetPath()))
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    colliders.append(str(prim.GetPath()))
                    mc = UsdPhysics.MeshCollisionAPI(prim)
                    if mc and mc.GetApproximationAttr():
                        collision_approx[str(prim.GetPath())] = mc.GetApproximationAttr().Get()
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rigid_bodies.append(str(prim.GetPath()))
            if prim.HasAPI(UsdPhysics.MassAPI):
                m = prim.GetAttribute("physics:mass").Get() if prim.HasAttribute("physics:mass") else None
                d = prim.GetAttribute("physics:density").Get() if prim.HasAttribute("physics:density") else None
                masses.append({"prim": str(prim.GetPath()), "mass_kg": m, "density_kg_m3": d})

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
            "collision_approximation": collision_approx,
        }
        report["status"] = "ok" if all(report["checks"].values()) else "failed"

        # Write to disk FIRST, then also print (Kit may swallow stdout).
        args.out.write_text(json.dumps(report, indent=2))
        print(f"[inspect] wrote {args.out}", flush=True)
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report["status"] == "ok" else 2
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
