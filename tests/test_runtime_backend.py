"""Backend discovery and host inspection tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aistackd.runtime.backends import (
    BackendDiscoveryResult,
    acquire_managed_llama_cpp_installation,
    discover_llama_cpp_installation,
    plan_llama_cpp_acquisition,
)
from aistackd.runtime.hardware import CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION, HardwareProfile, LlmfitDetectionResult
from aistackd.runtime.prereqs import inspect_host_environment


class BackendRuntimeTests(unittest.TestCase):
    def test_discover_llama_cpp_installation_from_explicit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = _create_fake_backend_root(Path(tmpdir))

            discovery = discover_llama_cpp_installation(backend_root=backend_root)

            self.assertTrue(discovery.found)
            self.assertEqual(discovery.discovery_mode, "explicit_root")
            self.assertEqual(discovery.backend_root, str(backend_root))
            self.assertTrue(discovery.server_binary.endswith("llama-server"))
            self.assertTrue(discovery.cli_binary.endswith("llama-cli"))

    def test_acquire_managed_backend_from_prebuilt_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            prebuilt_root = _create_fake_backend_root(Path(tmpdir) / "prebuilt")
            plan = plan_llama_cpp_acquisition(_fake_llmfit_detection().profile)

            result = acquire_managed_llama_cpp_installation(project_root, plan, prebuilt_root=prebuilt_root)

            self.assertEqual(result.strategy, "prebuilt_root")
            self.assertTrue(result.attempts[0].ok)
            self.assertEqual(result.installation.acquisition_method, "acquired_prebuilt_root")
            self.assertTrue(
                str(result.installation.backend_root).endswith(".aistackd/host/backends/llama.cpp/install")
            )
            self.assertTrue(Path(result.installation.server_binary).exists())

    def test_acquire_managed_backend_falls_back_to_source_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            broken_prebuilt_root = Path(tmpdir) / "broken-prebuilt"
            broken_prebuilt_root.mkdir()
            source_root = _create_fake_source_root(Path(tmpdir) / "source")
            plan = plan_llama_cpp_acquisition(
                _fake_llmfit_detection(backend="amd", acceleration_api="rocm", target="gfx1100").profile
            )
            captured_env: dict[str, str] = {}

            with patch(
                "aistackd.runtime.backends.subprocess.run",
                side_effect=lambda command, **kwargs: _fake_backend_subprocess_run(command, captured_env, **kwargs),
            ):
                result = acquire_managed_llama_cpp_installation(
                    project_root,
                    plan,
                    prebuilt_root=broken_prebuilt_root,
                    source_root=source_root,
                    jobs=2,
                )

            self.assertEqual(result.strategy, "source_build")
            self.assertFalse(result.attempts[0].ok)
            self.assertEqual(result.attempts[0].strategy, "prebuilt_root")
            self.assertTrue(result.attempts[-1].ok)
            self.assertEqual(result.attempts[-1].strategy, "source_build")
            self.assertEqual(captured_env["HSA_OVERRIDE_GFX_VERSION"], "11.0.0")
            self.assertEqual(result.installation.acquisition_method, "acquired_source_build")
            self.assertTrue(Path(result.installation.server_binary).exists())

    def test_inspect_host_environment_reports_prerequisite_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = _create_fake_backend_root(Path(tmpdir))

            with (
                patch(
                    "aistackd.runtime.prereqs.shutil.which",
                    side_effect=lambda command: None if command == "node" else f"/usr/bin/{command}",
                ),
                patch(
                    "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                    return_value=_fake_llmfit_detection(),
                ),
            ):
                report = inspect_host_environment(backend_root=backend_root)

            self.assertFalse(report.ok)
            self.assertFalse(report.prerequisites_ok)
            self.assertTrue(report.hardware_detection.ok)
            self.assertTrue(report.backend_discovery.found)
            self.assertIsNotNone(report.acquisition_plan)
            checks = {check.name: check for check in report.prerequisite_checks}
            self.assertFalse(checks["node"].ok)
            self.assertTrue(checks["cmake"].ok)
            self.assertTrue(checks["make"].ok)


class HardwareRuntimeTests(unittest.TestCase):
    def test_detect_hardware_with_llmfit_parses_mixed_output(self) -> None:
        payload = {
            "provider": "ROCm",
            "devices": [
                {"name": "AMD Radeon 7900 XTX", "target": "gfx1100"},
            ],
        }

        with (
            patch("aistackd.runtime.hardware.shutil.which", return_value="/usr/bin/llmfit"),
            patch(
                "aistackd.runtime.hardware.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=("/usr/bin/llmfit", "system", "--json"),
                    returncode=0,
                    stdout=f"llmfit warning\n{json.dumps(payload)}",
                    stderr="",
                ),
            ),
        ):
            from aistackd.runtime.hardware import detect_hardware_with_llmfit

            result = detect_hardware_with_llmfit()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.profile)
        self.assertEqual(result.profile.backend, "amd")
        self.assertEqual(result.profile.acceleration_api, "rocm")
        self.assertIn("-DGPU_TARGETS=gfx1100", result.profile.cmake_flags)

    def test_detect_hardware_with_llmfit_reports_missing_binary(self) -> None:
        with patch("aistackd.runtime.hardware.shutil.which", return_value=None):
            from aistackd.runtime.hardware import detect_hardware_with_llmfit

            result = detect_hardware_with_llmfit()

        self.assertFalse(result.ok)
        self.assertFalse(result.available)
        self.assertIn("'llmfit' was not found on PATH", result.issues)

    def test_inspect_host_environment_generates_acquisition_plan_when_backend_is_missing(self) -> None:
        with (
            patch(
                "aistackd.runtime.prereqs.shutil.which",
                side_effect=lambda command: f"/usr/bin/{command}",
            ),
            patch(
                "aistackd.runtime.prereqs.detect_hardware_with_llmfit",
                return_value=_fake_llmfit_detection(backend="amd", acceleration_api="rocm", target="gfx1100"),
            ),
            patch(
                "aistackd.runtime.prereqs.discover_llama_cpp_installation",
                return_value=BackendDiscoveryResult(
                    backend="llama.cpp",
                    found=False,
                    discovery_mode="path",
                    backend_root=None,
                    server_binary=None,
                    cli_binary=None,
                    issues=("'llama-server' was not found on PATH",),
                ),
            ),
        ):
            report = inspect_host_environment()

        self.assertTrue(report.ok)
        self.assertFalse(report.backend_discovery.found)
        self.assertIsNotNone(report.acquisition_plan)
        self.assertEqual(report.acquisition_plan.flavor, "rocm")
        self.assertEqual(
            dict(report.acquisition_plan.source_environment)["HSA_OVERRIDE_GFX_VERSION"],
            "11.0.0",
        )


def _create_fake_backend_root(root: Path) -> Path:
    backend_root = root / "llama.cpp"
    bin_dir = backend_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for binary_name in ("llama-server", "llama-cli"):
        path = bin_dir / binary_name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return backend_root


def _create_fake_source_root(root: Path) -> Path:
    source_root = root / "llama.cpp"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(llama_cpp)\n", encoding="utf-8")
    return source_root


def _fake_backend_subprocess_run(
    command: list[str],
    captured_env: dict[str, str],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    env = kwargs.get("env")
    if isinstance(env, dict):
        captured_env.update({key: str(value) for key, value in env.items()})

    if command[:2] == ["cmake", "-S"]:
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    if command[:2] == ["cmake", "--build"]:
        build_root = Path(command[2])
        bin_dir = build_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for binary_name in ("llama-server", "llama-cli"):
            path = bin_dir / binary_name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    raise AssertionError(f"unexpected command: {command}")


def _fake_llmfit_detection(
    *,
    backend: str = "nvidia",
    acceleration_api: str = "cuda",
    target: str = "",
) -> LlmfitDetectionResult:
    profile = HardwareProfile(
        schema_version=CURRENT_HARDWARE_PROFILE_SCHEMA_VERSION,
        detector="llmfit",
        backend=backend,
        acceleration_api=acceleration_api,
        target=target,
        cmake_flags=(
            ("-DGGML_HIP=ON", f"-DGPU_TARGETS={target}")
            if acceleration_api == "rocm" and target
            else ("-DGGML_HIP=ON",)
            if acceleration_api == "rocm"
            else ("-DGGML_CUDA=ON",)
            if acceleration_api == "cuda"
            else ()
        ),
        gpu_layers=99 if acceleration_api != "cpu" else 0,
        hsa_override_gfx_version="11.0.0" if acceleration_api == "rocm" else "",
    )
    return LlmfitDetectionResult(
        detector="llmfit",
        available=True,
        ok=True,
        command=("llmfit", "system", "--json"),
        exit_code=0,
        raw_output="{}",
        raw_payload={"provider": backend},
        profile=profile,
    )
