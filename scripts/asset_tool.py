#!/usr/bin/env python3
"""Machine-readable CLI for the AgentTools whitelist."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mining_asset_pipeline.agent.models import AssetRequest  # noqa: E402
from mining_asset_pipeline.agent.tools import AgentTools  # noqa: E402


def _payload(path: Path, tools: AgentTools, asset_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    resolved = path.resolve()
    asset_root = tools.store.root(asset_id)
    if resolved != asset_root and asset_root not in resolved.parents:
        raise ValueError("payload files must be inside the active asset bundle")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON/YAML object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled internal tools for the mining asset Agent")
    parser.add_argument("--output-root", type=Path, default=Path(os.environ.get("PIPELINE_OUTPUT_DIR", ROOT / "outputs")))
    parser.add_argument("--sam3-env", default=None)
    parser.add_argument("--sam3d-env", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--image", type=Path, required=True)
    create.add_argument("--prompt", required=True)
    create.add_argument("--asset-category", default="")
    create.add_argument("--target-task", default="")
    create.add_argument("--robot-constraints", default="")
    create.add_argument("--controller", choices=("external_skill", "embedded_claude_api"), default="external_skill")
    create.add_argument("--max-llm-calls", type=int, default=0)
    for name in ("status", "author-usd"):
        action = sub.add_parser(name)
        action.add_argument("--asset-id", required=True)
    for name in ("record-brief", "record-visual-review", "submit-physics", "check-physics"):
        action = sub.add_parser(name)
        action.add_argument("--asset-id", required=True)
        action.add_argument("--payload", type=Path, required=name != "check-physics")
    sam3 = sub.add_parser("run-sam3")
    sam3.add_argument("--asset-id", required=True)
    sam3.add_argument("--prompt", required=True)
    select = sub.add_parser("select-mask")
    select.add_argument("--asset-id", required=True)
    select.add_argument("--candidate-index", type=int, required=True)
    sam3d = sub.add_parser("run-sam3d")
    sam3d.add_argument("--asset-id", required=True)
    sam3d.add_argument("--seed", type=int, choices=(42, 43, 44), required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--asset-id", required=True)
    finalize.add_argument("--quality", choices=("agent_reviewed", "degraded"), default="agent_reviewed")
    finalize.add_argument("--fallback-reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    tools = AgentTools(ROOT, args.output_root)
    if args.sam3_env:
        tools.sam3_env = args.sam3_env
    if args.sam3d_env:
        tools.sam3d_env = args.sam3d_env
    try:
        if args.command == "create":
            result = tools.create(args.image, AssetRequest(args.prompt, args.asset_category, args.target_task, args.robot_constraints), controller=args.controller, max_llm_calls=args.max_llm_calls)
        elif args.command == "status":
            result = tools.status(args.asset_id)
        elif args.command == "record-brief":
            result = tools.record_brief(args.asset_id, _payload(args.payload, tools, args.asset_id))
        elif args.command == "run-sam3":
            result = tools.run_sam3(args.asset_id, args.prompt)
        elif args.command == "select-mask":
            result = tools.select_mask(args.asset_id, args.candidate_index)
        elif args.command == "run-sam3d":
            result = tools.run_sam3d(args.asset_id, args.seed)
        elif args.command == "record-visual-review":
            result = tools.record_visual_review(args.asset_id, _payload(args.payload, tools, args.asset_id))
        elif args.command == "submit-physics":
            result = tools.submit_physics(args.asset_id, _payload(args.payload, tools, args.asset_id))
        elif args.command == "check-physics":
            result = tools.check_physics(args.asset_id, _payload(args.payload, tools, args.asset_id) if args.payload else None)
        elif args.command == "author-usd":
            result = tools.author_usd(args.asset_id)
        else:
            result = tools.finalize(args.asset_id, quality=args.quality, fallback_reason=args.fallback_reason)
    except Exception as exc:  # noqa: BLE001 - CLI always emits one JSON object.
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
