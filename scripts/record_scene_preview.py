#!/usr/bin/env python3
"""Render a short MP4 preview of a packaged Phase 1 scene with Isaac Sim.

Run this script with Isaac Sim's ``python.sh``. It opens the USD read-only in
the current process, places a temporary animated camera in the session layer,
and asks Isaac Sim's viewport-capture extension to encode an MP4. The source
USD is never saved or modified.
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Iterable


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record an Isaac Sim scene preview as MP4.")
    parser.add_argument("--scene", type=Path, required=True, help="Packaged scene USD to preview")
    parser.add_argument(
        "--bounds-prim",
        default="/World/Collider",
        help="Prim used to frame the automatic camera (default: /World/Collider)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: <scene-dir>/preview)",
    )
    parser.add_argument("--frames", type=int, default=144, help="Number of frames (default: 144)")
    parser.add_argument("--fps", type=int, default=24, help="Output frame rate (default: 24)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1200,
        help="Fail rather than wait indefinitely for Isaac Sim capture (default: 1200)",
    )
    parser.add_argument(
        "--camera-mode",
        choices=("flythrough", "orbit"),
        default="flythrough",
        help="Automatic camera path (default: flythrough)",
    )
    parser.add_argument(
        "--visual-mode",
        choices=("auto", "full", "collider"),
        default="auto",
        help=(
            "What to render: auto uses the visible scene unless it contains NuRec; "
            "collider is a geometry-only fallback (default: auto)"
        ),
    )
    parser.add_argument(
        "--show-ui",
        action="store_true",
        help="Keep the Isaac Sim window visible while recording",
    )
    parser.add_argument("--keep-frames", action="store_true", help="Keep intermediate PNG frames")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing MP4/frames directory")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> tuple[Path, Path]:
    scene = args.scene.expanduser().resolve()
    if not scene.is_file() or scene.suffix.lower() not in {".usd", ".usda", ".usdc"}:
        raise ValueError(f"--scene must be an existing USD file: {scene}")
    if args.frames < 2:
        raise ValueError("--frames must be at least 2")
    if args.fps <= 0 or args.width <= 0 or args.height <= 0 or args.timeout_seconds <= 0:
        raise ValueError("--fps, --width, --height and --timeout-seconds must be positive")
    output_dir = (args.output_dir or scene.parent / "preview").expanduser().resolve()
    return scene, output_dir


def _flythrough_poses(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    frames: int,
) -> Iterable[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Create an interior path along the longest horizontal collider axis."""
    extents = tuple(maximum[index] - minimum[index] for index in range(3))
    travel_axis = 0 if extents[0] >= extents[1] else 1
    transverse_axis = 1 - travel_axis
    travel_min = minimum[travel_axis] + extents[travel_axis] * 0.08
    travel_max = maximum[travel_axis] - extents[travel_axis] * 0.08
    eye_height = minimum[2] + extents[2] * 0.56
    transverse_center = (minimum[transverse_axis] + maximum[transverse_axis]) / 2.0
    look_ahead = max(1.0, extents[travel_axis] * 0.12)
    for index in range(frames):
        progress = index / (frames - 1)
        travel = travel_min + (travel_max - travel_min) * progress
        target_travel = min(travel_max, travel + look_ahead)
        position = [0.0, 0.0, eye_height]
        target = [0.0, 0.0, eye_height]
        position[travel_axis] = travel
        target[travel_axis] = target_travel
        position[transverse_axis] = transverse_center
        target[transverse_axis] = transverse_center
        yield tuple(position), tuple(target)


def _orbit_poses(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    frames: int,
) -> Iterable[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    extents = tuple(maximum[index] - minimum[index] for index in range(3))
    center = tuple((minimum[index] + maximum[index]) / 2.0 for index in range(3))
    radius = max(extents[0], extents[1]) * 0.58 + 1.0
    height = center[2] + max(1.0, extents[2] * 0.35)
    for index in range(frames):
        angle = 2.0 * math.pi * index / (frames - 1)
        position = (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), height)
        yield position, center


def _author_camera_animation(stage, poses, fps: int, clipping_far: float) -> str:
    """Author a short camera animation only in the in-memory session layer."""
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
    try:
        camera = UsdGeom.Camera.Define(stage, Sdf.Path("/World/ScenePreviewCamera"))
        camera.CreateFocalLengthAttr(18.0)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(0.01, clipping_far))
        dome_light = UsdLux.DomeLight.Define(stage, Sdf.Path("/World/ScenePreviewLight"))
        dome_light.CreateIntensityAttr(1500.0)
        dome_light.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
        transform = UsdGeom.Xformable(camera.GetPrim()).AddTransformOp()
        up_axis = UsdGeom.GetStageUpAxis(stage)
        up = {
            UsdGeom.Tokens.x: Gf.Vec3d(1.0, 0.0, 0.0),
            UsdGeom.Tokens.y: Gf.Vec3d(0.0, 1.0, 0.0),
            UsdGeom.Tokens.z: Gf.Vec3d(0.0, 0.0, 1.0),
        }.get(up_axis, Gf.Vec3d(0.0, 0.0, 1.0))
        for frame, (position, target) in enumerate(poses, start=1):
            world = Gf.Matrix4d(1.0).SetLookAt(
                Gf.Vec3d(*position), Gf.Vec3d(*target), up
            ).GetInverse()
            transform.Set(world, Usd.TimeCode(frame))
        stage.SetStartTimeCode(1)
        stage.SetEndTimeCode(frame)
        stage.SetTimeCodesPerSecond(fps)
        stage.SetFramesPerSecond(fps)
        return str(camera.GetPath())
    finally:
        stage.SetEditTarget(previous_target)


def _stage_has_nurec(stage, scene_path: Path) -> bool:
    """Return whether composed references include a legacy NuRec payload."""
    for prim in stage.Traverse():
        references = prim.GetMetadata("references")
        if not references:
            continue
        for item in references.GetAddedOrExplicitItems():
            asset_path = item.assetPath
            if not asset_path.lower().endswith(".usdz"):
                continue
            package_path = (scene_path.parent / asset_path).resolve()
            try:
                with zipfile.ZipFile(package_path) as package:
                    if any(name.lower().endswith(".nurec") for name in package.namelist()):
                        return True
            except (OSError, zipfile.BadZipFile):
                continue
    return False


def _configure_visual_mode(stage, requested_mode: str, has_nurec: bool) -> str:
    """Apply preview-only visibility changes in the session layer."""
    mode = "collider" if requested_mode == "auto" and has_nurec else requested_mode
    if mode != "collider":
        return mode

    from pxr import Usd, UsdGeom

    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
    try:
        visual = stage.GetPrimAtPath("/World/Visual")
        if not visual.IsValid():
            visual = stage.GetPrimAtPath("/World/gauss")  # Legacy NuRec bundle.
        if visual.IsValid():
            UsdGeom.Imageable(visual).MakeInvisible()
        collider = stage.GetPrimAtPath("/World/Collider")
        if not collider.IsValid():
            collider = stage.GetPrimAtPath("/World/Xform")  # Legacy bundle.
        if collider.IsValid():
            UsdGeom.Imageable(collider).MakeVisible()
    finally:
        stage.SetEditTarget(previous_target)
    return mode


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        scene, output_dir = _validate_args(args)
    except ValueError as exc:
        print(f"Invalid preview request: {exc}", file=sys.stderr)
        return 2

    capture_name = f"{scene.stem}_{args.camera_mode}"
    video_path = output_dir / f"{capture_name}.mp4"
    frames_dir = output_dir / f"{capture_name}_frames"
    if video_path.exists() or frames_dir.exists():
        if not args.overwrite:
            print(f"Preview output exists (use --overwrite): {output_dir}", file=sys.stderr)
            return 2
        if video_path.exists():
            video_path.unlink()
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    # NuRec/gaussian scene previews are more stable on one GPU. In particular,
    # a workstation may expose multiple GPUs without fast peer-to-peer links.
    simulation_app = SimulationApp({"headless": not args.show_ui, "multi_gpu": False})
    try:
        import omni.kit.app
        import omni.usd
        from pxr import Usd, UsdGeom

        extension_manager = omni.kit.app.get_app().get_extension_manager()
        if not extension_manager.is_extension_enabled("omni.kit.capture.viewport"):
            if not extension_manager.set_extension_enabled_immediate("omni.kit.capture.viewport", True):
                raise RuntimeError("Isaac Sim could not enable omni.kit.capture.viewport")
        for _ in range(10):
            simulation_app.update()
        from omni.kit.capture.viewport import CaptureExtension, CaptureOptions, CaptureRenderPreset

        context = omni.usd.get_context()
        context.open_stage(str(scene))
        for _ in range(120):
            simulation_app.update()
            if context.get_stage_loading_status()[2] == 0:
                break
        stage = context.get_stage()
        if stage is None:
            raise RuntimeError(f"Isaac Sim could not open scene: {scene}")
        print("[preview] scene opened", flush=True)
        has_nurec = _stage_has_nurec(stage, scene)
        effective_visual_mode = _configure_visual_mode(stage, args.visual_mode, has_nurec)
        if args.visual_mode == "auto" and has_nurec:
            print(
                "[preview] NuRec detected; using visible collider fallback. "
                "Use --visual-mode full to attempt legacy NuRec rendering.",
                flush=True,
            )
        else:
            print(f"[preview] visual mode: {effective_visual_mode}", flush=True)
        collider = stage.GetPrimAtPath(args.bounds_prim)
        if not collider.IsValid():
            collider = stage.GetDefaultPrim()
        if not collider.IsValid():
            raise RuntimeError(
                f"Scene lacks camera framing prim {args.bounds_prim} and has no valid default prim"
            )
        bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        bounds = bbox.ComputeWorldBound(collider).ComputeAlignedRange()
        minimum = tuple(float(value) for value in bounds.GetMin())
        maximum = tuple(float(value) for value in bounds.GetMax())
        if any(maximum[index] <= minimum[index] for index in range(3)):
            raise RuntimeError(f"Collider has invalid bounds: min={minimum}, max={maximum}")

        poses = list(
            _flythrough_poses(minimum, maximum, args.frames)
            if args.camera_mode == "flythrough"
            else _orbit_poses(minimum, maximum, args.frames)
        )
        camera_path = _author_camera_animation(
            stage,
            poses,
            args.fps,
            max(maximum[index] - minimum[index] for index in range(3)) * 4.0,
        )
        print(f"[preview] camera animation prepared: {camera_path}", flush=True)
        options = CaptureOptions()
        options.file_type = ".mp4"
        options.start_frame = 1
        options.end_frame = args.frames
        options.fps = args.fps
        options.animation_fps = args.fps
        options.res_width = args.width
        options.res_height = args.height
        options.render_preset = CaptureRenderPreset.RAY_TRACE
        options.spp_per_iteration = 1
        options.path_trace_spp = 1
        options.output_folder = str(output_dir)
        options.file_name = capture_name
        options.overwrite_existing_frames = True
        options.hdr_output = False
        options.camera = camera_path
        capture = CaptureExtension().get_instance()
        capture.options = options
        print(f"[preview] recording {args.frames} frames at {args.width}x{args.height}", flush=True)
        if not capture.start():
            raise RuntimeError("Isaac Sim viewport capture could not start")
        deadline = time.monotonic() + args.timeout_seconds
        while not capture.done:
            simulation_app.update()
            if time.monotonic() >= deadline:
                capture.cancel()
                raise TimeoutError(f"Capture exceeded {args.timeout_seconds} seconds")
        outputs = [Path(path) for path in capture.get_outputs()]
        if video_path not in outputs or not video_path.is_file() or video_path.stat().st_size == 0:
            raise RuntimeError(f"Viewport capture did not write the expected MP4: {video_path}")
    except Exception as exc:  # noqa: BLE001 - normalize Kit/rendering failures for CLI callers.
        print(f"Scene preview failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        simulation_app.close()

    if not args.keep_frames:
        shutil.rmtree(frames_dir)
    print(f"video={video_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
