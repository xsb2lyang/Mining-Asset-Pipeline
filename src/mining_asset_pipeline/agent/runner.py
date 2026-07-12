"""Subprocess adapter for isolated SAM and Isaac Sim tool environments."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Protocol

from .models import ToolResult


class ToolRunner(Protocol):
    def run(self, name: str, command: list[str], cwd: Path, log_path: Path, env: Mapping[str, str] | None = None) -> ToolResult: ...


class SubprocessToolRunner:
    def run(self, name: str, command: list[str], cwd: Path, log_path: Path, env: Mapping[str, str] | None = None) -> ToolResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        process_env = dict(os.environ)
        if env:
            process_env.update(env)
        completed = subprocess.run(command, cwd=cwd, env=process_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
        return ToolResult(returncode=completed.returncode, command=command, log_path=str(log_path))


def isaac_clean_environment() -> dict[str, str]:
    """Avoid leaking an active Conda Python into Isaac Sim's embedded runtime."""
    return {name: "" for name in (
        "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_PROMPT_MODIFIER", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH",
    )}
