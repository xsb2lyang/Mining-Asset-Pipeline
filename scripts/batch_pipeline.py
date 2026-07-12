"""Batch wrapper for the unattended single-asset pipeline.

Each manifest entry is delegated unchanged to ``scripts/run_pipeline.py`` in a
fresh subprocess.  Keeping that script as the single source of truth prevents
the batch path from drifting from the already validated single-image workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_TO_CLEAR = (
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "CONDA_SHLVL",
    "CONDA_PROMPT_MODIFIER",
    "PYTHONPATH",
    "PYTHONHOME",
    "LD_LIBRARY_PATH",
)
SINGLE_ASSET_TIMEOUT_SECONDS = 3600


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run scripts/run_pipeline.py for every entry in a JSON manifest.",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="JSON list of image/prompt entries")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(os.environ.get("PIPELINE_OUTPUT_DIR", ROOT / "outputs")),
        help="Asset bundle root (defaults to $PIPELINE_OUTPUT_DIR or ./outputs)",
    )
    parser.add_argument(
        "--isaac-sim-path",
        type=Path,
        default=Path(os.environ["ISAAC_SIM_PATH"]) if os.environ.get("ISAAC_SIM_PATH") else None,
        help="Isaac Sim install root; defaults to $ISAAC_SIM_PATH",
    )
    parser.add_argument("--summary", type=Path, help="Summary JSON path (default: <output-root>/batch_summary_<timestamp>.json)")
    parser.add_argument("--continue-on-error", action="store_true", help="Process remaining entries after a blocked/failed item")
    return parser.parse_args(argv)


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"--manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to parse JSON manifest {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError("Manifest root must be a JSON list")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Manifest entry {index} must be an object")
        for field in ("image", "prompt"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Manifest entry {index} requires non-empty string field '{field}'")
        for field in ("asset_category", "target_task", "robot_constraints"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"Manifest entry {index} field '{field}' must be a string")
        if "rewrite_prompt" in item and not isinstance(item["rewrite_prompt"], bool):
            raise ValueError(f"Manifest entry {index} field 'rewrite_prompt' must be a boolean")
    return payload


def _clean_environment(isaac_sim_path: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    for name in ENVIRONMENT_TO_CLEAR:
        env.pop(name, None)
    if isaac_sim_path is not None:
        env["ISAAC_SIM_PATH"] = str(isaac_sim_path)
    return env


def _parse_single_asset_stdout(stdout: str) -> tuple[str | None, str | None]:
    asset_id = None
    final_usd = None
    for line in stdout.splitlines():
        if line.startswith("asset_id="):
            asset_id = line.split("=", 1)[1].strip() or None
        elif line.startswith("final_usd="):
            final_usd = line.split("=", 1)[1].strip() or None
    return asset_id, final_usd


def run_one(item: dict[str, Any], output_root: Path, isaac_sim_path: Path | None) -> dict[str, Any]:
    """Run one manifest item through the single-source-of-truth CLI."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_pipeline.py"),
        "--image", item["image"],
        "--prompt", item["prompt"],
        "--output-root", str(output_root),
        "--quiet",
    ]
    optional_args = {
        "asset_category": "--asset-category",
        "target_task": "--target-task",
        "robot_constraints": "--robot-constraints",
    }
    for field, flag in optional_args.items():
        if item.get(field):
            command.extend((flag, item[field]))
    if isaac_sim_path is not None:
        command.extend(("--isaac-sim-path", str(isaac_sim_path)))
    if item.get("rewrite_prompt", False):
        command.append("--rewrite-prompt")

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_clean_environment(isaac_sim_path),
            capture_output=True,
            text=True,
            timeout=SINGLE_ASSET_TIMEOUT_SECONDS,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 1
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimed out after {SINGLE_ASSET_TIMEOUT_SECONDS} seconds."
    except OSError as exc:
        exit_code = 1
        stdout = ""
        stderr = str(exc)

    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    asset_id, final_usd = _parse_single_asset_stdout(stdout)
    status = "complete" if exit_code == 0 else "blocked" if exit_code == 2 else "failed"
    return {
        "image": item["image"],
        "asset_id": asset_id,
        "final_usd": final_usd,
        "exit_code": exit_code,
        "status": status,
        "stderr_tail": "\n".join(stderr.splitlines()[-20:]),
    }


def _default_summary_path(output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return output_root / f"batch_summary_{timestamp}.json"


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_progress(index: int, total: int, result: dict[str, Any]) -> None:
    image_name = Path(result["image"]).name
    if result["status"] == "complete":
        detail = result["final_usd"] or "final USD path was not reported"
    elif result["status"] == "blocked":
        detail = "see asset physics_review_*.json"
    else:
        detail = result["stderr_tail"].splitlines()[-1] if result["stderr_tail"] else "see subprocess stderr"
    print(f"[{index}/{total}] {result['status']}: {detail}  (image={image_name})", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        items = _load_manifest(args.manifest)
    except ValueError as exc:
        print(f"Invalid batch manifest: {exc}", file=sys.stderr)
        return 2

    output_root = args.output_root
    summary_path = args.summary or _default_summary_path(output_root)
    started_at = _utc_now()
    results: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        result = run_one(item, output_root, args.isaac_sim_path)
        results.append(result)
        _print_progress(index, len(items), result)
        if result["status"] != "complete" and not args.continue_on_error:
            break

    summary = {
        "started_at": started_at,
        "finished_at": _utc_now(),
        "total": len(items),
        "processed": len(results),
        "complete": sum(result["status"] == "complete" for result in results),
        "blocked": sum(result["status"] == "blocked" for result in results),
        "failed": sum(result["status"] == "failed" for result in results),
        "results": results,
    }
    _write_summary(summary_path, summary)
    print(f"summary={summary_path}", flush=True)
    return 0 if len(results) == len(items) and summary["complete"] == len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
