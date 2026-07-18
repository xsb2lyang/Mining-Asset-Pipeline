"""Single public entry point: RGB + rough prompt to a statically checked USD."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.claude_controller import DEFAULT_MODEL, ClaudeAssetController  # noqa: E402
from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus  # noqa: E402
from mining_asset_pipeline.agent.tools import AgentTools  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent-controlled mining asset pipeline: RGB + rough prompt -> final/asset.usd")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="Input RGB image for a new asset")
    source.add_argument("--resume", metavar="ASSET_ID", help="Resume a manifest-v3 asset from its last durable phase")
    parser.add_argument("--prompt", help="Rough prompt for a new asset")
    parser.add_argument("--asset-category", default="")
    parser.add_argument("--target-task", default="")
    parser.add_argument("--robot-constraints", default="")
    parser.add_argument("--output-root", type=Path, default=Path(os.environ.get("PIPELINE_OUTPUT_DIR", ROOT / "outputs")))
    parser.add_argument("--isaac-sim-path", type=Path, default=Path(os.environ["ISAAC_SIM_PATH"]) if os.environ.get("ISAAC_SIM_PATH") else None)
    parser.add_argument("--sam3-env", help="Override $SAM3_ENV or environments/local.env")
    parser.add_argument("--sam3d-env", help="Override $SAM3D_ENV or environments/local.env")
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-llm-calls", type=int, default=8)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def _client() -> tuple[object | None, str | None]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, "ANTHROPIC_API_KEY is not set"
    try:
        import anthropic
    except ImportError:
        return None, "optional anthropic package is not installed"
    try:
        return anthropic.Anthropic(api_key=key), None
    except Exception as exc:  # noqa: BLE001
        return None, f"Anthropic client setup failed: {type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.image is not None:
        if not args.image.is_file():
            print(f"--image not found: {args.image}", file=sys.stderr)
            return 1
        if not args.prompt or not args.prompt.strip():
            print("--prompt is required with --image", file=sys.stderr)
            return 1
    elif args.prompt is not None:
        print("--prompt cannot be used with --resume", file=sys.stderr)
        return 1
    if args.max_llm_calls < 0:
        print("--max-llm-calls cannot be negative", file=sys.stderr)
        return 1
    tools = AgentTools(ROOT, args.output_root)
    if args.sam3_env:
        tools.sam3_env = args.sam3_env
    if args.sam3d_env:
        tools.sam3d_env = args.sam3d_env
    resume_is_complete = False
    if args.resume:
        try:
            resume_is_complete = tools.store.manifest(args.resume).get("status") == AssetStatus.COMPLETE.value
        except (FileNotFoundError, ValueError):
            pass
    if not resume_is_complete:
        isaac_sim_path = args.isaac_sim_path.resolve() if args.isaac_sim_path is not None else tools.isaac_sim_path
        if isaac_sim_path is None or not (isaac_sim_path / "python.sh").is_file():
            print("ISAAC_SIM_PATH must point to an Isaac Sim installation containing python.sh", file=sys.stderr)
            return 1
        os.environ["ISAAC_SIM_PATH"] = str(isaac_sim_path)
    client, client_reason = _client()
    controller = ClaudeAssetController(tools, client, model=args.model, max_calls=args.max_llm_calls)
    if client_reason:
        if not args.quiet:
            print(f"[fallback] {client_reason}", file=sys.stderr)
    try:
        if args.resume:
            manifest = controller.run(args.resume)
            asset_id = args.resume
        else:
            request = AssetRequest(args.prompt, args.asset_category, args.target_task, args.robot_constraints)
            manifest = controller.run_new(args.image, request)
            asset_id = str(manifest["asset_id"])
    except Exception as exc:  # noqa: BLE001
        print(f"Agent pipeline failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    final_usd = tools.store.root(asset_id) / "final" / "asset.usd"
    if manifest.get("status") == AssetStatus.COMPLETE.value and final_usd.is_file():
        print(f"asset_id={asset_id}")
        print(f"final_usd={final_usd}")
        print(f"quality={manifest.get('quality')}")
        return 0
    if manifest.get("status") == AssetStatus.BLOCKED.value:
        print(f"Asset blocked: {manifest.get('error') or manifest.get('events', [{}])[-1].get('message')}", file=sys.stderr)
        return 2
    print(f"Asset ended with status={manifest.get('status')} phase={manifest.get('phase')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
