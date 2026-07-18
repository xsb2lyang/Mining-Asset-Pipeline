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
    ap.add_argument("--expected", type=Path, help="Optional JSON snapshot of expected authored values")
    args = ap.parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp
    app = SimulationApp({"headless": True})
    try:
        from pxr import PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade

        stage = Usd.Stage.Open(str(args.input))
        if stage is None:
            raise RuntimeError(f"Unable to open USD stage: {args.input}")

        meshes, colliders, rigid_bodies, masses = [], [], [], []
        physics_materials, material_bindings, rigid_values = [], [], {}
        collision_values = {}
        collision_approx = {}

        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                meshes.append(str(prim.GetPath()))
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    colliders.append(str(prim.GetPath()))
                    collision_values[str(prim.GetPath())] = {
                        "enabled": UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get(),
                    }
                    mc = UsdPhysics.MeshCollisionAPI(prim)
                    if mc and mc.GetApproximationAttr():
                        collision_approx[str(prim.GetPath())] = mc.GetApproximationAttr().Get()
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rigid_bodies.append(str(prim.GetPath()))
                rigid = UsdPhysics.RigidBodyAPI(prim)
                physx_rigid = PhysxSchema.PhysxRigidBodyAPI(prim)
                rigid_values[str(prim.GetPath())] = {
                    "enabled": rigid.GetRigidBodyEnabledAttr().Get(),
                    "enable_ccd": physx_rigid.GetEnableCCDAttr().Get(),
                    "disable_gravity": physx_rigid.GetDisableGravityAttr().Get(),
                    "linear_damping": physx_rigid.GetLinearDampingAttr().Get(),
                    "angular_damping": physx_rigid.GetAngularDampingAttr().Get(),
                }
            if prim.HasAPI(UsdPhysics.MassAPI):
                m = prim.GetAttribute("physics:mass").Get() if prim.HasAttribute("physics:mass") else None
                d = prim.GetAttribute("physics:density").Get() if prim.HasAttribute("physics:density") else None
                masses.append({"prim": str(prim.GetPath()), "mass_kg": m, "density_kg_m3": d})
            if prim.HasAPI(UsdPhysics.MaterialAPI):
                api = UsdPhysics.MaterialAPI(prim)
                physx = PhysxSchema.PhysxMaterialAPI(prim)
                physics_materials.append({
                    "prim": str(prim.GetPath()),
                    "static_friction": api.GetStaticFrictionAttr().Get(),
                    "dynamic_friction": api.GetDynamicFrictionAttr().Get(),
                    "restitution": api.GetRestitutionAttr().Get(),
                    "friction_combine_mode": physx.GetFrictionCombineModeAttr().Get(),
                    "restitution_combine_mode": physx.GetRestitutionCombineModeAttr().Get(),
                })

        for mesh_path in meshes:
            mesh_prim = stage.GetPrimAtPath(mesh_path)
            try:
                bound, _relationship = UsdShade.MaterialBindingAPI(mesh_prim).ComputeBoundMaterial("physics")
            except Exception:
                bound = None
            if bound and bound.GetPrim().IsValid():
                material_bindings.append({"mesh": mesh_path, "material": str(bound.GetPath())})

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
                "has_physics_material": bool(physics_materials),
                "all_meshes_have_physics_material": bool(meshes) and len(material_bindings) == len(meshes),
            },
            "rigid_bodies": rigid_bodies,
            "mass_apis": masses,
            "collision_approximation": collision_approx,
            "collision_values": collision_values,
            "physics_materials": physics_materials,
            "physics_material_bindings": material_bindings,
            "rigid_body_values": rigid_values,
        }
        if args.expected:
            expected = json.loads(args.expected.read_text(encoding="utf-8"))
            observed_material = physics_materials[0] if physics_materials else {}
            observed_body = next(iter(rigid_values.values()), {})
            observed_mass = masses[0] if masses else {}
            observed_approximations = set(collision_approx.values())
            observed_collision_enabled = {value.get("enabled") for value in collision_values.values()}

            def close(left, right, tolerance=1e-5):
                try:
                    return abs(float(left) - float(right)) <= tolerance
                except (TypeError, ValueError):
                    return False

            material_expected = expected.get("material", {})
            body_expected = expected.get("rigid_body", {})
            mass_expected = expected.get("mass", {})
            matches = {
                "collision_approximation_matches": observed_approximations == {expected.get("collision", {}).get("approximation")},
                "static_friction_matches": close(observed_material.get("static_friction"), material_expected.get("static_friction")),
                "dynamic_friction_matches": close(observed_material.get("dynamic_friction"), material_expected.get("dynamic_friction")),
                "restitution_matches": close(observed_material.get("restitution"), material_expected.get("restitution")),
                "friction_combine_mode_matches": observed_material.get("friction_combine_mode") == material_expected.get("friction_combine_mode"),
                "restitution_combine_mode_matches": observed_material.get("restitution_combine_mode") == material_expected.get("restitution_combine_mode"),
                "rigid_body_enabled_matches": observed_body.get("enabled") == body_expected.get("enabled"),
                "ccd_matches": observed_body.get("enable_ccd") == body_expected.get("enable_ccd"),
                "gravity_matches": observed_body.get("disable_gravity") == body_expected.get("disable_gravity"),
                "linear_damping_matches": close(observed_body.get("linear_damping"), body_expected.get("linear_damping")),
                "angular_damping_matches": close(observed_body.get("angular_damping"), body_expected.get("angular_damping")),
                "collision_enabled_matches": observed_collision_enabled == {expected.get("collision", {}).get("enabled")},
            }
            if mass_expected.get("mode") == "mass":
                matches["mass_matches"] = close(observed_mass.get("mass_kg"), mass_expected.get("mass_kg"))
            else:
                matches["density_matches"] = close(observed_mass.get("density_kg_m3"), mass_expected.get("density_kg_m3"))
            report["expected_value_matches"] = matches
            report["checks"]["authored_values_match_spec"] = all(matches.values())
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
