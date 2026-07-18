"""Unattended CLI: drive the asset pipeline end-to-end with no human in the loop.

Image + text prompt in, ``outputs/<asset_id>/final/asset.usd`` out. After the
deterministic visual checks pass, the CLI starts ``run_physics_pipeline``
(Physics Author/Critic multi-round review + USD authoring).

Exit codes:
  0 — pipeline reached ``complete`` and ``final/asset.usd`` exists on disk
  2 — ``blocked``: Physics Author/Critic did not converge in 3 rounds
  1 — any other failure (visual generation, USD authoring, missing inputs)

The CLI requires ``ISAAC_SIM_PATH`` (env var or ``--isaac-sim-path``) because
the USD authoring stage invokes Isaac Sim's ``python.sh``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.models import AssetRequest, AssetStatus  # noqa: E402
from mining_asset_pipeline.agent.prompt_rewriter import rewrite_prompt  # noqa: E402
from mining_asset_pipeline.agent.workflow import AssetWorkflow  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_isaac = None
    if "ISAAC_SIM_PATH" in os.environ:
        default_isaac = Path(os.environ["ISAAC_SIM_PATH"])
    parser = argparse.ArgumentParser(
        description="Unattended mining asset pipeline: RGB + prompt → final/asset.usd",
    )
    parser.add_argument("--image", type=Path, required=True, help="Input RGB image path")
    parser.add_argument("--prompt", required=True, help="Text prompt (e.g. 'a red mug')")
    parser.add_argument("--asset-category", default="", help="Optional asset category (e.g. cup)")
    parser.add_argument("--target-task", default="", help="Optional target task hint")
    parser.add_argument("--robot-constraints", default="", help="Optional robot constraints hint")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("PIPELINE_OUTPUT_DIR", ROOT / "outputs")),
        help="Where asset bundles are written (defaults to $PIPELINE_OUTPUT_DIR or ./outputs)",
    )
    parser.add_argument(
        "--isaac-sim-path",
        type=Path,
        default=default_isaac,
        help="Isaac Sim install root (must contain python.sh); defaults to $ISAAC_SIM_PATH",
    )
    parser.add_argument("--sam3-env", default=os.environ.get("SAM3_ENV", "sam3"), help="Conda env for SAM3")
    parser.add_argument("--sam3d-env", default=os.environ.get("SAM3D_ENV", "sam3d-objects"), help="Conda env for SAM3D")
    parser.add_argument(
        "--rewrite-prompt",
        action="store_true",
        help="Rewrite --prompt through the rule-based rewriter before sending to SAM3",
    )
    parser.add_argument(
        "--use-llm-critic",
        action="store_true",
        help="Use the optional Claude physics critic; fall back to deterministic rules on any LLM error",
    )
    parser.add_argument(
        "--anthropic-api-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="Anthropic API key (defaults to $ANTHROPIC_API_KEY; never persisted)",
    )
    parser.add_argument(
        "--anthropic-model",
        default=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-20250514"),
        help="Claude model used with --use-llm-critic (defaults to $ANTHROPIC_MODEL or claude-sonnet-5-20250514)",
    )
    parser.add_argument("--quiet", action="store_true", help="Only print final result lines, not per-stage progress")
    return parser.parse_args(argv)


def _log(stage: str, message: str, quiet: bool) -> None:
    if quiet:
        return
    print(f"[{time.strftime('%H:%M:%S')}] {stage}: {message}", flush=True)


def _print_failure_diagnostics(workflow: AssetWorkflow, asset_id: str) -> None:
    """Print Physics Critic findings to stderr so CI logs are actionable."""
    root = workflow.store.root(asset_id)
    physics = root / "physics"
    review_paths = sorted(physics.glob("physics_review_*.json"))
    if not review_paths:
        return
    print("  Critic findings:", file=sys.stderr)
    for path in review_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if payload.get("accepted"):
            continue
        round_index = payload.get("round", "?")
        summary = payload.get("summary", "rejected")
        print(f"  - {path.name} (round {round_index}): {summary}", file=sys.stderr)
        for finding in payload.get("findings", []):
            severity = finding.get("severity", "info")
            code = finding.get("code", "?")
            message = finding.get("message", "")
            print(f"      [{severity}] {code}: {message}", file=sys.stderr)


def _build_llm_critic(args: argparse.Namespace):
    """Create the optional critic without making Anthropic a base dependency."""
    if not args.use_llm_critic:
        return None
    if not args.anthropic_api_key:
        print("LLM critic requested but no ANTHROPIC_API_KEY was provided; using deterministic critic.", file=sys.stderr)
        return None
    try:
        import anthropic
        from mining_asset_pipeline.agent.llm_critic import LLMCriticAgent
    except ImportError:
        print("LLM critic requested but the optional anthropic package is unavailable; using deterministic critic.", file=sys.stderr)
        return None
    try:
        client = anthropic.Anthropic(api_key=args.anthropic_api_key)
        return LLMCriticAgent(client=client, model=args.anthropic_model)
    except Exception as exc:  # noqa: BLE001 - setup failure must not disable the deterministic pipeline.
        print(f"LLM critic setup failed ({type(exc).__name__}); using deterministic critic.", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.isaac_sim_path is None:
        print("ISAAC_SIM_PATH is required (set env var or pass --isaac-sim-path)", file=sys.stderr)
        return 1
    if not args.isaac_sim_path.is_dir():
        print(f"--isaac-sim-path is not a directory: {args.isaac_sim_path}", file=sys.stderr)
        return 1
    python_sh = args.isaac_sim_path / "python.sh"
    if not python_sh.is_file():
        print(f"Isaac Sim python.sh not found under --isaac-sim-path: {python_sh}", file=sys.stderr)
        return 1
    if not args.image.is_file():
        print(f"--image not found: {args.image}", file=sys.stderr)
        return 1
    if not args.prompt.strip():
        print("--prompt must not be empty", file=sys.stderr)
        return 1

    original_prompt = args.prompt
    if args.rewrite_prompt:
        args.prompt = rewrite_prompt(args.prompt, args.asset_category)
        if args.prompt != original_prompt and not args.quiet:
            print(f"[rewriter] {original_prompt!r} -> {args.prompt!r}", flush=True)

    os.environ["ISAAC_SIM_PATH"] = str(args.isaac_sim_path)
    workflow = AssetWorkflow(
        repo_root=ROOT,
        output_root=args.output_root,
        critic_agent=_build_llm_critic(args),
    )
    workflow.sam3_env = args.sam3_env
    workflow.sam3d_env = args.sam3d_env

    request = AssetRequest(
        prompt=args.prompt,
        asset_category=args.asset_category,
        target_task=args.target_task,
        robot_constraints=args.robot_constraints,
    )

    try:
        asset_id = workflow.create_asset(args.image, request)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(f"create_asset failed: {exc}", file=sys.stderr)
        return 1

    _log("visual", f"asset_id={asset_id}", args.quiet)
    try:
        manifest = workflow.run_visual(asset_id)
    except (RuntimeError, ValueError) as exc:
        print(f"Loop 1 visual generation failed: {exc}", file=sys.stderr)
        _print_failure_diagnostics(workflow, asset_id)
        return 1
    if manifest.get("status") == AssetStatus.FAILED.value:
        print("Loop 1 visual generation reported status=failed", file=sys.stderr)
        return 1

    _log("physics", f"status={manifest.get('status')}, running automatic physics review", args.quiet)
    try:
        manifest = workflow.run_physics_pipeline(asset_id)
    except (RuntimeError, ValueError) as exc:
        print(f"Automatic physics review or USD authoring failed: {exc}", file=sys.stderr)
        _print_failure_diagnostics(workflow, asset_id)
        return 1

    final_status = manifest.get("status")
    final_usd = workflow.store.root(asset_id) / "final" / "asset.usd"

    if final_status == AssetStatus.COMPLETE.value and final_usd.is_file():
        _log("done", f"asset_id={asset_id} → {final_usd}", args.quiet)
        print(f"asset_id={asset_id}")
        print(f"final_usd={final_usd}")
        return 0

    if final_status == AssetStatus.BLOCKED.value:
        print("Physics Author/Critic did not converge within 3 rounds; status=blocked; USD was not authored.", file=sys.stderr)
        _print_failure_diagnostics(workflow, asset_id)
        return 2

    print(f"Unexpected terminal status: {final_status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
