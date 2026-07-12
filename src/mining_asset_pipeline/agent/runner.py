"""Subprocess adapter for isolated SAM and Isaac Sim tool environments."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterator, Mapping, Protocol

from .models import ToolResult


class ToolRunner(Protocol):
    def run(self, name: str, command: list[str], cwd: Path, log_path: Path, env: Mapping[str, str] | None = None) -> ToolResult: ...
    def stream(self, name: str, command: list[str], cwd: Path, log_path: Path, env: Mapping[str, str] | None = None) -> ToolResult: ...


class SubprocessToolRunner:
    def __init__(self) -> None:
        self._last_returncode: int = 0

    def _popen_logs(
        self,
        command: list[str],
        cwd: Path,
        env: Mapping[str, str] | None,
        log_path: Path,
    ) -> Iterator[str]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        process_env = dict(os.environ)
        if env:
            process_env.update(env)
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            with log_path.open("w", encoding="utf-8", errors="replace") as fh:
                assert proc.stdout is not None
                for line in proc.stdout:
                    fh.write(line)
                    yield line.rstrip("\n")
        finally:
            proc.wait()
            self._last_returncode = proc.returncode

    def run(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        log_path: Path,
        env: Mapping[str, str] | None = None,
    ) -> ToolResult:
        return self.stream(name, command, cwd, log_path, env)

    def stream(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        log_path: Path,
        env: Mapping[str, str] | None = None,
    ) -> ToolResult:
        # Materialise the generator so the subprocess actually runs to completion
        # and the log file is fully written before we hand the ToolResult back.
        for _ in self._popen_logs(command, cwd, env, log_path):
            pass
        return ToolResult(returncode=self._last_returncode, command=command, log_path=str(log_path))


def isaac_clean_environment() -> dict[str, str]:
    """Avoid leaking an active Conda Python into Isaac Sim's embedded runtime."""
    return {name: "" for name in (
        "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_PROMPT_MODIFIER", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH",
    )}