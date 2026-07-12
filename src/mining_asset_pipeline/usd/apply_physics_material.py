"""Author and bind rigid-body physics properties on an existing USD asset.

This script is deliberately schema-level: it uses the USD Physics and PhysX
schemas that ship with Isaac Sim, rather than the high-level Isaac wrappers.
Consequently, the saved USD remains editable in Isaac Sim's Property panel and
does not depend on an active simulation stage.

It covers every authored attribute exposed by the Isaac Sim 5.1 schemas that
is relevant to a *single rigid mesh asset*:

* ``UsdPhysics.MaterialAPI`` and ``PhysxSchema.PhysxMaterialAPI``;
* ``UsdPhysics.RigidBodyAPI`` and ``PhysxSchema.PhysxRigidBodyAPI``;
* ``UsdPhysics.MassAPI``; and
* ``UsdPhysics.CollisionAPI``, ``UsdPhysics.MeshCollisionAPI`` and
  ``PhysxSchema.PhysxCollisionAPI``.

It intentionally does not create joints, articulations, particle systems,
deformables, or a physics scene.  Those APIs model a different type of asset;
blindly applying them to a SAM3D-generated prop would create invalid semantics.

Run it with Isaac Sim's ``python.sh`` because ``pxr`` schema plugins are
registered by ``SimulationApp``::

    unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
    bash /path/to/isaac-sim-5.1.0/python.sh apply_physics_material.py \\
      --input mug_physics.usd --output mug_material.usd \\
      --static-friction 0.5 --dynamic-friction 0.4 --restitution 0.05

For all options, use ``--help``.  Options are opt-in: unspecified properties
are left exactly as authored in the input USD.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from isaacsim import SimulationApp


COMBINE_MODES = ("average", "min", "multiply", "max")
COLLISION_APPROXIMATIONS = (
    "none",  # triangle mesh; not supported by dynamic rigid bodies
    "convexDecomposition",
    "convexHull",
    "boundingSphere",
    "boundingCube",
    "meshSimplification",  # falls back to convex hull for dynamic bodies
    "sdf",
    "sphereFill",
)


def finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise argparse.ArgumentTypeError("must be a finite number")
    return result


def positive_float(value: str) -> float:
    result = finite_float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def nonnegative_float(value: str) -> float:
    result = finite_float(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return result


def nonnegative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return result


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def axis_mask(value: str) -> int:
    result = int(value, 0)
    if result < 0 or result > 7:
        raise argparse.ArgumentTypeError("must be an axis bit mask from 0 to 7 (X=1, Y=2, Z=4)")
    return result


def add_bool_option(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    parser.add_argument(name, action=argparse.BooleanOptionalAction, default=None, help=help_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add or adjust USD Physics/PhysX properties on a rigid mesh asset.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", type=Path, required=True, help="Source USD asset")
    parser.add_argument("--output", type=Path, required=True, help="Output USD asset; must differ from input")
    parser.add_argument(
        "--root-prim",
        help="Rigid-body root prim. Defaults to the first defined top-level prim in the source stage.",
    )
    parser.add_argument(
        "--material-path",
        help="Physics material prim path. Defaults to <root-prim>/Looks/PhysicsMaterial.",
    )
    parser.add_argument(
        "--bind-to",
        choices=("meshes", "root"),
        default="meshes",
        help="Bind the physics material directly to every descendant mesh (recommended) or only to root.",
    )
    parser.add_argument(
        "--binding-strength",
        choices=("stronger", "weaker"),
        default="stronger",
        help="Whether this material overrides descendant physics-material bindings.",
    )
    parser.add_argument("--report", type=Path, help="Optional JSON report; useful because Kit may capture stdout")

    material = parser.add_argument_group("Physics material (UsdPhysics.MaterialAPI)")
    material.add_argument("--static-friction", type=nonnegative_float, help="Static friction coefficient [0, inf)")
    material.add_argument("--dynamic-friction", type=nonnegative_float, help="Dynamic friction coefficient [0, inf)")
    material.add_argument("--restitution", type=finite_float, help="Restitution / bounciness coefficient [0, 1]")
    material.add_argument(
        "--material-density",
        type=positive_float,
        help="Material density in kg/m^3. Do not combine with MassAPI mass/density for a single rigid body.",
    )
    material.add_argument("--ensure-material", action="store_true", help="Create/bind a material even without values")

    physx_material = parser.add_argument_group("PhysX material extensions (PhysxMaterialAPI)")
    physx_material.add_argument("--friction-combine-mode", choices=COMBINE_MODES)
    physx_material.add_argument("--restitution-combine-mode", choices=COMBINE_MODES)
    physx_material.add_argument(
        "--damping-combine-mode",
        choices=COMBINE_MODES,
        help="Only relevant when compliant contact stiffness is enabled.",
    )
    add_bool_option(
        physx_material,
        "--compliant-contact-acceleration-spring",
        "Use acceleration-spring rather than force-spring behavior for compliant contacts.",
    )
    physx_material.add_argument("--compliant-contact-stiffness", type=nonnegative_float, help="Contact stiffness; 0 disables compliant contact")
    physx_material.add_argument("--compliant-contact-damping", type=nonnegative_float, help="Compliant-contact damping")

    rigid = parser.add_argument_group("Rigid body (RigidBodyAPI / PhysxRigidBodyAPI)")
    rigid.add_argument("--ensure-rigid-body", action="store_true", help="Apply RigidBodyAPI and PhysxRigidBodyAPI without changing a value")
    add_bool_option(rigid, "--rigid-body-enabled", "Enable/disable rigid-body simulation")
    add_bool_option(rigid, "--kinematic-enabled", "Move kinematically rather than through dynamics")
    add_bool_option(rigid, "--starts-asleep", "Initial sleep state")
    rigid.add_argument("--linear-velocity", type=finite_float, nargs=3, metavar=("X", "Y", "Z"), help="Initial linear velocity in m/s")
    rigid.add_argument("--angular-velocity", type=finite_float, nargs=3, metavar=("X", "Y", "Z"), help="Initial angular velocity in degrees/s")
    rigid.add_argument("--linear-damping", type=nonnegative_float)
    rigid.add_argument("--angular-damping", type=nonnegative_float)
    rigid.add_argument("--max-linear-velocity", type=positive_float)
    rigid.add_argument("--max-angular-velocity", type=positive_float, help="Maximum angular velocity in degrees/s")
    rigid.add_argument("--sleep-threshold", type=nonnegative_float)
    rigid.add_argument("--stabilization-threshold", type=nonnegative_float)
    rigid.add_argument("--max-depenetration-velocity", type=positive_float)
    rigid.add_argument("--max-contact-impulse", type=positive_float)
    rigid.add_argument("--solver-position-iterations", type=positive_int, help="PhysX position solver iterations")
    rigid.add_argument("--solver-velocity-iterations", type=positive_int, help="PhysX velocity solver iterations")
    add_bool_option(rigid, "--enable-ccd", "Enable swept continuous collision detection")
    add_bool_option(rigid, "--enable-speculative-ccd", "Enable speculative CCD")
    add_bool_option(rigid, "--retain-accelerations", "Retain accelerations between simulation steps")
    add_bool_option(rigid, "--enable-gyroscopic-forces", "Enable gyroscopic forces")
    add_bool_option(rigid, "--disable-gravity", "Disable gravity for this body")
    add_bool_option(rigid, "--solve-contact", "Include this body in contact solving")
    rigid.add_argument("--locked-pos-axis", type=axis_mask, help="Translation lock bit mask: X=1, Y=2, Z=4")
    rigid.add_argument("--locked-rot-axis", type=axis_mask, help="Rotation lock bit mask: X=1, Y=2, Z=4")
    rigid.add_argument("--contact-slop-coefficient", type=nonnegative_float)
    rigid.add_argument("--cfm-scale", type=nonnegative_float, help="Constraint-force-mixing scale")

    mass = parser.add_argument_group("Mass and inertia (MassAPI)")
    mass.add_argument("--ensure-mass-api", action="store_true", help="Apply MassAPI without changing a value")
    mass_choice = mass.add_mutually_exclusive_group()
    mass_choice.add_argument("--mass", type=positive_float, help="Explicit mass in kg")
    mass_choice.add_argument("--mass-density", type=positive_float, help="MassAPI density in kg/m^3; PhysX derives mass/inertia")
    mass.add_argument("--center-of-mass", type=finite_float, nargs=3, metavar=("X", "Y", "Z"), help="Local center of mass in metres")
    mass.add_argument("--diagonal-inertia", type=nonnegative_float, nargs=3, metavar=("IX", "IY", "IZ"), help="Principal moments of inertia in kg*m^2")
    mass.add_argument("--principal-axes", type=finite_float, nargs=4, metavar=("W", "X", "Y", "Z"), help="Local inertia-frame quaternion, W X Y Z")

    collision = parser.add_argument_group("Collision (CollisionAPI / MeshCollisionAPI / PhysxCollisionAPI)")
    collision.add_argument("--ensure-collision", action="store_true", help="Apply collision schemas to every mesh without changing a value")
    add_bool_option(collision, "--collision-enabled", "Enable/disable collision on every descendant mesh")
    collision.add_argument("--collision-approximation", choices=COLLISION_APPROXIMATIONS, help="Collider approximation for every descendant mesh")
    collision.add_argument("--contact-offset", type=positive_float, help="Contact-generation distance in metres; must exceed rest offset")
    collision.add_argument("--rest-offset", type=finite_float, help="Rest separation distance in metres; must be less than contact offset")
    collision.add_argument("--torsional-patch-radius", type=nonnegative_float, help="Torsional friction patch radius in metres")
    collision.add_argument("--min-torsional-patch-radius", type=nonnegative_float, help="Minimum torsional friction patch radius in metres")

    args = parser.parse_args()
    if args.restitution is not None and not 0 <= args.restitution <= 1:
        parser.error("--restitution must be in [0, 1]")
    if args.material_density is not None and (args.mass is not None or args.mass_density is not None):
        parser.error("--material-density cannot be combined with --mass or --mass-density on one rigid asset")
    if args.contact_offset is not None and args.rest_offset is not None and args.contact_offset <= args.rest_offset:
        parser.error("--contact-offset must be greater than --rest-offset")
    return args


def first_root_prim(stage: Any) -> Any:
    roots = [prim for prim in stage.GetPseudoRoot().GetChildren() if prim.IsDefined()]
    if not roots:
        raise RuntimeError("The USD stage has no defined top-level prim")
    return roots[0]


def meshes_below(root: Any, usd: Any, usd_geom: Any) -> list[Any]:
    return [prim for prim in usd.PrimRange(root) if prim.IsA(usd_geom.Mesh)]


def has_any(args: argparse.Namespace, names: Iterable[str]) -> bool:
    return any(getattr(args, name) is not None for name in names)


def set_if_given(api: Any, getter: str, value: Any) -> bool:
    if value is None:
        return False
    getattr(api, getter)().Set(value)
    return True


def validate_existing_offsets(meshes: Iterable[Any], physx_schema: Any) -> None:
    for mesh in meshes:
        api = physx_schema.PhysxCollisionAPI(mesh)
        contact = api.GetContactOffsetAttr().Get()
        rest = api.GetRestOffsetAttr().Get()
        if contact is not None and rest is not None and math.isfinite(contact) and math.isfinite(rest) and contact <= rest:
            raise ValueError(f"{mesh.GetPath()}: contact offset ({contact}) must exceed rest offset ({rest})")


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(args.input)
    if args.output.resolve() == args.input.resolve():
        raise ValueError("--output must be different from --input")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    app = SimulationApp({"headless": True})
    try:
        from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade

        stage = Usd.Stage.Open(str(args.input))
        if stage is None:
            raise RuntimeError(f"Unable to open USD stage: {args.input}")
        root = stage.GetPrimAtPath(args.root_prim) if args.root_prim else first_root_prim(stage)
        if not root or not root.IsDefined():
            raise ValueError(f"--root-prim does not name a defined prim: {args.root_prim}")
        meshes = meshes_below(root, Usd, UsdGeom)
        if not meshes:
            raise RuntimeError(f"No UsdGeom.Mesh prim exists below {root.GetPath()}")

        material_fields = (
            "static_friction", "dynamic_friction", "restitution", "material_density",
            "friction_combine_mode", "restitution_combine_mode", "damping_combine_mode",
            "compliant_contact_acceleration_spring", "compliant_contact_stiffness", "compliant_contact_damping",
        )
        rigid_fields = (
            "rigid_body_enabled", "kinematic_enabled", "starts_asleep", "linear_velocity", "angular_velocity",
            "linear_damping", "angular_damping", "max_linear_velocity", "max_angular_velocity", "sleep_threshold",
            "stabilization_threshold", "max_depenetration_velocity", "max_contact_impulse",
            "solver_position_iterations", "solver_velocity_iterations", "enable_ccd", "enable_speculative_ccd",
            "retain_accelerations", "enable_gyroscopic_forces", "disable_gravity", "solve_contact",
            "locked_pos_axis", "locked_rot_axis", "contact_slop_coefficient", "cfm_scale",
        )
        mass_fields = ("mass", "mass_density", "center_of_mass", "diagonal_inertia", "principal_axes")
        collision_fields = (
            "collision_enabled", "collision_approximation", "contact_offset", "rest_offset",
            "torsional_patch_radius", "min_torsional_patch_radius",
        )

        changes: dict[str, Any] = {"material": [], "rigid_body": [], "mass": [], "collision": []}

        if args.ensure_material or has_any(args, material_fields):
            material_path = args.material_path or f"{root.GetPath()}/Looks/PhysicsMaterial"
            if not material_path.startswith("/"):
                raise ValueError("--material-path must be an absolute USD prim path")
            material = UsdShade.Material.Define(stage, material_path)
            material_api = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
            physx_material_api = PhysxSchema.PhysxMaterialAPI.Apply(material.GetPrim())
            for arg_name, getter in (
                ("static_friction", "GetStaticFrictionAttr"),
                ("dynamic_friction", "GetDynamicFrictionAttr"),
                ("restitution", "GetRestitutionAttr"),
                ("material_density", "GetDensityAttr"),
            ):
                if set_if_given(material_api, getter, getattr(args, arg_name)):
                    changes["material"].append(arg_name)
            for arg_name, getter in (
                ("friction_combine_mode", "GetFrictionCombineModeAttr"),
                ("restitution_combine_mode", "GetRestitutionCombineModeAttr"),
                ("damping_combine_mode", "GetDampingCombineModeAttr"),
                ("compliant_contact_acceleration_spring", "GetCompliantContactAccelerationSpringAttr"),
                ("compliant_contact_stiffness", "GetCompliantContactStiffnessAttr"),
                ("compliant_contact_damping", "GetCompliantContactDampingAttr"),
            ):
                if set_if_given(physx_material_api, getter, getattr(args, arg_name)):
                    changes["material"].append(arg_name)
            binding_targets = meshes if args.bind_to == "meshes" else [root]
            strength = UsdShade.Tokens.strongerThanDescendants if args.binding_strength == "stronger" else UsdShade.Tokens.weakerThanDescendants
            for target in binding_targets:
                UsdShade.MaterialBindingAPI.Apply(target).Bind(
                    material, bindingStrength=strength, materialPurpose="physics"
                )
            changes["material"].append("physics_material_binding")

        if args.ensure_rigid_body or has_any(args, rigid_fields):
            rigid_api = UsdPhysics.RigidBodyAPI.Apply(root)
            physx_rigid_api = PhysxSchema.PhysxRigidBodyAPI.Apply(root)
            for arg_name, getter in (
                ("rigid_body_enabled", "GetRigidBodyEnabledAttr"),
                ("kinematic_enabled", "GetKinematicEnabledAttr"),
                ("starts_asleep", "GetStartsAsleepAttr"),
            ):
                if set_if_given(rigid_api, getter, getattr(args, arg_name)):
                    changes["rigid_body"].append(arg_name)
            if args.linear_velocity is not None:
                rigid_api.GetVelocityAttr().Set(Gf.Vec3f(*args.linear_velocity))
                changes["rigid_body"].append("linear_velocity")
            if args.angular_velocity is not None:
                rigid_api.GetAngularVelocityAttr().Set(Gf.Vec3f(*args.angular_velocity))
                changes["rigid_body"].append("angular_velocity")
            for arg_name, getter in (
                ("linear_damping", "GetLinearDampingAttr"),
                ("angular_damping", "GetAngularDampingAttr"),
                ("max_linear_velocity", "GetMaxLinearVelocityAttr"),
                ("max_angular_velocity", "GetMaxAngularVelocityAttr"),
                ("sleep_threshold", "GetSleepThresholdAttr"),
                ("stabilization_threshold", "GetStabilizationThresholdAttr"),
                ("max_depenetration_velocity", "GetMaxDepenetrationVelocityAttr"),
                ("max_contact_impulse", "GetMaxContactImpulseAttr"),
                ("solver_position_iterations", "GetSolverPositionIterationCountAttr"),
                ("solver_velocity_iterations", "GetSolverVelocityIterationCountAttr"),
                ("enable_ccd", "GetEnableCCDAttr"),
                ("enable_speculative_ccd", "GetEnableSpeculativeCCDAttr"),
                ("retain_accelerations", "GetRetainAccelerationsAttr"),
                ("enable_gyroscopic_forces", "GetEnableGyroscopicForcesAttr"),
                ("disable_gravity", "GetDisableGravityAttr"),
                ("solve_contact", "GetSolveContactAttr"),
                ("locked_pos_axis", "GetLockedPosAxisAttr"),
                ("locked_rot_axis", "GetLockedRotAxisAttr"),
                ("contact_slop_coefficient", "GetContactSlopCoefficientAttr"),
                ("cfm_scale", "GetCfmScaleAttr"),
            ):
                if set_if_given(physx_rigid_api, getter, getattr(args, arg_name)):
                    changes["rigid_body"].append(arg_name)

        if args.ensure_mass_api or has_any(args, mass_fields):
            mass_api = UsdPhysics.MassAPI.Apply(root)
            for arg_name, getter in (("mass", "GetMassAttr"), ("mass_density", "GetDensityAttr")):
                if set_if_given(mass_api, getter, getattr(args, arg_name)):
                    changes["mass"].append(arg_name)
            if args.center_of_mass is not None:
                mass_api.GetCenterOfMassAttr().Set(Gf.Vec3f(*args.center_of_mass))
                changes["mass"].append("center_of_mass")
            if args.diagonal_inertia is not None:
                mass_api.GetDiagonalInertiaAttr().Set(Gf.Vec3f(*args.diagonal_inertia))
                changes["mass"].append("diagonal_inertia")
            if args.principal_axes is not None:
                w, x, y, z = args.principal_axes
                norm = math.sqrt(w * w + x * x + y * y + z * z)
                if norm == 0:
                    raise ValueError("--principal-axes cannot be the zero quaternion")
                mass_api.GetPrincipalAxesAttr().Set(Gf.Quatf(w / norm, Gf.Vec3f(x / norm, y / norm, z / norm)))
                changes["mass"].append("principal_axes")

        if args.ensure_collision or has_any(args, collision_fields):
            for mesh in meshes:
                collision_api = UsdPhysics.CollisionAPI.Apply(mesh)
                if set_if_given(collision_api, "GetCollisionEnabledAttr", args.collision_enabled):
                    changes["collision"].append(f"{mesh.GetPath()}:collision_enabled")
                if args.collision_approximation is not None:
                    UsdPhysics.MeshCollisionAPI.Apply(mesh).GetApproximationAttr().Set(args.collision_approximation)
                    changes["collision"].append(f"{mesh.GetPath()}:collision_approximation")
                if any(getattr(args, key) is not None for key in collision_fields[2:]):
                    physx_collision_api = PhysxSchema.PhysxCollisionAPI.Apply(mesh)
                    for arg_name, getter in (
                        ("contact_offset", "GetContactOffsetAttr"),
                        ("rest_offset", "GetRestOffsetAttr"),
                        ("torsional_patch_radius", "GetTorsionalPatchRadiusAttr"),
                        ("min_torsional_patch_radius", "GetMinTorsionalPatchRadiusAttr"),
                    ):
                        if set_if_given(physx_collision_api, getter, getattr(args, arg_name)):
                            changes["collision"].append(f"{mesh.GetPath()}:{arg_name}")
            validate_existing_offsets(meshes, PhysxSchema)

        if not any(changes.values()) and not (args.ensure_material or args.ensure_rigid_body or args.ensure_mass_api or args.ensure_collision):
            raise ValueError("No property requested. Pass at least one physics option; use --help for the full list.")

        stage.GetRootLayer().Export(str(args.output))
        report = {
            "status": "ok",
            "input": str(args.input),
            "output": str(args.output),
            "root_prim": str(root.GetPath()),
            "mesh_paths": [str(mesh.GetPath()) for mesh in meshes],
            "changes": changes,
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
