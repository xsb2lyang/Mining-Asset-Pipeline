"""Check whether a clone is ready to run the complete asset pipeline.

The checks are intentionally dependency-free so a new contributor can run
this script before installing the project.  It never imports CUDA libraries or
starts Isaac Sim.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    required: bool
    detail: str


def _local_environment() -> dict[str, str]:
    """Read simple ``export NAME=value`` entries without executing shell code."""
    values: dict[str, str] = {}
    path = ROOT / "environments" / "local.env"
    if not path.is_file():
        return values
    pattern = re.compile(r"^export\s+([A-Z][A-Z0-9_]*)=(.*)$")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        name, raw_value = match.groups()
        value = raw_value.strip().strip("\"'")
        value = value.replace("${REPO_ROOT}", str(ROOT)).replace("$REPO_ROOT", str(ROOT))
        values[name] = os.path.expanduser(os.path.expandvars(value))
    return values


def _setting(name: str, local: dict[str, str], default: Path | None = None) -> Path | None:
    value = os.environ.get(name) or local.get(name)
    if value:
        return Path(value).expanduser().resolve()
    return default.resolve() if default is not None else None


def _conda_environments(conda: str) -> set[str]:
    try:
        completed = subprocess.run(
            [conda, "env", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        payload = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return set()
    return {Path(path).name for path in payload.get("envs", []) if isinstance(path, str)}


def _maximum_gpu_memory_mib(nvidia_smi: str) -> int | None:
    try:
        completed = subprocess.run(
            [nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip().isdigit()]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return max(values) if completed.returncode == 0 and values else None


def collect_checks(*, require_llm: bool = False) -> list[Check]:
    local = _local_environment()
    checks = [
        Check(
            "python",
            sys.version_info >= (3, 11),
            True,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
    ]
    for module, package in (("numpy", "numpy"), ("yaml", "PyYAML"), ("PIL", "Pillow")):
        available = importlib.util.find_spec(module) is not None
        detail = "installed" if available else "run: pip install -e ."
        checks.append(Check(f"python:{package}", available, True, detail))
    anthropic_available = importlib.util.find_spec("anthropic") is not None
    anthropic_detail = "installed" if anthropic_available else "run: pip install -e '.[llm]'"
    checks.append(Check("optional:anthropic", anthropic_available, require_llm, anthropic_detail))

    sam3 = ROOT / "third_party" / "sam3" / "sam3" / "model_builder.py"
    sam3d = ROOT / "third_party" / "sam-3d-objects" / "pyproject.toml"
    checks.extend((
        Check("submodule:sam3", sam3.is_file(), True, str(sam3)),
        Check("submodule:sam-3d-objects", sam3d.is_file(), True, str(sam3d)),
    ))

    conda = shutil.which("conda")
    checks.append(Check("command:conda", conda is not None, True, conda or "not found on PATH"))
    environments = _conda_environments(conda) if conda else set()
    sam3_env = os.environ.get("SAM3_ENV", local.get("SAM3_ENV", "sam3"))
    sam3d_env = os.environ.get("SAM3D_ENV", local.get("SAM3D_ENV", "sam3d-objects"))
    checks.extend(
        (
            Check(
                f"conda-env:{sam3_env}",
                sam3_env in environments,
                True,
                "available" if sam3_env in environments else "missing",
            ),
            Check(
                f"conda-env:{sam3d_env}",
                sam3d_env in environments,
                True,
                "available" if sam3d_env in environments else "missing",
            ),
        )
    )

    sam3_checkpoint_dir = _setting("SAM3_CHECKPOINT_DIR", local, ROOT / "checkpoints" / "sam3")
    sam3_checkpoint = sam3_checkpoint_dir / "sam3.pt" if sam3_checkpoint_dir else None
    sam3d_checkpoint_dir = _setting(
        "SAM3D_CHECKPOINT_DIR", local, ROOT / "third_party" / "sam-3d-objects" / "checkpoints" / "hf"
    )
    sam3d_checkpoint = sam3d_checkpoint_dir / "pipeline.yaml" if sam3d_checkpoint_dir else None
    checks.extend((
        Check("checkpoint:sam3", bool(sam3_checkpoint and sam3_checkpoint.is_file()), True, str(sam3_checkpoint)),
        Check("checkpoint:sam-3d-objects", bool(sam3d_checkpoint and sam3d_checkpoint.is_file()), True, str(sam3d_checkpoint)),
    ))

    isaac = _setting("ISAAC_SIM_PATH", local)
    isaac_python = isaac / "python.sh" if isaac else None
    checks.append(
        Check(
            "isaac-sim",
            bool(isaac_python and isaac_python.is_file()),
            True,
            str(isaac_python or "ISAAC_SIM_PATH is unset"),
        )
    )

    nvidia_smi = shutil.which("nvidia-smi")
    checks.append(
        Check(
            "command:nvidia-smi",
            nvidia_smi is not None,
            True,
            nvidia_smi or "NVIDIA driver tools not found",
        )
    )
    memory_mib = _maximum_gpu_memory_mib(nvidia_smi) if nvidia_smi else None
    memory_ok = memory_mib is not None and memory_mib >= 32 * 1024
    memory_detail = (
        f"maximum {memory_mib} MiB; SAM3D recommends at least 32768 MiB"
        if memory_mib is not None
        else "unable to query GPU memory"
    )
    checks.append(Check("gpu-memory", memory_ok, True, memory_detail))
    return checks


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check prerequisites for the Mining Asset Pipeline")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--require-llm", action="store_true", help="Treat the optional Anthropic SDK as required")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    checks = collect_checks(require_llm=args.require_llm)
    passed = all(check.ok for check in checks if check.required)
    if args.json:
        print(json.dumps({"ready": passed, "checks": [asdict(check) for check in checks]}, indent=2))
    else:
        for check in checks:
            marker = "PASS" if check.ok else "FAIL" if check.required else "SKIP"
            print(f"[{marker}] {check.name}: {check.detail}")
        print("\nReady for the full pipeline." if passed else "\nNot ready; resolve the FAIL entries above.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
