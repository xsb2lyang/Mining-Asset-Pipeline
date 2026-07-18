"""Tests for the dependency-free environment doctor."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def test_conda_environment_names_are_extracted(self) -> None:
        response = type(
            "Response",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {"envs": ["/opt/conda", "/opt/conda/envs/sam3", "/opt/conda/envs/sam3d-objects"]}
                ),
            },
        )()
        with patch.object(doctor.subprocess, "run", return_value=response):
            self.assertEqual(doctor._conda_environments("conda"), {"conda", "sam3", "sam3d-objects"})

    def test_setting_prefers_process_environment(self) -> None:
        with patch.dict(doctor.os.environ, {"ISAAC_SIM_PATH": "/process/isaac"}, clear=False):
            value = doctor._setting("ISAAC_SIM_PATH", {"ISAAC_SIM_PATH": "/file/isaac"})
        self.assertEqual(value, Path("/process/isaac"))

    def test_gpu_memory_returns_largest_device(self) -> None:
        response = type("Response", (), {"returncode": 0, "stdout": "24576\n49140\n"})()
        with patch.object(doctor.subprocess, "run", return_value=response):
            self.assertEqual(doctor._maximum_gpu_memory_mib("nvidia-smi"), 49140)

    def test_main_fails_when_a_required_check_fails(self) -> None:
        checks = [doctor.Check("required", False, True, "missing"), doctor.Check("optional", False, False, "missing")]
        with patch.object(doctor, "collect_checks", return_value=checks):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(doctor.main(["--json"]), 1)

    def test_main_passes_when_only_optional_check_fails(self) -> None:
        checks = [doctor.Check("required", True, True, "ok"), doctor.Check("optional", False, False, "missing")]
        with patch.object(doctor, "collect_checks", return_value=checks):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(doctor.main(["--json"]), 0)


if __name__ == "__main__":
    unittest.main()
